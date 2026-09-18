"""Hook PreToolUse : point d'observation. Il n'appelle aucun modele.

CE QUE FAIT CE FICHIER
Il lit l'evenement PreToolUse sur stdin, en extrait de quoi reconstruire plus
tard la decision, et ajoute une ligne a results/raw/gate_observations.jsonl.
C'est tout.

CE QU'IL NE FAIT PAS, ET POURQUOI
- *Aucun appel API.* Un hook PreToolUse est bloquant : deux appels reseau
  ajouteraient quelques secondes a CHAQUE outil de la session observee. Les
  appels sont faits hors ligne par run_gate.py, sur le fichier d'observations.
  C'est aussi la regle du depot : run et analyse sont separes.
- *Aucune lecture du transcript.* La doc precise que le transcript est ecrit de
  facon asynchrone et peut etre en retard quand le hook se declenche : y lire le
  tour courant donnerait parfois le tour PRECEDENT, sans que rien ne le signale.
  Le hook enregistre `prompt_id`, et resolve.py fait la jointure apres coup,
  quand le fichier est complet.
- *Aucune decision.* Il sort toujours en 0 avec une sortie standard vide, ce qui
  laisse l'appel suivre le flux de permission normal. Un hook qui se tait
  n'approuve rien.
- *Aucune exception qui remonte.* Toute erreur est ecrite dans un fichier
  d'erreurs a cote, jamais sur stdout, et le code de sortie reste 0 : observer
  l'agent ne doit pas pouvoir casser la session de l'agent.

INSTALLATION -- voir docs/METHOD_GATE.md. Le hook doit etre installe avec le
matcher "*" : restreindre aux outils ecrivains biaiserait la distribution
collectee, qui est justement ce qu'on mesure.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "raw" / "gate_observations.jsonl"
ERRORS = ROOT / "results" / "raw" / "gate_hook_errors.log"

#: Plafond par valeur d'argument. Il borne le cout du run -- les arguments de
#: Write ou d'Edit portent des fichiers entiers -- et limite ce qui est recopie
#: dans un fichier destine a etre commite. La troncature est SIGNALEE dans la
#: valeur, et la representation canonique envoyee aux deux modeles est la
#: version tronquee : la parite porte sur ce qui est reellement envoye.
MAX_ARGUMENT_CHARS = 2000
SCHEMA_VERSION = 1

#: Formes de secrets connues, redigees avant toute ecriture sur disque. La liste
#: n'est pas une garantie : docs/METHOD_GATE.md impose une relecture du fichier
#: avant commit.
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bpypi-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b[A-Za-z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*\s*=\s*\S+",
               re.IGNORECASE),
)


def _env_secrets() -> list[str]:
    """Valeurs litterales du .env, redigees par egalite exacte."""
    values: list[str] = []
    env = ROOT / ".env"
    if not env.exists():
        return values
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            value = line.split("=", 1)[1].strip().strip("'\"")
            if len(value) >= 8:
                values.append(value)
    return values


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "[REDACTED]")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def clean(value, secrets: list[str]):
    """Redige et tronque, en preservant la forme de l'argument."""
    if isinstance(value, str):
        cleaned = redact(value, secrets)
        if len(cleaned) > MAX_ARGUMENT_CHARS:
            dropped = len(cleaned) - MAX_ARGUMENT_CHARS
            cleaned = cleaned[:MAX_ARGUMENT_CHARS] + f"\n[... {dropped} characters truncated]"
        return cleaned
    if isinstance(value, dict):
        return {k: clean(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v, secrets) for v in value]
    return value


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # stdin illisible : on n'observe rien, on ne gene rien.

    try:
        secrets = _env_secrets()
        record = {
            "schema_version": SCHEMA_VERSION,
            # tool_use_id est l'identifiant de reprise : unique par appel d'outil,
            # et c'est aussi la cle de jointure avec le transcript.
            "tool_use_id": event.get("tool_use_id"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": event.get("session_id"),
            "prompt_id": event.get("prompt_id"),
            "transcript_path": event.get("transcript_path"),
            "cwd": event.get("cwd"),
            "permission_mode": event.get("permission_mode"),
            "tool_name": event.get("tool_name"),
            "tool_input": clean(event.get("tool_input"), secrets),
            "truncated_at": MAX_ARGUMENT_CHARS,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception as error:  # observer ne doit jamais casser la session
        try:
            ERRORS.parent.mkdir(parents=True, exist_ok=True)
            with ERRORS.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{datetime.now(timezone.utc).isoformat()} {error!r}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    # Jamais rien sur stdout : une sortie vide en code 0 ne decide rien.
    sys.exit(main())
