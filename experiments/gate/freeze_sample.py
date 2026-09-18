"""Fige l'echantillon mesure dans une liste d'ids explicite. Aucun appel API.

POURQUOI UN FICHIER PLUTOT QU'UNE GRAINE
Le tirage d'origine portait sur les decisions RESTANTES au moment du lancement.
Il depend donc du nombre de lignes deja ecrites, et le run a ete interrompu deux
fois : rejouer la meme graine sur un fichier plus avance ne redonne pas le meme
sous-ensemble. Une graine ne suffit pas a definir cet echantillon.

La liste d'ids, elle, le definit entierement. Elle est commitee, contrairement
aux observations brutes, et c'est elle qui rend l'echantillon verifiable.

RECONSTRUCTION DU TIRAGE D'ORIGINE
Les 76 premieres lignes du fichier de reference sont celles qui etaient ecrites
au moment du tirage. On retire leurs ids des 569, ce qui rend les 493
restantes dans l'ordre du fichier de decisions, et on rejoue exactement
`random.Random(SEED).sample(restantes, 324)`.

    python experiments/gate/freeze_sample.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "results" / "raw"
OUT = ROOT / "data" / "gate_sample_400.json"

SEED = 20260918
TARGET_N = 400
#: Lignes de reference deja ecrites au moment du tirage d'origine.
DONE_AT_DRAW = 76


def main() -> int:
    decisions = [json.loads(line) for line
                 in (RAW / "gate_decisions.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    written = [json.loads(line) for line
               in (RAW / "gate_reference.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]

    seeded = [row["id"] for row in written[:DONE_AT_DRAW]]
    remaining = [row for row in decisions if row["id"] not in set(seeded)]
    drawn = random.Random(SEED).sample(remaining, TARGET_N - DONE_AT_DRAW)
    sample = sorted(set(seeded) | {row["id"] for row in drawn})

    # Verification : tout ce qui a deja ete paye doit tomber dans l'echantillon.
    # Sinon la reconstruction du tirage est fausse et on paierait deux fois.
    paid = {row["id"] for row in written}
    stray = paid - set(sample)
    if stray:
        raise SystemExit(f"Reconstruction fausse : {len(stray)} lignes deja payees "
                         f"sont hors de l'echantillon reconstruit.")
    if len(sample) != TARGET_N:
        raise SystemExit(f"{len(sample)} ids au lieu de {TARGET_N}.")

    by_id = {row["id"]: row for row in decisions}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "n": TARGET_N,
        "seed": SEED,
        "drawn_from": len(remaining),
        "seeded_prefix": DONE_AT_DRAW,
        "prompt_hash": decisions[0]["prompt_hash"],
        "note": ("The 76 seeded ids are the consecutive rows written before the "
                 "draw; the other 324 were drawn at random from the rows left at "
                 "that moment. This file, not the seed, defines the sample."),
        "ids": sample,
    }, indent=2) + "\n", encoding="utf-8")

    from collections import Counter
    sources = Counter(by_id[i]["source"] for i in sample)
    print(f"echantillon fige : {len(sample)} ids -> {OUT.relative_to(ROOT)}")
    print(f"  deja payees dedans : {len(paid)}   a faire : {len(sample) - len(paid)}")
    print(f"  par source : " + "  ".join(f"{k} {v}" for k, v in sources.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
