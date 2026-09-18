"""Extraction retrospective : les appels d'outils de transcripts deja ecrits.

Meme sortie que le hook, plus une colonne `source`. Aucun appel API.

LISTE BLANCHE OBLIGATOIRE
Les projets sont des arguments positionnels. Il n'y a AUCUNE valeur par defaut :
sans argument, le script s'arrete. Rien en dehors de la liste n'est ouvert, pas
meme pour compter. C'est la garantie de perimetre, et elle est structurelle --
le script ne sait pas enumerer `~/.claude/projects/`.

    python experiments/gate/extract.py \
        C--Users-ayadi-Documents-Projects-Calibre=janus \
        C--Users-ayadi-Documents-Projects-Saas-Tenor-code-tenor=tenor

D'OU VIENT LE prompt_id
Dans un transcript, `promptId` est porte par les lignes `user` et par AUCUNE
ligne `assistant` -- or ce sont les lignes `assistant` qui portent les blocs
`tool_use`. On remonte donc la chaine `parentUuid` depuis le bloc jusqu'au
premier tour utilisateur reel, et on en prend le `promptId`. Jointure
structurelle, pas heuristique : elle suit le lien de parente ecrit dans le
fichier. Si la chaine n'aboutit pas, `prompt_id` sort nul et resolve.py classe
l'observation JOIN_MISSING.

Voir docs/METHOD_GATE.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hook import MAX_ARGUMENT_CHARS, SCHEMA_VERSION, _env_secrets, clean  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "raw" / "gate_observations.jsonl"


def real_turn_text(row: dict) -> str | None:
    """Le texte d'un vrai tour utilisateur, ou None si ce n'en est pas un.

    Un resultat d'outil est ecrit comme un message `user` : il ne compte pas.
    Les injections de la machinerie sont marquees `isMeta` et ne comptent pas
    non plus.
    """
    if row.get("isMeta"):
        return None
    content = row.get("message", {}).get("content")
    if isinstance(content, str):
        return content.strip() or None
    blocks = [b for b in (content or []) if isinstance(b, dict)]
    if any(b.get("type") == "tool_result" for b in blocks):
        return None
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return text.strip() or None


def anchor_of(row: dict, by_uuid: dict[str, dict]) -> dict | None:
    """Remonte parentUuid jusqu'au tour utilisateur qui ancre cet appel."""
    node, seen = row, set()
    while node is not None:
        uuid = node.get("uuid")
        if uuid in seen:
            return None  # cycle : on ne devine pas
        seen.add(uuid)
        if node.get("type") == "user" and real_turn_text(node) is not None:
            return node
        node = by_uuid.get(node.get("parentUuid"))
    return None


def extract_file(path: Path, source: str, secrets: list[str]) -> list[dict]:
    rows, by_uuid = [], {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(row)
            if row.get("uuid"):
                by_uuid[row["uuid"]] = row

    observations = []
    for row in rows:
        if row.get("type") != "assistant":
            continue
        for block in (row.get("message", {}).get("content") or []):
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            anchor = anchor_of(row, by_uuid)
            observations.append({
                "schema_version": SCHEMA_VERSION,
                "tool_use_id": block.get("id"),
                "timestamp": row.get("timestamp"),
                "session_id": row.get("sessionId") or path.stem,
                "prompt_id": (anchor or {}).get("promptId"),
                "transcript_path": str(path),
                "cwd": row.get("cwd"),
                "permission_mode": row.get("permissionMode"),
                "tool_name": block.get("name"),
                "tool_input": clean(block.get("input"), secrets),
                "truncated_at": MAX_ARGUMENT_CHARS,
                "source": source,
            })
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "projects", nargs="+", metavar="FOLDER[=SOURCE]",
        help="dossier de ~/.claude/projects a lire, avec un nom de source "
             "optionnel. Obligatoire : aucun defaut, rien d'autre n'est ouvert.")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    whitelist: list[tuple[str, str]] = []
    for item in args.projects:
        folder, _, source = item.partition("=")
        whitelist.append((folder, source or folder))

    # Verification du perimetre AVANT d'ouvrir quoi que ce soit.
    missing = [f for f, _ in whitelist if not (PROJECTS / f).is_dir()]
    if missing:
        parser.error("dossier(s) introuvable(s) : " + ", ".join(missing))

    secrets = _env_secrets()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    total, seen_ids = 0, set()
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for folder, source in whitelist:
            files = sorted((PROJECTS / folder).glob("*.jsonl"))
            per_source = 0
            for path in files:
                for observation in extract_file(path, source, secrets):
                    # tool_use_id est l'identifiant de reprise : un doublon
                    # serait une meme decision comptee deux fois.
                    if observation["tool_use_id"] in seen_ids:
                        continue
                    seen_ids.add(observation["tool_use_id"])
                    out.write(json.dumps(observation, ensure_ascii=False) + "\n")
                    per_source += 1
            out.flush()
            os.fsync(out.fileno())
            print(f"{source:10s} {len(files)} session(s)  {per_source} appels d'outils")
            total += per_source

    print(f"\n{total} observations -> {args.out}")
    print("Fichier NON commite : gate_*.jsonl est dans .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
