"""Baseline frontier sur les 500 exemples de Banking77 -> results/raw/.

Le backend est choisi par --provider et vient de providers.py, qui expose une
interface unique : call(state) -> (prediction, input_tokens, output_tokens,
model_id). Le runner lui-meme ne connait aucun fournisseur ; ajouter Opus 5 en
v2 ne demandera pas de le rouvrir.

Meme dataset, meme mapping importe de labels.py, meme ordre et meme formulation
des 77 criteres que run_jev.py. Le prompt_hash est calcule par la MEME formule
que le runner Jev : les deux fichiers doivent porter un prompt_hash identique,
et cette egalite est la preuve verifiable que les modeles ont recu le meme
enonce.

Le frontier n'expose aucune distribution comparable : les colonnes confidence,
probabilities, margin_top2, entropy_norm et ratio_top2 restent nulles. Elles ne
sont pas fabriquees. Voir docs/METHOD.md.

Ecriture au fil de l'eau, reprise par id, refus si le prompt_hash differe.
"""

import argparse
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from labels import CRITERIA, INSTRUCTIONS
from providers import PROVIDERS

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "banking77_500.jsonl"
PROGRESS_EVERY = 25

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())

# Partie constante du prompt, identique a celle de run_jev.py et hachee par la
# meme formule. Le rendu textuel de providers.py en derive entierement.
PROMPT_CONSTANT = {"instructions": INSTRUCTIONS, "criteria": CRITERIA}
PROMPT_HASH = hashlib.sha256(
    json.dumps(PROMPT_CONSTANT, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()


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
                    f"alors que le prompt courant vaut\n  {PROMPT_HASH}\n"
                    "Le protocole a change depuis ce run. Relancer dans un fichier "
                    "neuf plutot que melanger deux versions de prompt."
                )
            done.add(record["id"])
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="gemini")
    parser.add_argument("--model", default=None, help="surcharge du modele par defaut du backend")
    parser.add_argument("--sample", type=int, default=None,
                        help="rodage : tirer N exemples au hasard dans les 500 "
                             "(exige --seed). Jamais les premiers ids du fichier, "
                             "qui sont groupes par classe.")
    parser.add_argument("--seed", type=int, default=None,
                        help="graine du tirage de rodage, a documenter dans METHOD.md")
    parser.add_argument("--limit", type=int, default=None,
                        help="ne traiter que les N premiers exemples restants")
    args = parser.parse_args()
    if (args.sample is None) != (args.seed is None):
        parser.error("--sample et --seed vont ensemble : un rodage sans graine "
                     "documentee n'est pas reproductible.")

    provider = PROVIDERS[args.provider](**({"model": args.model} if args.model else {}))
    out_path = ROOT / "results" / "raw" / f"{provider.name}_banking77_500.jsonl"

    examples = [
        json.loads(line)
        for line in DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Le tirage porte sur les 500, AVANT de retirer les ids deja traites :
    # l'echantillon ne depend donc que de la graine, pas de l'avancement du run.
    if args.sample is not None:
        examples = sorted(random.Random(args.seed).sample(examples, args.sample),
                          key=lambda e: e["id"])
        print(f"rodage      : {args.sample} ids tires au hasard, graine {args.seed}")
        print(f"              {[e['id'] for e in examples]}")

    done = already_done(out_path)
    todo = [example for example in examples if example["id"] not in done]
    if args.limit is not None:
        todo = todo[: args.limit]

    print(f"prompt_hash : {PROMPT_HASH}")
    print(f"              (doit etre identique a celui du run Jev)")
    print(f"backend     : {provider.name} / {provider.model}")
    print(f"sortie      : {out_path.name}")
    print(f"dataset     : {len(examples)} exemples, {len(done)} deja traites")
    print(f"a traiter   : {len(todo)}")
    if not todo:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    started_run = time.perf_counter()
    total_cost = 0.0
    unknown_cost = 0

    with out_path.open("a", encoding="utf-8", newline="\n") as out:
        for n, example in enumerate(todo, 1):
            # Heure de l'appel : elle fixe le regime tarifaire chez les
            # fournisseurs a tarif horaire, donc elle est prise AVANT l'appel
            # et reutilisee pour le calcul de cout.
            when = datetime.now(timezone.utc)
            started = time.perf_counter()
            completion = provider.call(example["text"])
            latency_ms = (time.perf_counter() - started) * 1000

            cost = provider.cost_usd(completion, when)
            if isinstance(cost, float):
                total_cost += cost
            else:
                unknown_cost += 1

            record = {
                "id": example["id"],
                "text": example["text"],
                "gold_label": example["gold_label"],
                "model_id": completion.model_id,
                "prediction": completion.prediction,
                # Le frontier n'expose pas de distribution comparable :
                # ces cinq colonnes restent nulles, elles ne sont pas fabriquees.
                "confidence": None,
                "probabilities": None,
                "margin_top2": None,
                "entropy_norm": None,
                "ratio_top2": None,
                "input_tokens": completion.input_tokens,
                "latency_ms": round(latency_ms, 1),
                "prompt_hash": PROMPT_HASH,
                "run_date": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
                # Colonnes propres au frontier, absentes du run Jev dont la
                # sortie n'est pas facturee. output_tokens inclut les tokens de
                # raisonnement, factures au tarif de sortie.
                "output_tokens": completion.output_tokens,
                "cost_usd": cost,
                # Regime tarifaire de l'heure reelle de l'appel : consigne pour
                # que le cout de la ligne soit recalculable depuis la ligne seule.
                "pricing_tier": ("peak" if getattr(provider, "is_peak", None)
                                 and provider.is_peak(when) else "off_peak"),
                **completion.extra,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())

            if n % PROGRESS_EVERY == 0 or n == len(todo):
                elapsed = time.perf_counter() - started_run
                print(f"  {n}/{len(todo)} lignes | {elapsed:.0f}s ecoulees "
                      f"| {elapsed / n * 1000:.0f} ms/exemple "
                      f"| {total_cost:.4f} $ cumules")

    print(f"ecrit : {out_path}")
    if unknown_cost:
        print(f"cout inconnu sur {unknown_cost} appels : tarif absent de PRICING "
              "pour le modele rendu.")


if __name__ == "__main__":
    main()
