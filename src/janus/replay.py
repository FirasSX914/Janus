"""Rejouer une mesure depuis des JSONL bruts, sans appeler personne.

Une politique enregistre son balayage complet pour qu'on puisse la rejouer a
une autre cible sans repayer un seul appel. `--replay` fait la meme chose un
cran plus bas : il repart des JSONL bruts que `measure` a ecrits et refait la
mesure entiere hors ligne.

La garantie est executable. Les fournisseurs rendus ici levent une exception
si on les appelle : le run ne peut aboutir que si toutes les lignes sont deja
la, et il echoue bruyamment sinon plutot que de completer en silence.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

#: Les deux mesures commitees dans le depot Janus. Ce sont des exemples, pas
#: une partie du paquet installe : les fichiers vivent dans le depot.
TASKS: dict[str, dict[str, str]] = {
    "banking77": {
        "dataset": "data/banking77_500.jsonl",
        "labels": "data/banking77.labels.json",
        "primary": "results/raw/jev_banking77_500.jsonl",
        "fallback": "results/raw/deepseek_banking77_500.jsonl",
    },
    "wos": {
        "dataset": "data/wos_500.jsonl",
        "labels": "data/wos.labels.json",
        "primary": "results/raw/jev_wos_500.jsonl",
        "fallback": "results/raw/deepseek_wos_500.jsonl",
    },
}

#: Le runner de experiments/ n'ecrit pas cost_usd ; le fournisseur du paquet le
#: ferait. Meme tarif que cascade.py.
JEV_USD_PER_MTOK = 0.042


class OfflineProvider:
    """Fournisseur qui refuse d'etre appele. Le hors-ligne devient verifiable."""

    def __init__(self, name: str, model: str) -> None:
        self.name, self.model = name, model

    def ask(self, input: str, question):
        raise RuntimeError(
            f"--replay: {self.name} was asked to answer, which means a row is "
            "missing from the recorded raw JSONL. Replay measures nothing new.")

    def cost_usd(self, answer, when) -> float:
        raise RuntimeError("--replay prices nothing: costs are read from the raw JSONL")


def resolve_task(name: str, root: Path) -> dict[str, Path]:
    """Chemins d'une tache commitee, relatifs a la racine du depot."""
    spec = TASKS[name]
    paths = {key: root / value for key, value in spec.items()}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise SystemExit(
            f"--task {name} replays a measurement committed in the Janus "
            f"repository, and these files are not here:\n  "
            + "\n  ".join(missing)
            + f"\nRun it from a clone of the repository, or pass --dataset, "
              "--labels and --raw-dir yourself.")
    return paths


def stage_artifacts(primary: Path, fallback: Path) -> Path:
    """Copie les deux JSONL sous les noms que `measure` attend."""
    artifacts = Path(tempfile.mkdtemp(prefix="janus_replay_"))
    rows = [json.loads(line) for line in primary.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    for row in rows:
        row.setdefault("cost_usd", row["input_tokens"] / 1e6 * JEV_USD_PER_MTOK)
    (artifacts / "primary.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")
    shutil.copy(fallback, artifacts / "fallback.jsonl")
    return artifacts
