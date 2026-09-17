"""Construit le dataset figé : 500 résumés du Web of Science WOS-46985.

Source : archive Mendeley Data 9rw3vkcfy4 v6 (Kowsari et al., HDLTex).

On lit le classeur `Meta-data/Data.xlsx`, et non les fichiers `WOS46985/*.txt`.
Raison : les trois systèmes de labels de l'archive se contredisent — `Y.txt`
donne 134 classes, les couples `(YL1, YL2)` en donnent 133, le `Meta-data` en
donne 145 — et `Y.txt` ne contient que des indices, dont la correspondance vers
les noms est ambiguë sur 10 valeurs. Le `Meta-data` est la seule source
auto-cohérente : chaque ligne y porte son propre `Domain` et sa propre `area`.
Voir data/README.md et docs/METHOD.md.

Le label est le **couple** `Domain/area` : `Depression` et `Schizophrenia`
existent sous deux domaines, donc `area` seule ne suffit pas à identifier une
classe.

Aucune dépendance hors stdlib : un .xlsx est un zip de XML, on le streame en
deux passes pour ne résoudre que les chaînes réellement utilisées.
"""

import collections
import hashlib
import io
import json
import random
import re
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ARCHIVE_URL = (
    "https://data.mendeley.com/public-files/datasets/9rw3vkcfy4/files/"
    "c9ea673d-5542-44c0-ab7b-f1311f7d61df/file_downloaded"
)
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SEED = 42          # même rôle, même graine que le sous-échantillonnage Banking77
N_SAMPLE = 500
# Colonnes du classeur, dans l'ordre annoncé par le ReadMe de l'archive :
# Y1, Y2, Y, Domain, area, keywords, Abstract
COL_DOMAIN, COL_AREA, COL_ABSTRACT = "D", "E", "G"

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "wos_500.jsonl"
CACHE = ROOT / "data" / ".cache_wos.zip"


def fetch_archive() -> bytes:
    if CACHE.exists():
        print(f"archive en cache   : {CACHE}")
        return CACHE.read_bytes()
    print("téléchargement de l'archive Mendeley (~60 Mo)…")
    raw = urllib.request.urlopen(ARCHIVE_URL).read()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(raw)
    return raw


def sheet_rows(book: zipfile.ZipFile) -> list[dict[str, int]]:
    """Première passe : pour chaque ligne, les index de chaînes partagées."""
    rows: list[dict[str, int]] = []
    with book.open("xl/worksheets/sheet1.xml") as handle:
        current: dict[str, int] = {}
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag == f"{NS}c":
                match = re.match(r"([A-Z]+)", element.get("r", ""))
                value = element.findtext(f"{NS}v")
                # `t="s"` : la cellule référence la table des chaînes partagées.
                if match and value is not None and element.get("t") == "s":
                    current[match.group(1)] = int(value)
                element.clear()
            elif element.tag == f"{NS}row":
                if current:
                    rows.append(current)
                current = {}
                element.clear()
    return rows


def resolve(book: zipfile.ZipFile, wanted: set[int]) -> dict[int, str]:
    """Seconde passe : ne matérialise que les chaînes demandées."""
    strings: dict[int, str] = {}
    index = 0
    with book.open("xl/sharedStrings.xml") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag == f"{NS}si":
                if index in wanted:
                    strings[index] = "".join(element.itertext()).strip()
                index += 1
                element.clear()
    return strings


def main() -> None:
    raw = fetch_archive()
    print(f"sha256 archive     : {hashlib.sha256(raw).hexdigest()}")
    outer = zipfile.ZipFile(io.BytesIO(raw))
    book = zipfile.ZipFile(io.BytesIO(outer.read("Meta-data/Data.xlsx")))

    rows = sheet_rows(book)
    header, rows = rows[0], rows[1:]   # la première ligne est un en-tête
    assert len(rows) == 46985, len(rows)
    print(f"lignes de données  : {len(rows)}")

    # Les libellés de classe : peu nombreux, on les résout tous.
    label_ids = {r[c] for r in rows for c in (COL_DOMAIN, COL_AREA) if c in r}
    # Les résumés : seulement ceux de l'échantillon.
    indices = sorted(random.Random(SEED).sample(range(len(rows)), N_SAMPLE))
    abstract_ids = {rows[i][COL_ABSTRACT] for i in indices if COL_ABSTRACT in rows[i]}
    strings = resolve(book, label_ids | abstract_ids)

    classes = collections.Counter(
        (strings[r[COL_DOMAIN]], strings[r[COL_AREA]]) for r in rows
    )
    counts = sorted(classes.values())
    print(f"classes (Domain, area) : {len(classes)} sur "
          f"{len({d for d, _ in classes})} domaines")
    print(f"effectifs          : min {counts[0]}, médiane {counts[len(counts)//2]}, "
          f"max {counts[-1]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="\n") as out:
        for i in indices:
            row = rows[i]
            domain, area = strings[row[COL_DOMAIN]], strings[row[COL_AREA]]
            record = {
                # id = index de la ligne dans la feuille, hors en-tête, conservé tel quel.
                "id": i,
                "text": strings[row[COL_ABSTRACT]],
                "gold_label": f"{domain}/{area}",
                "parent": domain,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    sampled = collections.Counter(
        (strings[rows[i][COL_DOMAIN]], strings[rows[i][COL_AREA]]) for i in indices
    )
    lengths = sorted(len(strings[rows[i][COL_ABSTRACT]]) for i in indices)
    print(f"écrit              : {OUT_PATH}")
    print(f"                     {N_SAMPLE} lignes, {len(sampled)} classes "
          f"représentées sur {len(classes)}")
    print(f"longueur des résumés : médiane {lengths[len(lengths)//2]} caractères, "
          f"max {lengths[-1]}")
    print(f"sha256 sortie      : "
          f"{hashlib.sha256(OUT_PATH.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
