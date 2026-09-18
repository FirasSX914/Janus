"""Exporte les modules de labels en JSON, le format que lit `janus measure`.

Le JSON est un export FIDELE du module : meme enonce, memes criteres, meme
ordre. Le script le verifie en recalculant le `prompt_hash` et en le comparant
a celui inscrit dans les JSONL bruts commites -- si les deux coincident, le
fichier decrit exactement ce qui a ete envoye a l'API pendant la mesure.

    python experiments/export_labels.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "src"))

from janus.providers.base import prompt_hash  # noqa: E402
from janus.types import Question  # noqa: E402

TASKS = {
    "banking77": ("labels", "jev_banking77_500.jsonl"),
    "wos": ("labels_wos", "jev_wos_500.jsonl"),
}


def main() -> int:
    failures = 0
    for task, (module_name, raw_name) in TASKS.items():
        module = __import__(module_name)
        criteria = {name: description for _, name, description in module.LABELS}
        question = Question(instructions=module.INSTRUCTIONS, criteria=criteria)

        out = ROOT / "data" / f"{task}.labels.json"
        out.write_text(json.dumps({"instructions": question.instructions,
                                   "labels": criteria}, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

        first = json.loads((ROOT / "results" / "raw" / raw_name)
                           .read_text(encoding="utf-8").splitlines()[0])
        measured, exported = first["prompt_hash"], prompt_hash(question)
        ok = measured == exported
        failures += not ok
        print(f"{out.relative_to(ROOT)}  {len(criteria)} labels  "
              f"prompt_hash {'==' if ok else '!='} run  {exported[:16]}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
