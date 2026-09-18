"""Accord entre un journal de decisions et un modele de reference.

Porte de `experiments/gate/analyze_gate.py`, sans changement de methode.

CE QUI EST MESURE EST UN ACCORD, JAMAIS UNE JUSTESSE.
Un journal n'a pas d'etiquette d'or : le modele de reference n'est pas un
oracle, c'est un second avis. `guard()` refuse un rapport qui contiendrait
`accuracy`, `correct`, `ground truth` ou `error rate` -- la garantie est
executable, pas declarative.

LA STRATIFICATION EST OBLIGATOIRE.
L'experience `gate` a etabli pourquoi : sur 400 decisions reelles, les deux
paliers de confiance les plus hauts ne contenaient QUE la classe majoritaire.
Un accord eleve y refletait le desequilibre des classes, pas la confiance. A
classe predite constante, l'accord montait encore avec la confiance -- mais
c'est la stratification qui l'a montre, et sans elle le chiffre global
(86,5 %) ne battait sa propre ligne de base (86,0 %) que de 0,5 point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .metrics import wilson

#: Paliers DISJOINTS. Des paliers emboites partagent leurs lignes et rendent
#: quatre intervalles de confiance qui ne sont pas independants.
TIERS: tuple[tuple[str, float, float], ...] = (
    ("[0.95, 1.00]", 0.95, 1.01),
    ("[0.90, 0.95)", 0.90, 0.95),
    ("[0.80, 0.90)", 0.80, 0.90),
    ("[0.00, 0.80)", 0.00, 0.80),
)

#: Sous cet effectif, un palier est rapporte mais n'est pas interprete.
MIN_TIER = 10

#: Mots interdits, en correspondance MOT ENTIER. La formule imposee est
#: "not correctness" : une correspondance par sous-chaine bannirait la phrase
#: meme que le garde-fou existe pour proteger.
BANNED = (r"\baccurac(?:y|ies)\b", r"\bcorrect(?:ly)?\b",
          r"\bground[ -]truth\b", r"\berror rates?\b")

FORMULA = "agreement with the selected reference model, not correctness"


class ForbiddenWording(AssertionError):
    """Le rapport laisserait croire a une verite terrain."""


def guard(text: str) -> str:
    """Rend le texte, ou echoue s'il parle de justesse."""
    found = [pattern for pattern in BANNED if re.search(pattern, text, re.IGNORECASE)]
    if found:
        raise ForbiddenWording(
            f"report rejected, forbidden wording {found}. What a log measures is "
            "an agreement, not a correctness: there is no ground truth in it.")
    return text


@dataclass(frozen=True)
class Verdict:
    """Une decision du journal confrontee a la reference."""

    id: str
    confidence: float
    decision: str
    reference: str
    agree: bool
    reference_cost: float | None = None
    reference_latency_ms: float | None = None


@dataclass(frozen=True)
class TierRow:
    label: str
    n: int
    agreed: int
    interval: tuple[float, float]

    @property
    def rate(self) -> float:
        return self.agreed / self.n if self.n else float("nan")

    @property
    def interpreted(self) -> bool:
        return self.n >= MIN_TIER


@dataclass(frozen=True)
class OperatingPoint:
    """Un seuil : ce qu'on garde, ce qu'on escalade, ce que ca coute."""

    threshold: float | None
    coverage: float
    escalation_rate: float
    agreement_kept: float
    n_kept: int
    projected_cost: float | None


@dataclass(frozen=True)
class AgreementReport:
    n: int
    decisions: dict[str, int]
    reference_decisions: dict[str, int]
    majority_baseline: float
    overall: float
    overall_interval: tuple[float, float]
    tiers: Sequence[TierRow]
    #: Obligatoire : {classe predite -> paliers}. Jamais vide.
    stratified: dict[str, Sequence[TierRow]]
    points: Sequence[OperatingPoint]
    divergences: Sequence[Verdict]
    reference_cost_total: float | None
    caveats: Sequence[str] = field(default_factory=tuple)


def _tiers(verdicts: Sequence[Verdict]) -> list[TierRow]:
    rows = []
    for label, low, high in TIERS:
        inside = [v for v in verdicts if low <= v.confidence < high]
        agreed = sum(1 for v in inside if v.agree)
        rows.append(TierRow(label, len(inside), agreed,
                            wilson(agreed, len(inside)) if inside
                            else (float("nan"), float("nan"))))
    return rows


def _points(verdicts: Sequence[Verdict], mean_cost: float | None) -> list[OperatingPoint]:
    """Un point par niveau de confiance observe, plus les deux extremes.

    Le cout projete est celui de la PRODUCTION, pas de la mesure : en service,
    la reference n'est appelee que sur ce qui est escalade. La mesure, elle, l'a
    appelee partout, et c'est ce qu'elle coute une fois.
    """
    n = len(verdicts)
    levels = sorted({v.confidence for v in verdicts}, reverse=True)
    points: list[OperatingPoint] = []
    for threshold in [None] + levels:
        if threshold is None:            # tout escalade
            kept: list[Verdict] = []
        else:
            kept = [v for v in verdicts if v.confidence >= threshold]
        escalated = n - len(kept)
        points.append(OperatingPoint(
            threshold=threshold,
            coverage=len(kept) / n,
            escalation_rate=escalated / n,
            agreement_kept=(sum(1 for v in kept if v.agree) / len(kept)
                            if kept else float("nan")),
            n_kept=len(kept),
            projected_cost=None if mean_cost is None else escalated * mean_cost,
        ))
    return points


def analyse(verdicts: Sequence[Verdict]) -> AgreementReport:
    """Le rapport complet. La stratification n'est pas une option."""
    if not verdicts:
        raise ValueError("no decision to compare")
    n = len(verdicts)

    decisions: dict[str, int] = {}
    reference_decisions: dict[str, int] = {}
    for v in verdicts:
        decisions[v.decision] = decisions.get(v.decision, 0) + 1
        reference_decisions[v.reference] = reference_decisions.get(v.reference, 0) + 1

    agreed = sum(1 for v in verdicts if v.agree)
    costs = [v.reference_cost for v in verdicts if v.reference_cost is not None]
    total = sum(costs) if len(costs) == n else None
    mean_cost = (total / n) if total is not None else None

    caveats: list[str] = []
    if total is None:
        caveats.append("some reference calls have no known price; cost is left out "
                       "rather than counted as zero")

    # Obligatoire, pas conditionnel : c'est la seule vue qui separe la confiance
    # du desequilibre des classes.
    stratified = {label: _tiers([v for v in verdicts if v.decision == label])
                  for label in sorted(decisions)}
    for label, rows in stratified.items():
        if sum(1 for r in rows if r.interpreted) < 2:
            caveats.append(
                f"stratum {label!r} has fewer than two tiers above n={MIN_TIER}: "
                "its tiers are degenerate and are reported, not interpreted")

    return AgreementReport(
        n=n,
        decisions=decisions,
        reference_decisions=reference_decisions,
        majority_baseline=max(reference_decisions.values()) / n,
        overall=agreed / n,
        overall_interval=wilson(agreed, n),
        tiers=_tiers(verdicts),
        stratified=stratified,
        points=_points(verdicts, mean_cost),
        divergences=[v for v in verdicts if v.confidence >= 0.95 and not v.agree],
        reference_cost_total=total,
        caveats=tuple(caveats),
    )
