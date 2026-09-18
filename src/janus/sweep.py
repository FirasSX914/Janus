"""Balayage des seuils et choix du point de fonctionnement.

Migre de `experiments/cascade.py`, sans changement de methode.

Trois regles que la mesure a etablies et qui gouvernent ce module :

- **Le cout d'un routage inclut TOUJOURS le primary sur 100 % des requetes.**
  Il faut l'interroger pour connaitre sa confiance avant de pouvoir router
  dessus. Seule la regle `always_fallback` y echappe, puisqu'elle n'a pas besoin
  de la confiance.
- **Aucun seuil n'est choisi a la main, et aucun n'est cable par defaut.** Les
  seuils balayes sont exactement les niveaux observes. Sur nos deux datasets
  l'optimum est sorti a 0,67 et a 0,37 ; aucune de ces valeurs n'est un defaut.
- **« Ne pas router » est un resultat de premier ordre.** Quand aucun point de
  routage ne bat le meilleur des deux modeles seuls, le verdict est
  `do_not_route` et la politique designe ce modele. Sur Web of Science, router
  egalait le primary seul pour 46 % plus cher.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from .metrics import round_confidence
from .types import OperatingPoint, Verdict

#: Pas de la grille de confiance, cf. policy.GRID.
GRID = 0.01


@dataclass(frozen=True)
class Row:
    """Une ligne de mesure : ce que les deux modeles ont repondu, et a quel prix."""

    confidence: float
    primary_ok: bool
    fallback_ok: bool
    primary_cost: float | None
    fallback_cost: float | None
    primary_latency_ms: float = 0.0
    fallback_latency_ms: float = 0.0


def _total(costs: Sequence[float | None]) -> float | None:
    """Somme, ou `None` des qu'un cout est inconnu : l'inconnu ne s'additionne pas."""
    if any(cost is None for cost in costs):
        return None
    return float(sum(cost for cost in costs if cost is not None))


def simulate(rows: Sequence[Row], threshold: float) -> OperatingPoint:
    """Le primary tranche si sa confiance atteint le seuil, sinon on escalade."""
    kept = [r for r in rows if round_confidence(r.confidence) >= threshold]
    escalated = [r for r in rows if round_confidence(r.confidence) < threshold]
    correct = sum(r.primary_ok for r in kept) + sum(r.fallback_ok for r in escalated)
    cost = _total([r.primary_cost for r in rows] + [r.fallback_cost for r in escalated])
    # Une escalade paie les deux latences : le primary est interroge d'abord.
    latencies = ([r.primary_latency_ms for r in kept]
                 + [r.primary_latency_ms + r.fallback_latency_ms for r in escalated])
    return OperatingPoint(
        threshold=threshold,
        rule="primary_if_confidence_ge",
        coverage=len(kept) / len(rows),
        escalation_rate=len(escalated) / len(rows),
        n_escalated=len(escalated),
        accuracy=correct / len(rows),
        cost_total=cost if cost is not None else float("nan"),
        latency_p50_ms=statistics.median(latencies) if latencies else 0.0,
    )


def single_model(rows: Sequence[Row], which: str) -> OperatingPoint:
    """Un seul modele sur tout le trafic, sans interroger l'autre."""
    if which == "primary":
        correct = sum(r.primary_ok for r in rows)
        cost = _total([r.primary_cost for r in rows])
        latencies = [r.primary_latency_ms for r in rows]
        coverage, escalation = 1.0, 0.0
    else:
        correct = sum(r.fallback_ok for r in rows)
        cost = _total([r.fallback_cost for r in rows])
        # `always_fallback` n'interroge pas le primary : sa latence non plus.
        latencies = [r.fallback_latency_ms for r in rows]
        coverage, escalation = 0.0, 1.0
    return OperatingPoint(
        threshold=None,
        rule="always_primary" if which == "primary" else "always_fallback",
        coverage=coverage,
        escalation_rate=escalation,
        n_escalated=len(rows) if which == "fallback" else 0,
        accuracy=correct / len(rows),
        cost_total=cost if cost is not None else float("nan"),
        latency_p50_ms=statistics.median(latencies) if latencies else 0.0,
    )


def sweep(rows: Sequence[Row]) -> list[OperatingPoint]:
    """Un point par niveau de confiance observe, plus les deux modeles seuls.

    Un seuil au-dessus du maximum observe est inclus : il escalade tout en
    payant quand meme le primary, et c'est precisement ce qui rend visible que
    `always_fallback` fait mieux pour moins cher. Le garder dans la table evite
    qu'un lecteur croie que router tout equivaut a n'utiliser que le fallback.
    """
    levels = sorted({round_confidence(r.confidence) for r in rows}, reverse=True)
    above_max = round(levels[0] + GRID, 2) if levels else 1.01
    points = [simulate(rows, above_max)] + [simulate(rows, level) for level in levels]
    return [single_model(rows, "primary"), single_model(rows, "fallback"), *points]


def oracle_accuracy(rows: Sequence[Row]) -> float:
    """Plafond de CETTE paire de modeles : au moins un des deux a la reponse.

    Propre au couple mesure, pas une propriete de la tache. Un autre fallback
    deplacerait ce plafond.
    """
    return sum(r.primary_ok or r.fallback_ok for r in rows) / len(rows)


def choose(points: Sequence[OperatingPoint], *, target_accuracy: float | None = None,
           max_cost: float | None = None) -> tuple[OperatingPoint, Verdict, str]:
    """Selectionne un point de fonctionnement. Rend aussi le verdict et sa raison.

    Sans contrainte : le point le plus exact, a cout minimal en cas d'egalite.
    Avec `target_accuracy` : le moins cher qui l'atteint, sinon le plus exact,
    et la cible est rapportee comme inatteignable plutot que revisee.
    Avec `max_cost` : les points plus chers sont ecartes.
    """
    singles = [p for p in points if p.rule != "primary_if_confidence_ge"]
    routed = [p for p in points if p.rule == "primary_if_confidence_ge"]
    best_single = max(singles, key=lambda p: (p.accuracy, -p.cost_total))

    candidates = list(points)
    if max_cost is not None:
        affordable = [p for p in candidates if p.cost_total <= max_cost]
        if not affordable:
            cheapest = min(candidates, key=lambda p: p.cost_total)
            return cheapest, "do_not_route", (
                f"no operating point costs at most {max_cost:.4f}; "
                f"cheapest measured is {cheapest.cost_total:.4f}")
        candidates = affordable

    if target_accuracy is not None:
        meeting = [p for p in candidates if p.accuracy >= target_accuracy]
        if meeting:
            best = min(meeting, key=lambda p: (p.cost_total, -p.accuracy))
            verdict: Verdict = ("route" if best.rule == "primary_if_confidence_ge"
                                else "do_not_route")
            return best, verdict, f"cheapest point reaching {target_accuracy:.1%}"
        best = max(candidates, key=lambda p: (p.accuracy, -p.cost_total))
        verdict = "route" if best.rule == "primary_if_confidence_ge" else "do_not_route"
        return best, verdict, (
            f"target {target_accuracy:.1%} unattainable; best measured is "
            f"{best.accuracy:.1%}. The target is reported, not revised.")

    best_routed = max(routed, key=lambda p: (p.accuracy, -p.cost_total)) if routed else None
    if best_routed is None or best_routed.accuracy <= best_single.accuracy:
        margin = (best_routed.accuracy - best_single.accuracy) if best_routed else 0.0
        return best_single, "do_not_route", (
            "no routing threshold beats the better single model "
            f"({best_single.rule}, {best_single.accuracy:.1%}); "
            f"best routed point is {margin:+.1%} against it")
    return best_routed, "route", (
        f"beats the better single model by "
        f"{best_routed.accuracy - best_single.accuracy:+.1%}")
