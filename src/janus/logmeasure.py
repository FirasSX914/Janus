"""Faire tourner le modele de reference sur les entrees d'un journal.

Porte de `experiments/gate/run_gate.py` : meme reprise par id, meme refus de
melanger deux enonces, meme plafond de budget. La difference tient en une ligne
-- il n'y a pas de `gold_label` a comparer, donc ce qui sort est un accord.

PARITE D'ENTREE
La reference recoit la chaine du journal telle quelle. Janus ne la reformule
pas, ne l'enrichit pas et ne la tronque pas : ce que le modele du journal a vu
est ce que la reference voit. Sans cela, l'accord mesurerait deux questions
differentes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from .agreement import Verdict
from .logs import LogRow
from .measure import run_provider
from .providers.base import Provider
from .types import Question

#: Caracteres par token. Conservateur pour du code et du JSON, ou le tokenizer
#: rend moins de caracteres par token que sur de la prose.
CHARS_PER_TOKEN = 3.6


def estimate(rows: Sequence[LogRow], question: Question, *,
             usd_per_mtok_in: float, usd_per_mtok_out: float,
             output_tokens: int) -> tuple[int, float]:
    """(tokens d'entree, cout estime) pour interroger la reference sur tout.

    `output_tokens` n'a pas de valeur par defaut parce qu'il n'en a pas de
    raisonnable : sur DeepSeek V4-Pro, mesure sur 76 decisions reelles, la
    moyenne est de 638 tokens de raisonnement -- la supposer a 30 avait
    sous-evalue un run de moitie et rendu son plafond inoperant.
    """
    overhead = len(question.instructions) + sum(
        len(name) + len(criterion) for name, criterion in question.criteria.items())
    chars = sum(len(row.input) for row in rows) + overhead * len(rows)
    tokens_in = int(chars / CHARS_PER_TOKEN)
    cost = (tokens_in / 1e6 * usd_per_mtok_in
            + len(rows) * output_tokens / 1e6 * usd_per_mtok_out)
    return tokens_in, cost


def ask_reference(rows: Sequence[LogRow], question: Question, reference: Provider,
                  artifacts: Path, *, budget: float | None = None,
                  progress: Callable[[str], None] = print) -> list[Verdict]:
    """Interroge la reference et confronte ses reponses au journal.

    Les lignes brutes sont conservees dans `artifacts` : une mesure d'accord
    doit pouvoir etre rejouee sans etre repayee, et verifiee ligne a ligne.
    """
    # `gold_label` vaut None et non "" : il n'y a pas d'etiquette, et une chaine
    # vide se confondrait avec une etiquette vide.
    examples = [{"id": row.id, "text": row.input, "gold_label": None} for row in rows]
    answered = run_provider(reference, examples, question,
                            artifacts / "reference.jsonl",
                            budget=budget, progress=progress)

    by_id = {record["id"]: record for record in answered}
    verdicts: list[Verdict] = []
    for row in rows:
        record = by_id.get(row.id)
        if record is None:      # budget atteint : on mesure ce qui a ete paye
            continue
        verdicts.append(Verdict(
            id=row.id,
            confidence=row.confidence,
            decision=row.decision,
            reference=record["prediction"],
            agree=row.decision == record["prediction"],
            reference_cost=record.get("cost_usd"),
            reference_latency_ms=record.get("latency_ms"),
        ))
    return verdicts
