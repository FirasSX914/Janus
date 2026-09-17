"""Jev sur les 500 exemples d'une tache -> results/raw/jev_<tache>_500.jsonl.

La tache est choisie par --task et vient de tasks.py : le runner ne connait
aucun dataset. Un appel par exemple, un Choice a exactement autant d'options que
la tache a de classes, criteres importes du module de labels de la tache.
Ecrit au fil de l'eau : rien n'est bufferise en memoire, chaque ligne
est flushee et fsyncee des qu'elle est produite, pour qu'une interruption ne
coute que l'appel en cours.

Reprise : les ids deja presents dans le fichier de sortie sont sautes. Le
prompt_hash des lignes existantes est verifie avant toute reprise, et la reprise
est refusee s'il differe -- deux versions de prompt ne doivent jamais cohabiter
dans un meme fichier.

Contrat des colonnes et definition du prompt_hash : docs/METHOD.md.
"""

import argparse
import json
import random
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from typesafe_sdk import Choice, TypeSafeClient

import tasks

ROOT = Path(__file__).resolve().parent.parent
MODEL = "jev-latest"
QUESTION_ID = "intent"
PROGRESS_EVERY = 25

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())

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


def already_done(path: Path, prompt_hash: str) -> set[int]:
    """Ids deja traites. Refuse la reprise si un prompt_hash differe."""
    if not path.exists():
        return set()
    done: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record["prompt_hash"] != prompt_hash:
                raise SystemExit(
                    f"Reprise refusee : {path} ligne {line_no} porte le prompt_hash\n"
                    f"  {record['prompt_hash']}\n"
                    f"alors que le prompt courant vaut\n"
                    f"  {prompt_hash}\n"
                    "Le protocole a change depuis ce run. Relancer dans un fichier "
                    "neuf plutot que melanger deux versions de prompt."
                )
            done.add(record["id"])
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="banking77")
    parser.add_argument("--sample", type=int, default=None,
                        help="rodage : tirer N exemples au hasard dans les 500 "
                             "(exige --seed). Jamais les premiers ids du fichier.")
    parser.add_argument("--seed", type=int, default=None,
                        help="graine du tirage de rodage, a documenter dans METHOD.md")
    parser.add_argument("--limit", type=int, default=None,
                        help="ne traiter que les N premiers exemples restants")
    args = parser.parse_args()
    if (args.sample is None) != (args.seed is None):
        parser.error("--sample et --seed vont ensemble : un rodage sans graine "
                     "documentee n'est pas reproductible.")

    task = tasks.load(args.task)
    prompt_hash = task.prompt_hash
    out_path = task.out_path("jev")
    examples = task.examples()
    # Le tirage porte sur les 500, AVANT de retirer les ids deja traites :
    # l'echantillon ne depend donc que de la graine, pas de l'avancement du run.
    if args.sample is not None:
        examples = sorted(random.Random(args.seed).sample(examples, args.sample),
                          key=lambda e: e["id"])
        print(f"rodage      : {args.sample} ids tires au hasard, graine {args.seed}")
        print(f"              {[e['id'] for e in examples]}")
    done = already_done(out_path, prompt_hash)
    todo = [example for example in examples if example["id"] not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"tache       : {task.name}, {len(task.criteria)} classes")
    print(f"prompt_hash : {prompt_hash}")
    print(f"dataset     : {len(examples)} exemples, {len(done)} deja traites")
    print(f"a traiter   : {len(todo)}")
    if not todo:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    question = {QUESTION_ID: Choice(instructions=task.instructions,
                                    criteria=task.criteria)}
    started_run = time.perf_counter()

    with out_path.open("a", encoding="utf-8", newline="\n") as out, TypeSafeClient(
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
                "prompt_hash": prompt_hash,
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

    print(f"ecrit : {out_path}")


if __name__ == "__main__":
    main()
