"""Metriques de calibration. Migrees de `experiments/analyze.py`, sans
changement de definition.

Deux precautions imposees par l'interface de sortie des modeles mesures, et
conservees ici parce qu'elles valent pour tout fournisseur a sortie discrete :

- **La confiance est arrondie au centieme avant tout regroupement.** Sur nos
  runs, 44 valeurs de probabilite sur 38 500 derivaient d'un ULP de double et
  auraient cree des niveaux fantomes.
- **`sum(distribution) == 1` n'est pas un invariant.** 33 lignes sur 500
  sommaient a 0,99. Rien ici ne suppose la somme, et rien ne renormalise :
  renormaliser fabriquerait une distribution que le modele n'a pas produite.
"""

from __future__ import annotations

import collections
import math
from typing import Iterable, Sequence

import numpy as np

from .types import LevelRow

Z95 = 1.959963984540054
BOOTSTRAP_ITERS = 10_000
BOOTSTRAP_SEED = 1729


def round_confidence(value: float) -> float:
    """Arrondi au centieme, avant tout regroupement."""
    return round(value, 2)


def wilson(correct: int, n: int) -> tuple[float, float]:
    """Intervalle de Wilson a 95 % pour une proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = correct / n
    denom = 1 + Z95**2 / n
    center = (p + Z95**2 / (2 * n)) / denom
    half = Z95 / denom * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2))
    return max(0.0, center - half), min(1.0, center + half)


def levels_of(confidences: Sequence[float], correct: Sequence[bool]) -> list[LevelRow]:
    """Une ligne par valeur de confiance observee, triee decroissante."""
    grouped: dict[float, list[int]] = collections.defaultdict(lambda: [0, 0])
    for value, ok in zip(confidences, correct):
        bucket = grouped[round_confidence(value)]
        bucket[0] += 1
        bucket[1] += bool(ok)
    return [LevelRow(level, *grouped[level]) for level in sorted(grouped, reverse=True)]


def ece_by_level(confidences: Sequence[float], correct: Sequence[bool]) -> float:
    """Ecart absolu confiance/accuracy, pondere par niveau OBSERVE.

    Pas de bandes de largeur fixe : la variable est discrete, donc regrouper par
    niveau observe est exact, la ou un decoupage arbitraire melangerait des
    niveaux que l'API distingue.
    """
    n = len(confidences)
    if n == 0:
        return float("nan")
    return sum(row.n / n * abs(row.accuracy - row.confidence)
               for row in levels_of(confidences, correct))


def ece_equal_width(confidences: Sequence[float], correct: Sequence[bool],
                    bins: int = 10) -> float:
    """Variante conventionnelle, pour comparaison a la litterature seulement."""
    n = len(confidences)
    if n == 0:
        return float("nan")
    rounded = [round_confidence(c) for c in confidences]
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        picked = [(c, ok) for c, ok in zip(rounded, correct)
                  if lo <= c < hi or (b == bins - 1 and c >= 1.0)]
        if not picked:
            continue
        accuracy = sum(bool(ok) for _, ok in picked) / len(picked)
        confidence = sum(c for c, _ in picked) / len(picked)
        total += len(picked) / n * abs(accuracy - confidence)
    return total


def brier_per_row(distributions: Iterable[dict[str, float] | None],
                  golds: Sequence[str]) -> np.ndarray:
    """Brier multiclasse, contribution de chaque ligne.

    Somme sur toutes les classes du carre de l'ecart a la cible one-hot : 0 quand
    toute la masse est sur le gold, jusqu'a 2 quand elle est entierement
    ailleurs. Calcule sur les distributions BRUTES, sans renormalisation.
    """
    out = []
    for distribution, gold in zip(distributions, golds):
        if distribution is None:
            out.append(float("nan"))
            continue
        out.append(sum((p - (1.0 if name == gold else 0.0)) ** 2
                       for name, p in distribution.items()))
    return np.asarray(out, dtype=float)


def _ece_terms(confidences: Sequence[float], correct: Sequence[bool]):
    rounded = [round_confidence(c) for c in confidences]
    levels = sorted(set(rounded))
    index = {level: i for i, level in enumerate(levels)}
    return (np.array([index[c] for c in rounded], dtype=int),
            np.array([bool(ok) for ok in correct], dtype=float),
            np.array(levels, dtype=float))


def _ece_from_terms(idx: np.ndarray, correct: np.ndarray, levels: np.ndarray) -> float:
    counts = np.bincount(idx, minlength=len(levels)).astype(float)
    sums = np.bincount(idx, weights=correct, minlength=len(levels))
    seen = counts > 0
    accuracy = np.divide(sums, counts, out=np.zeros_like(sums), where=seen)
    return float(np.sum(counts[seen] / len(idx) * np.abs(accuracy[seen] - levels[seen])))


def bootstrap_ci(values: np.ndarray, *, iters: int = BOOTSTRAP_ITERS,
                 seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """IC en percentiles sur la moyenne d'une quantite decomposable par ligne."""
    rng = np.random.default_rng(seed)
    n = len(values)
    draws = np.array([values[rng.integers(0, n, n)].mean() for _ in range(iters)])
    low, high = np.percentile(draws, [2.5, 97.5])
    return float(low), float(high)


def bootstrap_ece_ci(confidences: Sequence[float], correct: Sequence[bool], *,
                     iters: int = BOOTSTRAP_ITERS,
                     seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """IC de l'ECE : non decomposable par ligne, donc recalcule a chaque tirage."""
    idx, ok, levels = _ece_terms(confidences, correct)
    rng = np.random.default_rng(seed)
    n = len(idx)
    draws = np.empty(iters)
    for i in range(iters):
        pick = rng.integers(0, n, n)
        draws[i] = _ece_from_terms(idx[pick], ok[pick], levels)
    low, high = np.percentile(draws, [2.5, 97.5])
    return float(low), float(high)
