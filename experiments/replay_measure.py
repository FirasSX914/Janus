"""Rejoue `janus measure` sur les JSONL commites. AUCUN appel API.

    python experiments/replay_measure.py --task banking77 --top 1
    python experiments/replay_measure.py --task wos --top 1

La garantie n'est pas declarative : les fournisseurs passes a `measure()` levent
une exception si on les appelle. Le run ne peut aboutir que parce que les 500
lignes sont deja dans les fichiers d'artefacts, donc que la liste `todo` est
vide. C'est le vrai `measure()` du paquet et le vrai `_print_report` de la CLI
qui tournent : rien n'est reimplemente pour la demonstration.

`--top N` ne garde que N seuils autour du point retenu. Le balayage complet part
dans le rapport, comme toujours.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from janus import cli  # noqa: E402
from janus.labels import from_json  # noqa: E402
from janus.measure import measure  # noqa: E402

#: Meme tarif que cascade.py. Le runner Jev de experiments/ n'ecrit pas de
#: colonne cost_usd ; le fournisseur du paquet, lui, l'ecrirait. On la calcule
#: ici sans toucher a aucune autre colonne.
JEV_USD_PER_MTOK = 0.042

TASKS = {
    "banking77": ("data/banking77_500.jsonl", "data/banking77.labels.json",
                  "results/raw/jev_banking77_500.jsonl",
                  "results/raw/deepseek_banking77_500.jsonl"),
    "wos": ("data/wos_500.jsonl", "data/wos.labels.json",
            "results/raw/jev_wos_500.jsonl",
            "results/raw/deepseek_wos_500.jsonl"),
}


class OfflineOnly:
    """Tout appel est une erreur : ce replay ne doit rien couter."""

    def __init__(self, name: str, model: str) -> None:
        self.name, self.model = name, model

    def ask(self, input, question):
        raise AssertionError(f"{self.name} was called - this replay is offline")

    def cost_usd(self, answer, when):
        raise AssertionError("cost_usd was called - nothing is priced live")


def rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", choices=sorted(TASKS), required=True)
    parser.add_argument("--top", type=int, default=None,
                        help="n'afficher que N seuils autour du point retenu")
    parser.add_argument("--quiet", action="store_true",
                        help="taire la progression de la reprise")
    args = parser.parse_args()

    data, labels, primary_raw, fallback_raw = TASKS[args.task]
    question = from_json(ROOT / labels)
    examples = rows_of(ROOT / data)

    artifacts = Path(tempfile.mkdtemp(prefix=f"janus_replay_{args.task}_"))
    try:
        primary = rows_of(ROOT / primary_raw)
        for row in primary:
            row.setdefault("cost_usd", row["input_tokens"] / 1e6 * JEV_USD_PER_MTOK)
        (artifacts / "primary.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in primary),
            encoding="utf-8")
        shutil.copy(ROOT / fallback_raw, artifacts / "fallback.jsonl")

        result = measure(
            examples=examples, question=question,
            primary=OfflineOnly("typesafe", "jev-latest"),
            fallback=OfflineOnly("deepseek", "deepseek-v4-pro"),
            artifacts=artifacts,
            dataset_fingerprint={"dataset": Path(data).name},
            progress=(lambda message: None) if args.quiet else print,
        )
        print(f"dataset   : {data}, {len(examples)} rows")
        print(f"question  : {len(question)} classes")
        print("primary   : typesafe:jev-latest")
        print("fallback  : deepseek:deepseek-v4-pro")
        cli._print_report(result, top=args.top)
    finally:
        shutil.rmtree(artifacts, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
