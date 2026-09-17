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

import tasks  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIGDIR = ROOT / "results" / "figures"

Z95 = 1.959963984540054
SMALL_N = 10  # en deca, l'intervalle est trop large pour lire la ligne seule
BOOTSTRAP_ITERS = 10_000
BOOTSTRAP_SEED = 1729  # distinct de la graine 42 du dataset, pour ne pas les confondre

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


def average_ranks(values: np.ndarray) -> np.ndarray:
    """Rangs a partir de 1, ex aequo ramenes au rang moyen du groupe."""
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    starts_group = np.empty(len(ordered), dtype=bool)
    starts_group[0] = True
    starts_group[1:] = ordered[1:] != ordered[:-1]
    group = np.cumsum(starts_group) - 1
    counts = np.bincount(group)
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    mean_rank = starts + (counts - 1) / 2 + 1
    ranks = np.empty(len(ordered), dtype=float)
    ranks[order] = mean_rank[group]
    return ranks


def auroc(scores: np.ndarray, correct: np.ndarray) -> float:
    """AUROC de `scores` pour separer les reponses justes des fausses.

    Statistique de Mann-Whitney sur rangs moyens : les ex aequo comptent 1/2,
    ce qui est indispensable ici puisque les scores vivent sur une grille
    grossiere et produisent beaucoup d'egalites.
    """
    n_pos = int(correct.sum())
    n_neg = int(len(correct) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = average_ranks(scores)
    return (ranks[correct].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


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


def print_bootstrap(records: list[dict]) -> None:
    """Bootstrap apparie des AUROC et de leurs differences, hors atome 1.00."""
    zone = [r for r in records if r["confidence_r"] < 1.00]
    correct = np.array([r["correct"] for r in zone], dtype=bool)
    n = len(zone)
    columns = {
        "confidence": np.array([r["confidence_r"] for r in zone], dtype=float),
        "margin_top2": np.array([r["margin_top2"] for r in zone], dtype=float),
        # Orientation documentee dans METHOD.md : entropy_norm varie en sens inverse.
        "entropy_norm": np.array([-r["entropy_norm"] for r in zone], dtype=float),
        "ratio_top2": np.array([r["ratio_top2"] for r in zone], dtype=float),
    }

    print(f"Reechantillonnage APPARIE : a chaque tirage, le meme jeu d'indices est")
    print(f"applique aux quatre scores, donc les differences portent exactement sur")
    print(f"les memes observations. {BOOTSTRAP_ITERS} iterations, graine {BOOTSTRAP_SEED},")
    print(f"tirage avec remise de {n} observations parmi {n}.\n")

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = {name: np.empty(BOOTSTRAP_ITERS) for name in columns}
    degenerate = 0
    for i in range(BOOTSTRAP_ITERS):
        idx = rng.integers(0, n, n)
        resampled_correct = correct[idx]
        if resampled_correct.all() or not resampled_correct.any():
            degenerate += 1
            for name in columns:
                draws[name][i] = np.nan
            continue
        for name, values in columns.items():
            draws[name][i] = auroc(values[idx], resampled_correct)

    point = {name: auroc(values, correct) for name, values in columns.items()}
    print(f"{'Statistique':>14} | {'AUROC':>6} | {'IC 95 % bootstrap':>20}")
    print("-" * 78)
    for name in columns:
        low, high = np.nanpercentile(draws[name], [2.5, 97.5])
        print(f"{name:>14} | {point[name]:>6.3f} | [{low:>6.3f}, {high:>6.3f}]")

    print(f"\nDifferences appariees, positif = confidence discrimine mieux :\n")
    print(f"{'Difference':>30} | {'Ecart':>7} | {'IC 95 % bootstrap':>18} | verdict")
    print("-" * 92)
    verdicts = []
    for name in ("entropy_norm", "margin_top2", "ratio_top2"):
        diff = draws["confidence"] - draws[name]
        low, high = np.nanpercentile(diff, [2.5, 97.5])
        observed = point["confidence"] - point[name]
        includes_zero = low <= 0 <= high
        verdicts.append(includes_zero)
        verdict = "l'IC englobe zero" if includes_zero else "l'IC exclut zero"
        label = f"confidence - {name}"
        print(f"{label:>30} | {observed:>+7.3f} | [{low:>+6.3f}, {high:>+6.3f}] | {verdict}")

    if degenerate:
        print(f"\n{degenerate} tirages ecartes : une seule classe apres reechantillonnage.")
    print()
    if all(verdicts):
        print("Les trois intervalles englobent zero : pouvoir discriminant comparable")
        print("dans la zone non saturee. Aucune des quatre statistiques ne se distingue")
        print("des autres sur ces donnees.")
    elif any(verdicts):
        print("Certains intervalles englobent zero, d'autres non : voir le detail")
        print("ligne a ligne ci-dessus. Un ecart ponctuel dont l'IC contient zero ne")
        print("permet pas de departager deux statistiques.")
    else:
        print("Aucun intervalle n'englobe zero sur ces donnees.")


def plot_calibration_levels(level_rows: list[tuple], path: Path) -> None:
    """Confidence annoncee vs accuracy empirique, un point par niveau observe.

    L'atome 1.00 est trace distinctement : il porte a lui seul pres de la moitie
    du trafic, et toute statistique derivee de `probabilities` y est constante.
    Les niveaux a faible effectif sont dessines en plus clair et leurs barres de
    Wilson montrent d'elles-memes ce qu'ils ne permettent pas de conclure.

    Fond blanc explicite, pas de transparence : une image transparente devient
    illisible selon le theme clair ou sombre du lecteur.
    """
    atom = [r for r in level_rows if r[0] >= 1.0]
    big = [r for r in level_rows if r[0] < 1.0 and r[1] >= SMALL_N]
    small = [r for r in level_rows if r[0] < 1.0 and r[1] < SMALL_N]

    fig, ax = plt.subplots(figsize=(9, 5.6), facecolor="white")
    ax.set_facecolor("white")
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1.2, color="#7a7a7a",
            zorder=1, label="perfect calibration")

    def draw(rows, color, size, alpha, label):
        if not rows:
            return
        xs = [r[0] for r in rows]
        ys = [r[3] for r in rows]
        lo = [r[3] - r[4] for r in rows]
        hi = [r[5] - r[3] for r in rows]
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="o", markersize=size, capsize=3,
                    linewidth=1.1, linestyle="none", color=color, alpha=alpha,
                    zorder=3, label=label)

    draw(small, "#9db8d2", 5, 0.85, f"observed level, N < {SMALL_N} (95% Wilson)")
    draw(big, "#1f4e79", 8, 1.0, f"observed level, N ≥ {SMALL_N} (95% Wilson)")
    draw(atom, "#c62828", 13, 1.0, "the 1.00 atom")

    if atom:
        level, n, _, accuracy, _, high = atom[0]
        ax.annotate(f"confidence = 1.00\nN = {n} ({n/5:.0f}% of traffic)\n"
                    f"accuracy {accuracy*100:.1f}%",
                    (level, accuracy), textcoords="offset points", xytext=(-14, -30),
                    ha="right", fontsize=9, color="#c62828",
                    bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                              edgecolor="#c62828", linewidth=0.9))

    ax.set_xlabel("confidence reported by Jev (0.01 grid)")
    ax.set_ylabel("empirical accuracy (%)")
    ax.set_title("Calibration — reported confidence vs empirical accuracy")
    ax.set_xlim(0.15, 1.06)
    ax.set_ylim(-0.04, 1.08)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0", "20", "40", "60", "80", "100"])
    ax.grid(alpha=0.3, zorder=0)
    ax.legend(loc="lower right", fontsize=9, framealpha=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


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

    fig, ax = plt.subplots(figsize=(9, 5.6), facecolor="white")
    ax.set_facecolor("white")
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1.2, color="#7a7a7a",
            zorder=1, label="perfect calibration")

    # L'atome 1.00 est le dernier palier et se distingue des autres : il porte
    # pres de la moitie du trafic et aucune statistique derivee de
    # `probabilities` n'y varie.
    atom = [i for i, name in enumerate(names) if name == "1.00"]
    rest = [i for i, name in enumerate(names) if name != "1.00"]
    for idx, color, size, label in (
        (rest, "#1f4e79", 9, "confidence tier (95% Wilson)"),
        (atom, "#c62828", 14, "the 1.00 atom"),
    ):
        if not idx:
            continue
        ax.errorbar([xs[i] for i in idx], [ys[i] for i in idx],
                    yerr=[[los[i] for i in idx], [his[i] for i in idx]],
                    fmt="o", markersize=size, capsize=4, linewidth=1.5,
                    linestyle="none", color=color, zorder=3, label=label)

    # Annotations toujours a droite : les paliers se tassent vers x=1 et une
    # etiquette placee a gauche traverserait la barre du palier voisin.
    for i, (x, y, name, n) in enumerate(zip(xs, ys, names, ns)):
        color = "#c62828" if name == "1.00" else "0.25"
        ax.annotate(f"{name}   N={n}   {ys[i]*100:.1f}%", (x, y),
                    textcoords="offset points", xytext=(13, -3), fontsize=9,
                    color=color, ha="left")
    ax.set_xlabel("confidence reported by Jev (tier mean, 0.01 grid)")
    ax.set_ylabel("empirical accuracy (%)")
    ax.set_title("Calibration — reported confidence vs empirical accuracy")
    ax.set_xlim(0.3, 1.45)
    ax.set_ylim(0.2, 1.06)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["20", "40", "60", "80", "100"])
    ax.grid(alpha=0.3, zorder=0)
    ax.legend(loc="upper left", fontsize=9, framealpha=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def plot_risk_coverage(rows: list[tuple], path: Path) -> None:
    """Points de fonctionnement atteignables, un par palier.

    Points non relies : rien n'est defini entre deux paliers et un trait le
    laisserait croire. Fond blanc explicite, comme les autres figures.
    """
    coverage = [r[2] for r in rows]
    accuracy = [r[4] * 100 for r in rows]
    los = [(r[4] - r[5]) * 100 for r in rows]
    his = [(r[6] - r[4]) * 100 for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5.6), facecolor="white")
    ax.set_facecolor("white")
    ax.errorbar(coverage, accuracy, yerr=[los, his], fmt="o", markersize=8,
                capsize=4, linewidth=1.5, linestyle="none", color="#1f4e79",
                label="confidence tier (95% Wilson)")
    for x, y, row in zip(coverage, accuracy, rows):
        right = x > 0.92
        ax.annotate(f"threshold {row[0]:.2f}\nN={row[1]}", (x, y),
                    textcoords="offset points",
                    xytext=(-12 if right else 12, 8), fontsize=9, color="0.25",
                    ha="right" if right else "left")
    ax.set_xlabel("coverage — share of requests answered by Jev alone")
    ax.set_ylabel("accuracy (%) on the covered share")
    ax.set_title("Risk-coverage — reachable operating points")
    ax.set_xlim(min(coverage) - 0.09, 1.1)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=9, framealpha=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse d'un JSONL de results/raw/.")
    parser.add_argument("--task", choices=sorted(tasks.TASKS), default="banking77")
    parser.add_argument("--runner", default="jev")
    parser.add_argument("--input", type=Path, default=None,
                        help="surcharge le fichier deduit de --task")
    parser.add_argument("--figdir", type=Path, default=DEFAULT_FIGDIR)
    args = parser.parse_args()

    task = tasks.load(args.task)
    # Les figures de la tache de reference gardent leur nom historique ; les
    # autres sont suffixees, pour que le README ne change pas de cible.
    suffix = "" if task.name == "banking77" else f"_{task.name}"
    path = args.input or task.out_path(args.runner)
    records = load(path)
    correct = sum(r["correct"] for r in records)

    print(f"tache        : {task.name}, {len(task.criteria)} classes")
    print(f"fichier      : {path}")
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

    print(f"\n{'='*92}\n4b. BOOTSTRAP APPARIE DES AUROC ET DE LEURS DIFFERENCES\n{'='*92}")
    print_bootstrap(records)

    args.figdir.mkdir(parents=True, exist_ok=True)
    tier_thresholds = [lo for _, lo, _ in TIERS if math.isfinite(lo)]
    tier_thresholds.append(min(r["confidence_r"] for r in records))
    # Figure principale : les paliers. Les 63 niveaux observes, dont 58 sous
    # N=10, produisent un nuage de barres de Wilson illisible et suggerent une
    # precision que les donnees n'ont pas. La version par niveau est conservee
    # a part, pour qui veut la detailler.
    plot_calibration(tier_rows, records, args.figdir / f"calibration{suffix}.png")
    plot_calibration_levels(level_rows, args.figdir / f"calibration_levels{suffix}.png")
    plot_risk_coverage(risk_coverage(records, sorted(set(tier_thresholds), reverse=True)),
                       args.figdir / f"risk_coverage{suffix}.png")
    print(f"\n{'='*78}\n5. GRAPHES (traces sur les paliers, pas sur les {len(level_rows)} niveaux)\n{'='*78}")
    print(f"  {args.figdir / f'calibration{suffix}.png'}")
    print(f"  {args.figdir / f'risk_coverage{suffix}.png'}")


if __name__ == "__main__":
    main()
