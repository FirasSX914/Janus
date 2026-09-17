"""Jev sur les 500 exemples de Banking77 -> results/raw/jev_banking77_500.jsonl.

Un appel par exemple, un Choice a exactement 77 options, criteres importes de
labels.py. Ecrit au fil de l'eau : rien n'est bufferise en memoire, chaque ligne
est flushee et fsyncee des qu'elle est produite, pour qu'une interruption ne
coute que l'appel en cours.

Reprise : les ids deja presents dans le fichier de sortie sont sautes. Le
prompt_hash des lignes existantes est verifie avant toute reprise, et la reprise
est refusee s'il differe -- deux versions de prompt ne doivent jamais cohabiter
dans un meme fichier.

Contrat des colonnes et definition du prompt_hash : docs/METHOD.md.
"""

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from typesafe_sdk import Choice, TypeSafeClient

from labels import CRITERIA, INSTRUCTIONS

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "banking77_500.jsonl"
OUT_PATH = ROOT / "results" / "raw" / "jev_banking77_500.jsonl"
MODEL = "jev-latest"
QUESTION_ID = "intent"
PROGRESS_EVERY = 25

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())

# Partie CONSTANTE du prompt : instructions + les 77 criteres, dans l'ordre
# exact ou ils sont envoyes. Le state change a chaque exemple, donc il n'entre
# pas dans le hash -- sinon le hash serait unique par ligne et ne detecterait
# plus un changement de protocole.
PROMPT_CONSTANT = {"instructions": INSTRUCTIONS, "criteria": CRITERIA}
PROMPT_HASH = hashlib.sha256(
    json.dumps(PROMPT_CONSTANT, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()


def descriptive_stats(probabilities: dict[str, float]) -> dict[str, float]:
    ps = sorted(probabilities.values(), reverse=True)
    p1, p2 = ps[0], ps[1]
    n = len(ps)
    # + 0.0 : sans lui une distribution saturee donne -0.0 au lieu de 0.0
    entropy = -sum(p * math.log(p) for p in ps if p > 0) + 0.0
    return {
        "margin_top2": p1 - p2,
        "entropy_norm": entropy / math.log(n),
        "ratio_top2": p1 / max(p2, 0.005),
    }


def already_done(path: Path) -> set[int]:
    """Ids deja traites. Refuse la reprise si un prompt_hash differe."""
    if not path.exists():
        return set()
    done: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record["prompt_hash"] != PROMPT_HASH:
                raise SystemExit(
                    f"Reprise refusee : {path} ligne {line_no} porte le prompt_hash\n"
                    f"  {record['prompt_hash']}\n"
                    f"alors que le prompt courant vaut\n"
                    f"  {PROMPT_HASH}\n"
                    "Le protocole a change depuis ce run. Relancer dans un fichier "
                    "neuf plutot que melanger deux versions de prompt."
                )
            done.add(record["id"])
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ne traiter que les N premiers exemples restants (rodage)",
    )
    args = parser.parse_args()

    examples = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    done = already_done(OUT_PATH)
    todo = [example for example in examples if example["id"] not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"prompt_hash : {PROMPT_HASH}")
    print(f"dataset     : {len(examples)} exemples, {len(done)} deja traites")
    print(f"a traiter   : {len(todo)}")
    if not todo:
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    question = {QUESTION_ID: Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)}
    started_run = time.perf_counter()

    with OUT_PATH.open("a", encoding="utf-8", newline="\n") as out, TypeSafeClient(
        timeout=30.0
    ) as client:
        for n, example in enumerate(todo, 1):
            run_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
            started = time.perf_counter()
            response = client.system_one(
                state=example["text"], model=MODEL, questions=question
            )
            latency_ms = (time.perf_counter() - started) * 1000

            # choices[...] et jamais answers[...] : answers melange les types et
            # un NoulAnswer n'a pas de champ confidence.
            answer = response.choices[QUESTION_ID]
            record = {
                "id": example["id"],
                "text": example["text"],
                "gold_label": example["gold_label"],
                # response.model : la version resolue, pas l'alias envoye.
                "model_id": response.model,
                "prediction": answer.choice,
                "confidence": answer.confidence,
                "probabilities": answer.probabilities,
                **descriptive_stats(answer.probabilities),
                "input_tokens": response.usage.input_tokens,
                "latency_ms": round(latency_ms, 1),
                "prompt_hash": PROMPT_HASH,
                "run_date": run_date.replace("+00:00", "Z"),
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())

            if n % PROGRESS_EVERY == 0 or n == len(todo):
                elapsed = time.perf_counter() - started_run
                print(
                    f"  {n}/{len(todo)} lignes | {elapsed:.0f}s ecoulees "
                    f"| {elapsed / n * 1000:.0f} ms/exemple"
                )

    print(f"ecrit : {OUT_PATH}")


if __name__ == "__main__":
    main()
