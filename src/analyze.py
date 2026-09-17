"""Calibration et risk-coverage a partir d'un JSONL de results/raw/.

AUCUN appel API : ce script lit un fichier, rien d'autre.

Produit :
  1. la table des niveaux de confidence observes (intervalle de Wilson a 95 %)
  2. la meme table regroupee par paliers
  3. le risk-coverage, un point par niveau observe, sans interpolation
  4. le pouvoir discriminant des statistiques alternatives, hors atome 1.00
  5. deux graphes : calibration et risk-coverage, traces sur les paliers

Ce script ne choisit pas de seuil et n'interprete pas ses sorties.

Deux precautions imposees par l'interface de sortie de l'API (voir METHOD.md) :
  - `confidence` est arrondie au centieme avant tout regroupement : 44 valeurs
    sur 38 500 derivent d'un ULP et creeraient des niveaux fantomes.
  - `sum(probabilities) == 1` n'est PAS un invariant : 33 lignes sur 500 somment
    a 0,99. Rien ici ne suppose la somme.
"""

import argparse
import collections
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "results" / "raw" / "jev_banking77_500.jsonl"
DEFAULT_FIGDIR = ROOT / "results" / "figures"

Z95 = 1.959963984540054
SMALL_N = 10  # en deca, l'intervalle est trop large pour lire la ligne seule

# Paliers, bornes basses incluses, bornes hautes exclues.
TIERS: tuple[tuple[str, float, float], ...] = (
    ("1.00", 1.00, math.inf),
    ("[0.95, 1.00[", 0.95, 1.00),
    ("[0.90, 0.95[", 0.90, 0.95),
    ("[0.70, 0.90[", 0.70, 0.90),
    ("< 0.70", -math.inf, 0.70),
)


def wilson(correct: int, n: int) -> tuple[float, float]:
    """Intervalle de Wilson a 95 % pour une proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = correct / n
    denom = 1 + Z95**2 / n
    center = (p + Z95**2 / (2 * n)) / denom
    half = Z95 / denom * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2))
    return max(0.0, center - half), min(1.0, center + half)


def auroc(scores: np.ndarray, correct: np.ndarray) -> float:
    """AUROC de `scores` pour separer les reponses justes des fausses.

    Statistique de Mann-Whitney sur rangs moyens : les ex aequo comptent 1/2,
    ce qui est indispensable ici puisque les scores vivent sur une grille
    grossiere et produisent beaucoup d'egalites.
    """
    n_pos = int(correct.sum())
    n_neg = int((~correct).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ordered = scores[order]
    ranks = np.empty(len(ordered), dtype=float)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2 + 1
        i = j + 1
    unordered = np.empty(len(ordered), dtype=float)
    unordered[order] = ranks
    return (unordered[correct].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def load(path: Path) -> list[dict]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for record in records:
        # Arrondi au centieme AVANT tout regroupement.
        record["confidence_r"] = round(record["confidence"], 2)
        record["correct"] = record["prediction"] == record["gold_label"]
    return records


def table_by_level(records: list[dict]) -> list[tuple]:
    grouped: dict[float, list[int]] = collections.defaultdict(lambda: [0, 0])
    for record in records:
        bucket = grouped[record["confidence_r"]]
        bucket[0] += 1
        bucket[1] += record["correct"]
    rows = []
    for level in sorted(grouped, reverse=True):
        n, correct = grouped[level]
        low, high = wilson(correct, n)
        rows.append((level, n, correct, correct / n, low, high))
    return rows


def table_by_tier(records: list[dict]) -> list[tuple]:
    rows = []
    for name, lo, hi in TIERS:
        subset = [r for r in records if lo <= r["confidence_r"] < hi]
        n = len(subset)
        correct = sum(r["correct"] for r in subset)
        low, high = wilson(correct, n)
        accuracy = correct / n if n else float("nan")
        rows.append((name, n, correct, accuracy, low, high))
    return rows


def risk_coverage(records: list[dict], thresholds: list[float]) -> list[tuple]:
    total = len(records)
    rows = []
    for threshold in thresholds:
        subset = [r for r in records if r["confidence_r"] >= threshold]
        n = len(subset)
        correct = sum(r["correct"] for r in subset)
        coverage = n / total
        accuracy = correct / n if n else float("nan")
        low, high = wilson(correct, n)
        rows.append((threshold, n, coverage, correct, accuracy, low, high, 1 - accuracy if n else float("nan")))
    return rows


def print_level_table(rows: list[tuple]) -> None:
    print(f"{'Confidence':>10} | {'N':>4} | {'Correct':>7} | {'Accuracy':>8} | "
          f"{'CI_low':>7} | {'CI_high':>7} | !")
    print("-" * 66)
    for level, n, correct, accuracy, low, high in rows:
        flag = "!" if n < SMALL_N else ""
        print(f"{level:>10.2f} | {n:>4} | {correct:>7} | {accuracy*100:>7.1f}% | "
              f"{low*100:>6.1f}% | {high*100:>6.1f}% | {flag}")
    small = [r for r in rows if r[1] < SMALL_N]
    n_small = sum(r[1] for r in small)
    total = sum(r[1] for r in rows)
    print(f"\n  ! = N < {SMALL_N}. {len(small)} niveaux sur {len(rows)} sont dans ce cas,")
    print(f"      soit {n_small} observations sur {total} ({n_small/total*100:.1f} % de la masse).")
    widest = max(rows, key=lambda r: r[5] - r[4])
    print(f"      Intervalle le plus large : confidence {widest[0]:.2f}, N={widest[1]}, "
          f"[{widest[4]*100:.1f}%, {widest[5]*100:.1f}%], amplitude "
          f"{(widest[5]-widest[4])*100:.1f} points.")


def print_tier_table(rows: list[tuple]) -> None:
    print(f"{'Palier':>14} | {'N':>4} | {'Correct':>7} | {'Accuracy':>8} | "
          f"{'CI_low':>7} | {'CI_high':>7}")
    print("-" * 66)
    for name, n, correct, accuracy, low, high in rows:
        if n == 0:
            print(f"{name:>14} | {n:>4} | {correct:>7} | {'  n/a':>8} | {'n/a':>7} | {'n/a':>7}")
            continue
        print(f"{name:>14} | {n:>4} | {correct:>7} | {accuracy*100:>7.1f}% | "
              f"{low*100:>6.1f}% | {high*100:>6.1f}%")


def print_risk_coverage(rows: list[tuple]) -> None:
    print(f"{'Seuil':>7} | {'N':>4} | {'Coverage':>8} | {'Correct':>7} | "
          f"{'Sel.acc':>8} | {'CI_low':>7} | {'CI_high':>7} | {'Err':>7}")
    print("-" * 80)
    for threshold, n, coverage, correct, accuracy, low, high, err in rows:
        print(f"{threshold:>7.2f} | {n:>4} | {coverage*100:>7.1f}% | {correct:>7} | "
              f"{accuracy*100:>7.1f}% | {low*100:>6.1f}% | {high*100:>6.1f}% | {err*100:>6.1f}%")


def print_discrimination(records: list[dict]) -> None:
    zone = [r for r in records if r["confidence_r"] < 1.00]
    n = len(zone)
    correct = np.array([r["correct"] for r in zone], dtype=bool)
    print(f"Zone : confidence < 1.00, soit {n} observations sur {len(records)} "
          f"({n/len(records)*100:.1f} %).")
    print(f"       {int(correct.sum())} justes, {int((~correct).sum())} fausses.")
    print("L'atome 1.00 est exclu : les trois statistiques y sont constantes par")
    print("construction, l'AUROC y serait 0.5 par definition et non par mesure.\n")

    # Orientation documentee dans METHOD.md : entropy_norm varie en sens inverse.
    columns = [
        ("confidence", lambda r: r["confidence_r"], "^ = plus certain"),
        ("margin_top2", lambda r: r["margin_top2"], "^ = plus certain"),
        ("entropy_norm", lambda r: -r["entropy_norm"], "^ = MOINS certain, orientee en -x"),
        ("ratio_top2", lambda r: r["ratio_top2"], "^ = plus certain"),
    ]
    print(f"{'Statistique':>14} | {'AUROC':>6} | {'valeurs distinctes':>18} | orientation")
    print("-" * 78)
    for name, getter, orientation in columns:
        scores = np.array([getter(r) for r in zone], dtype=float)
        print(f"{name:>14} | {auroc(scores, correct):>6.3f} | "
              f"{len(np.unique(scores)):>18} | {orientation}")
    print("\nAUROC = probabilite qu'une reponse juste tiree au hasard recoive un score")
    print("strictement superieur a une reponse fausse, les ex aequo comptant 1/2.")


def plot_calibration(tier_rows: list[tuple], records: list[dict], path: Path) -> None:
    usable = [(name, n, acc, low, high) for name, n, _, acc, low, high in tier_rows if n]
    xs, ys, los, his, names, ns = [], [], [], [], [], []
    for name, lo, hi in TIERS:
        subset = [r for r in records if lo <= r["confidence_r"] < hi]
        if not subset:
            continue
        row = next(r for r in tier_rows if r[0] == name)
        xs.append(float(np.mean([r["confidence_r"] for r in subset])))
        ys.append(row[3])
        los.append(row[3] - row[4])
        his.append(row[5] - row[3])
        names.append(name)
        ns.append(row[1])

    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1, color="0.6",
            label="calibration parfaite")
    ax.errorbar(xs, ys, yerr=[los, his], fmt="o", markersize=7, capsize=4,
                linewidth=1.5, color="#1f4e79", label="palier observe (IC Wilson 95 %)")
    # Annotations toujours a droite : les paliers se tassent vers x=1 et une
    # etiquette placee a gauche traverserait la barre du palier voisin.
    for x, y, name, n in zip(xs, ys, names, ns):
        ax.annotate(f"{name}  N={n}", (x, y), textcoords="offset points",
                    xytext=(12, -3), fontsize=8, color="0.25", ha="left")
    ax.set_xlabel("confidence annoncee (moyenne du palier)")
    ax.set_ylabel("accuracy empirique")
    ax.set_title("Calibration par palier")
    ax.set_xlim(0, 1.32)
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_risk_coverage(rows: list[tuple], path: Path) -> None:
    coverage = [r[2] for r in rows]
    accuracy = [r[4] for r in rows]
    los = [r[4] - r[5] for r in rows]
    his = [r[6] - r[4] for r in rows]
    labels = [f"{r[0]:.2f}" for r in rows]

    fig, ax = plt.subplots(figsize=(7.5, 6))
    # Points non relies : chaque palier est un point de fonctionnement atteignable,
    # rien n'est defini entre deux paliers et un trait le laisserait croire.
    ax.errorbar(coverage, accuracy, yerr=[los, his], fmt="o", markersize=7,
                capsize=4, linewidth=1.5, linestyle="none", color="#1f4e79",
                label="palier (IC Wilson 95 %)")
    for x, y, label, row in zip(coverage, accuracy, labels, rows):
        right = x > 0.92
        ax.annotate(f"seuil {label}\nN={row[1]}", (x, y), textcoords="offset points",
                    xytext=(-10 if right else 10, 8), fontsize=8, color="0.25",
                    ha="right" if right else "left")
    ax.set_xlabel("coverage : part des exemples traites")
    ax.set_ylabel("selective accuracy sur la zone couverte")
    ax.set_title("Risk-coverage : points de fonctionnement par palier")
    ax.set_xlim(min(coverage) - 0.08, 1.08)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse d'un JSONL de results/raw/.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--figdir", type=Path, default=DEFAULT_FIGDIR)
    args = parser.parse_args()

    records = load(args.input)
    correct = sum(r["correct"] for r in records)

    print(f"fichier      : {args.input}")
    print(f"lignes       : {len(records)}")
    print(f"model_id     : {sorted({r['model_id'] for r in records})}")
    print(f"prompt_hash  : {sorted({r['prompt_hash'] for r in records})}")
    low, high = wilson(correct, len(records))
    print(f"accuracy     : {correct}/{len(records)} = {correct/len(records)*100:.1f}% "
          f"[{low*100:.1f}%, {high*100:.1f}%]")

    level_rows = table_by_level(records)
    print(f"\n{'='*66}\n1. NIVEAUX DE CONFIDENCE OBSERVES ({len(level_rows)})\n{'='*66}")
    print_level_table(level_rows)

    tier_rows = table_by_tier(records)
    print(f"\n{'='*66}\n2. PALIERS\n{'='*66}")
    print_tier_table(tier_rows)

    print(f"\n{'='*80}\n3. RISK-COVERAGE, un point par niveau observe, sans interpolation\n{'='*80}")
    print_risk_coverage(risk_coverage(records, [r[0] for r in level_rows]))

    print(f"\n{'='*78}\n4. POUVOIR DISCRIMINANT HORS ATOME 1.00\n{'='*78}")
    print_discrimination(records)

    args.figdir.mkdir(parents=True, exist_ok=True)
    tier_thresholds = [lo for _, lo, _ in TIERS if math.isfinite(lo)]
    tier_thresholds.append(min(r["confidence_r"] for r in records))
    plot_calibration(tier_rows, records, args.figdir / "calibration.png")
    plot_risk_coverage(risk_coverage(records, sorted(set(tier_thresholds), reverse=True)),
                       args.figdir / "risk_coverage.png")
    print(f"\n{'='*78}\n5. GRAPHES (traces sur les paliers, pas sur les {len(level_rows)} niveaux)\n{'='*78}")
    print(f"  {args.figdir / 'calibration.png'}")
    print(f"  {args.figdir / 'risk_coverage.png'}")


if __name__ == "__main__":
    main()
