"""Etape 3 : poser la question aux deux modeles, sur la MEME chaine.

Migration de experiments/run_jev.py et de son provider de reference : meme
structure de reprise, meme contrat de colonnes, meme discipline.

    python experiments/gate/run_gate.py --model jev
    python experiments/gate/run_gate.py --model reference

PARITE
Les deux modes lisent `canonical` dans gate_decisions.jsonl et l'envoient tel
quel. Aucun des deux ne reconstruit la chaine, ne l'enrichit ni ne la tronque :
c'est ce qui rend la parite de contexte verifiable plutot que promise.

BUDGET
Seul le modele de reference est sous plafond. Le run estime son cout AVANT
d'appeler, refuse de demarrer au-dessus du plafond, refuse les heures pleines,
et s'arrete net si le cout cumule depasse le plafond en cours de route. Le cout
de Jev est enregistre mais compte a part, comme dit le protocole.

Voir docs/METHOD_GATE.md.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "experiments"))

from question import CRITERIA, INSTRUCTIONS, LABELS, prompt_hash  # noqa: E402

RAW = ROOT / "results" / "raw"
DECISIONS = RAW / "gate_decisions.jsonl"
JEV_MODEL = "jev-latest"
JEV_USD_PER_MTOK = 0.042
QUESTION_ID = "gate"
PROGRESS_EVERY = 25
#: Releve de 0,50 a 0,60 le 2026-09-18 : le plafond initial avait ete fixe sur
#: un estimateur qui comptait 30 tokens de sortie par decision au lieu des ~250
#: reellement produits. Corriger un budget fonde sur une erreur de calcul n'est
#: pas le relever parce que le resultat n'y tient pas -- N est inchange.
#: Voir docs/METHOD_GATE.md.
DEFAULT_BUDGET = 0.60
#: Tokens de SORTIE par decision pour le modele de reference, mesures sur 76
#: decisions reelles : mediane 364, MOYENNE 638, p90 1282, max 5640. Le modele
#: raisonne avant de repondre et ces tokens sont factures au tarif de sortie,
#: ou ils pesent 82 % du cout -- le cache d'entree n'y change presque rien.
#:
#: Deux estimations precedentes ont ete fausses ici. 30 tokens d'abord, ce qui
#: sous-evaluait de moitie. Puis 250, moyenne d'un rodage de TROIS lignes prises
#: en tete de fichier : trop peu et non tirees au hasard pour attraper une queue
#: qui va jusqu'a 5640. C'est la moyenne qui compte pour un cout total, et elle
#: demande un echantillon qui voie la queue.
REFERENCE_OUTPUT_TOKENS = 638

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def descriptive_stats(probabilities: dict[str, float]) -> dict[str, float]:
    """Memes trois statistiques que run_jev.py, memes conventions."""
    ps = sorted(probabilities.values(), reverse=True)
    p1, p2 = ps[0], ps[1]
    # + 0.0 : sans lui une distribution saturee donne -0.0 au lieu de 0.0
    entropy = -sum(p * math.log(p) for p in ps if p > 0) + 0.0
    return {
        "margin_top2": p1 - p2,
        "entropy_norm": entropy / math.log(len(ps)),
        "ratio_top2": p1 / max(p2, 0.005),
    }


def already_done(path: Path, digest: str) -> set[str]:
    """Ids deja traites. Refuse la reprise si un prompt_hash differe."""
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record["prompt_hash"] != digest:
                raise SystemExit(
                    f"Reprise refusee : {path} ligne {line_no} porte le prompt_hash\n"
                    f"  {record['prompt_hash']}\nalors que le prompt courant vaut\n"
                    f"  {digest}\nRelancer dans un fichier neuf plutot que melanger "
                    "deux versions de prompt.")
            done.add(record["id"])
    return done


def load_decisions(digest: str) -> list[dict]:
    if not DECISIONS.exists():
        raise SystemExit(f"{DECISIONS} n'existe pas : lancer extract.py puis resolve.py")
    rows = [json.loads(line) for line
            in DECISIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    stale = {row["prompt_hash"] for row in rows} - {digest}
    if stale:
        raise SystemExit(
            f"{DECISIONS} porte un prompt_hash etranger : {sorted(stale)}\n"
            f"Le prompt courant vaut {digest}. Relancer resolve.py.")
    return rows


def run_jev(todo: list[dict], out_path: Path, digest: str) -> None:
    from typesafe_sdk import Choice, TypeSafeClient

    question = {QUESTION_ID: Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)}
    started_run = time.perf_counter()
    with out_path.open("a", encoding="utf-8", newline="\n") as out, \
         TypeSafeClient(timeout=60.0) as client:
        for n, row in enumerate(todo, 1):
            run_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
            started = time.perf_counter()
            response = client.system_one(state=row["canonical"], model=JEV_MODEL,
                                         questions=question)
            latency_ms = (time.perf_counter() - started) * 1000
            # choices[...] et jamais answers[...] : un NoulAnswer n'aurait pas
            # de champ confidence.
            answer = response.choices[QUESTION_ID]
            tokens = response.usage.input_tokens
            out.write(json.dumps({
                "id": row["id"],
                "source": row["source"],
                "tool_name": row["tool_name"],
                # response.model : la version resolue, pas l'alias envoye.
                "model_id": response.model,
                "prediction": answer.choice,
                "confidence": answer.confidence,
                "probabilities": answer.probabilities,
                **descriptive_stats(answer.probabilities),
                "input_tokens": tokens,
                "cost_usd": tokens / 1e6 * JEV_USD_PER_MTOK,
                "latency_ms": round(latency_ms, 1),
                "prompt_hash": digest,
                "run_date": run_date.replace("+00:00", "Z"),
            }, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
            if n % PROGRESS_EVERY == 0 or n == len(todo):
                elapsed = time.perf_counter() - started_run
                print(f"  {n}/{len(todo)} | {elapsed:.0f}s | "
                      f"{elapsed / n * 1000:.0f} ms/decision", flush=True)


def run_reference(todo: list[dict], out_path: Path, digest: str, budget: float) -> None:
    from dataclasses import dataclass

    import providers

    @dataclass(frozen=True)
    class GateTask:
        """Adaptateur : le provider de reference attend la forme d'une Task."""
        name: str = "gate"
        instructions: str = INSTRUCTIONS
        criteria: dict = None
        label_names: tuple = LABELS

    task = GateTask(criteria=CRITERIA)
    provider = providers.DeepSeekProvider(task)

    now = datetime.now(timezone.utc)
    if providers.DeepSeekProvider.is_peak(now):
        raise SystemExit(
            f"Heure pleine ({now:%H:%M} UTC) : le tarif y est double et le "
            "protocole interdit d'y lancer le run. Attendre une heure creuse.")

    spent = 0.0
    started_run = time.perf_counter()
    with out_path.open("a", encoding="utf-8", newline="\n") as out:
        for n, row in enumerate(todo, 1):
            run_date = datetime.now(timezone.utc)
            started = time.perf_counter()
            completion = provider.call(row["canonical"])
            latency_ms = (time.perf_counter() - started) * 1000
            cost = provider.cost_usd(completion, run_date)
            if isinstance(cost, float):
                spent += cost
            out.write(json.dumps({
                "id": row["id"],
                "source": row["source"],
                "tool_name": row["tool_name"],
                "model_id": completion.model_id,
                "prediction": completion.prediction,
                # Le modele de reference n'expose ni confiance ni distribution :
                # les colonnes existent et valent null, elles ne sont pas omises.
                "confidence": None,
                "probabilities": None,
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "cost_usd": cost,
                "latency_ms": round(latency_ms, 1),
                "prompt_hash": digest,
                "run_date": run_date.isoformat(timespec="seconds").replace("+00:00", "Z"),
                **completion.extra,
            }, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())

            if spent > budget:
                raise SystemExit(
                    f"\nArret : cout cumule ${spent:.4f} > plafond ${budget:.2f} "
                    f"apres {n} decisions. Les lignes ecrites sont conservees, la "
                    "reprise repartira d'ici.")
            if n % PROGRESS_EVERY == 0 or n == len(todo):
                elapsed = time.perf_counter() - started_run
                print(f"  {n}/{len(todo)} | {elapsed:.0f}s | ${spent:.4f} depenses",
                      flush=True)
    print(f"cout total de la reference : ${spent:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=("jev", "reference"), required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sample-file", type=Path, default=None,
                        help="liste d'ids figee definissant l'echantillon mesure. "
                             "A preferer a --target-n/--seed : un tirage porte "
                             "sur les lignes restantes, donc il depend de "
                             "l'avancement du run et ne se rejoue pas.")
    parser.add_argument("--target-n", type=int, default=None,
                        help="taille visee de l'echantillon mesure. Les lignes "
                             "deja ecrites en font partie ; le complement est "
                             "TIRE AU HASARD parmi les restantes (exige --seed).")
    parser.add_argument("--seed", type=int, default=None,
                        help="graine du tirage, a documenter dans METHOD_GATE.md")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                        help="plafond du modele de reference, en dollars")
    parser.add_argument("--estimate", action="store_true",
                        help="afficher le plan et le cout, n'appeler personne")
    args = parser.parse_args()

    digest = prompt_hash()
    rows = load_decisions(digest)
    out_path = RAW / f"gate_{args.model}.jsonl"
    done = already_done(out_path, digest)
    todo = [row for row in rows if row["id"] not in done]

    if args.sample_file is not None:
        if args.target_n is not None or args.seed is not None:
            parser.error("--sample-file definit deja l'echantillon : ne pas y "
                         "ajouter --target-n/--seed.")
        spec = json.loads(args.sample_file.read_text(encoding="utf-8"))
        if spec.get("prompt_hash") != digest:
            raise SystemExit(
                f"{args.sample_file} a ete fige sous le prompt_hash\n"
                f"  {spec.get('prompt_hash')}\nalors que le prompt courant vaut\n"
                f"  {digest}\nL'echantillon ne decrit pas cette mesure.")
        wanted = set(spec["ids"])
        unknown = wanted - {row["id"] for row in rows}
        if unknown:
            raise SystemExit(f"{len(unknown)} ids de l'echantillon sont absents "
                             f"de {DECISIONS.name}.")
        todo = [row for row in todo if row["id"] in wanted]
        print(f"echantillon : {len(wanted)} ids figes dans "
              f"{args.sample_file.name}, {len(wanted) - len(todo)} deja faits")

    if (args.target_n is None) != (args.seed is None):
        parser.error("--target-n et --seed vont ensemble : un tirage sans graine "
                     "documentee n'est pas reproductible.")
    if args.target_n is not None:
        need = args.target_n - len(done)
        if need < 0:
            parser.error(f"{len(done)} lignes deja ecrites depassent la cible "
                         f"{args.target_n} : rien a tirer.")
        if need > len(todo):
            parser.error(f"cible {args.target_n} hors d'atteinte : {len(done)} "
                         f"faites + {len(todo)} disponibles.")
        # Tirage parmi les RESTANTES, jamais les premieres du fichier : prendre
        # la tete ordonnerait l'echantillon par la chronologie des sessions.
        todo = sorted(random.Random(args.seed).sample(todo, need),
                      key=lambda row: row["id"])
        print(f"tirage      : {need} parmi {len([r for r in rows if r['id'] not in done])} "
              f"restantes, graine {args.seed}")
    if args.limit is not None:
        todo = todo[: args.limit]

    chars = sum(len(row["canonical"]) for row in todo)
    tokens = chars / 3.6 + len(todo) * 55  # + l'enonce et les deux classes
    print(f"modele      : {args.model}")
    print(f"prompt_hash : {digest}")
    print(f"decisions   : {len(rows)} au total, {len(done)} deja traitees")
    print(f"a traiter   : {len(todo)}  (~{tokens:,.0f} tokens d'entree)")

    if args.model == "reference":
        estimate = (tokens / 1e6 * 0.66
                    + len(todo) * REFERENCE_OUTPUT_TOKENS / 1e6 * 1.98)
        print(f"estimation  : ${estimate:.4f} (sans cache, heures creuses) "
              f"| plafond ${args.budget:.2f}")
        if estimate > args.budget:
            raise SystemExit(
                f"Refus de demarrer : l'estimation ${estimate:.4f} depasse le "
                f"plafond ${args.budget:.2f}.")
    else:
        print(f"estimation  : ${tokens / 1e6 * JEV_USD_PER_MTOK:.4f} "
              "(compte a part du budget de la reference)")

    if args.estimate or not todo:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.model == "jev":
        run_jev(todo, out_path, digest)
    else:
        run_reference(todo, out_path, digest, args.budget)
    print(f"ecrit : {out_path}")


if __name__ == "__main__":
    main()
