"""Construit le dataset figé : 500 exemples du split test de Banking77.

Le dataset HuggingFace PolyAI/banking77 est un dataset à script : son loader
télécharge lui-même test.csv depuis le dépôt GitHub de PolyAI. On lit donc
directement cette source amont, ce qui évite la dépendance `datasets`
(et pyarrow/pandas avec elle).

Les labels sont repris tels quels, sans transformation.
Provenance et licence : voir data/README.md.
"""

import csv
import hashlib
import io
import json
import random
import urllib.request
from pathlib import Path

TEST_CSV_URL = (
    "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets"
    "/master/banking_data/test.csv"
)
SEED = 42
N_SAMPLE = 500
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "banking77_500.jsonl"

raw = urllib.request.urlopen(TEST_CSV_URL).read()
print(f"test.csv          : {len(raw)} octets")
print(f"sha256            : {hashlib.sha256(raw).hexdigest()}")

# Même dialecte que le loader HuggingFace, pour que les index de ligne
# correspondent à ceux du split test tel que `datasets` le numérotait.
reader = csv.reader(
    io.StringIO(raw.decode("utf-8")),
    quotechar='"',
    delimiter=",",
    quoting=csv.QUOTE_ALL,
    skipinitialspace=True,
)
header = next(reader)
assert header == ["text", "category"], header
rows = [(text, category) for text, category in reader]
print(f"split test        : {len(rows)} exemples, {len({c for _, c in rows})} labels")

# Tirage uniforme sans remise, puis tri : l'ordre du fichier ne dépend pas
# de l'ordre de tirage, seulement de la graine.
indices = sorted(random.Random(SEED).sample(range(len(rows)), N_SAMPLE))

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", encoding="utf-8", newline="\n") as out:
    for i in indices:
        text, category = rows[i]
        # id = index de la ligne dans le split test d'origine, conservé tel quel.
        record = {"id": i, "text": text, "gold_label": category}
        out.write(json.dumps(record, ensure_ascii=False) + "\n")

print(f"écrit             : {OUT_PATH}")
print(f"                    {N_SAMPLE} lignes, "
      f"{len({rows[i][1] for i in indices})} labels représentés")
