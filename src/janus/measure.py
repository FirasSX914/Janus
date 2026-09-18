"""La passe de mesure : interroge les deux modeles, balaye, ecrit une politique.

Les garde-fous viennent tous de l'experience qui fonde ce paquet :

- **Ecriture au fil de l'eau**, flushee et fsyncee ligne par ligne. Une
  interruption ne coute que l'appel en cours ; notre propre run de 500 a ete
  interrompu a 332 lignes et a repris sans repayer un seul appel.
- **Reprise par identifiant**, refusee si une ligne existante porte une autre
  empreinte d'enonce : deux versions d'enonce ne cohabitent jamais dans un
  fichier.
- **Les JSONL bruts sont ecrits automatiquement** a cote de la politique. Une
  politique doit etre auditable sans que l'utilisateur ait a gerer un chemin de
  plus.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import metrics
from .policy import ModelRef, Policy, build
from .providers.base import Provider, prompt_hash
from .sweep import Row, choose, oracle_accuracy, sweep
from .types import Answer, CalibrationReport, Measurement, OperatingPoint, Question


class BudgetExceeded(RuntimeError):
    """L'extrapolation du cout depasse le plafond demande : on s'arrete."""


def _rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _done_ids(path: Path, expected_hash: str) -> set:
    if not path.exists():
        return set()
    done = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record["prompt_hash"] != expected_hash:
            raise RuntimeError(
                f"refusing to resume: {path} line {number} carries prompt_hash\n"
                f"  {record['prompt_hash']}\n"
                f"expected\n  {expected_hash}\n"
                "The statement changed since that run. Start a fresh file rather "
                "than mixing two versions of a prompt.")
        done.add(record["id"])
    return done


def run_provider(provider: Provider, examples: Sequence[Mapping], question: Question,
                 out_path: Path, *, budget: float | None = None,
                 progress: Callable[[str], None] = print) -> list[dict]:
    """Interroge un fournisseur sur les exemples, en reprenant ce qui existe."""
    expected = prompt_hash(question)
    done = _done_ids(out_path, expected)
    todo = [e for e in examples if e["id"] not in done]
    progress(f"  {provider.name}/{provider.model}: {len(done)} done, {len(todo)} to go")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    with out_path.open("a", encoding="utf-8", newline="\n") as handle:
        for index, example in enumerate(todo, 1):
            when = datetime.now(timezone.utc)
            answer = provider.ask(example["text"], question)
            cost = provider.cost_usd(answer, when)
            record = {
                "id": example["id"],
                "text": example["text"],
                "gold_label": example["gold_label"],
                "model_id": answer.model_id,
                "prediction": answer.label,
                "confidence": answer.confidence,
                "probabilities": dict(answer.distribution) if answer.distribution else None,
                "input_tokens": answer.input_tokens,
                "output_tokens": answer.output_tokens,
                "latency_ms": answer.latency_ms,
                "cost_usd": cost,
                "prompt_hash": expected,
                "run_date": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
                **dict(answer.extra),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

            if cost is not None:
                spent += cost
            if budget is not None and index >= 10 and cost is not None:
                projected = spent / index * len(todo)
                if projected > budget:
                    raise BudgetExceeded(
                        f"projected cost {projected:.4f} exceeds the budget "
                        f"{budget:.4f} after {index} calls. Stopped; "
                        f"{spent:.4f} already spent, and the run resumes by id.")
            if index % 25 == 0 or index == len(todo):
                progress(f"    {index}/{len(todo)}  {spent:.4f} USD")
    return _rows_of(out_path)


def calibration_of(rows: Sequence[Mapping]) -> CalibrationReport:
    confidences = [r["confidence"] for r in rows if r["confidence"] is not None]
    correct = [r["prediction"] == r["gold_label"] for r in rows if r["confidence"] is not None]
    if not confidences:
        raise ValueError("the primary exposed no confidence; nothing to calibrate")
    n = len(confidences)
    hits = sum(correct)
    per_row = metrics.brier_per_row((r.get("probabilities") for r in rows),
                                    [r["gold_label"] for r in rows])
    usable = per_row[~(per_row != per_row)]  # retire les NaN
    return CalibrationReport(
        accuracy=hits / n,
        accuracy_ci=metrics.wilson(hits, n),
        mean_confidence=sum(confidences) / n,
        ece_by_level=metrics.ece_by_level(confidences, correct),
        ece_by_level_ci=metrics.bootstrap_ece_ci(confidences, correct),
        ece_equal_width=metrics.ece_equal_width(confidences, correct),
        brier=float(usable.mean()) if len(usable) else float("nan"),
        brier_ci=metrics.bootstrap_ci(usable) if len(usable) else (float("nan"),) * 2,
        levels=metrics.levels_of(confidences, correct),
    )


def measure(*, examples: Sequence[Mapping], question: Question,
            primary: Provider, fallback: Provider,
            artifacts: Path, target_accuracy: float | None = None,
            max_cost: float | None = None, budget: float | None = None,
            sample: int | None = None, seed: int | None = None,
            dataset_fingerprint: Mapping | None = None,
            caveats: Sequence[str] = (),
            progress: Callable[[str], None] = print) -> Measurement:
    """Mesure une politique de routage sur des donnees etiquetees."""
    if (sample is None) != (seed is None):
        raise ValueError("sample and seed go together: a draw without a "
                         "documented seed is not reproducible")
    if sample is not None:
        # Le tirage porte sur tout le jeu AVANT de retirer ce qui est deja fait :
        # l'echantillon ne depend que de la graine, pas de l'avancement.
        examples = sorted(random.Random(seed).sample(list(examples), sample),
                          key=lambda e: e["id"])
        progress(f"  smoke test: {sample} rows, seed {seed}")

    artifacts.mkdir(parents=True, exist_ok=True)
    primary_rows = run_provider(primary, examples, question,
                                artifacts / "primary.jsonl", budget=budget,
                                progress=progress)
    fallback_rows = run_provider(fallback, examples, question,
                                 artifacts / "fallback.jsonl", budget=budget,
                                 progress=progress)

    by_id = {r["id"]: r for r in fallback_rows}
    rows = [
        Row(confidence=p["confidence"],
            primary_ok=p["prediction"] == p["gold_label"],
            fallback_ok=by_id[p["id"]]["prediction"] == by_id[p["id"]]["gold_label"],
            primary_cost=p["cost_usd"],
            fallback_cost=by_id[p["id"]]["cost_usd"])
        for p in primary_rows if p["id"] in by_id
    ]
    if not rows:
        raise ValueError("the two runs share no example")

    points = sweep(rows)
    point, verdict, reason = choose(points, target_accuracy=target_accuracy,
                                    max_cost=max_cost)
    report = calibration_of(primary_rows)
    oracle = oracle_accuracy(rows)
    singles = {p.rule: p for p in points if p.rule != "primary_if_confidence_ge"}

    policy = build(
        question=question,
        primary=ModelRef(primary.name, primary.model, primary_rows[0]["model_id"]),
        fallback=ModelRef(fallback.name, fallback.model, fallback_rows[0]["model_id"]),
        point=point, verdict=verdict, reason=reason,
        levels=report.levels, oracle=oracle,
        unreachable=round((1 - oracle) * len(rows)),
        measured_on={"rows": len(rows), "sampling": {"sample": sample, "seed": seed},
                     **(dict(dataset_fingerprint) if dataset_fingerprint else {})},
        baselines={"primary_only": singles["always_primary"].accuracy,
                   "fallback_only": singles["always_fallback"].accuracy},
        caveats=caveats,
    )
    return Measurement(policy=policy, levels=list(report.levels),
                       calibration=report, sweep=points, verdict=verdict)
