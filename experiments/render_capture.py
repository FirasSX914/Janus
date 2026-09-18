"""Rend la capture de `janus measure` affichee en tete du README.

Les chemins de la ligne de commande sont ceux du depot : la commande affichee
est lancable telle quelle.

La sortie est REELLE : elle est produite en rejouant les JSONL commites a
travers le paquet, pas ecrite a la main. Seul le milieu du balayage est elide,
et la ligne d'elision le dit.

    python experiments/render_capture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))

from janus.measure import calibration_of  # noqa: E402
from janus.sweep import Row, choose, oracle_accuracy, sweep  # noqa: E402

OUT = ROOT / "results" / "figures" / "cli_measure.png"
#: Lignes du balayage conservees autour du seuil retenu. Le reste est elide.
KEEP_AROUND = 4

# Couleurs d'un terminal sombre : l'image est son propre fond, donc elle reste
# lisible sous les deux themes de GitHub.
BACKGROUND = "#12161c"
TEXT = "#d5dae1"
DIM = "#7f8a99"
ACCENT = "#7aa2f7"
GOOD = "#9ece6a"


def _rows() -> tuple[list[Row], list[dict]]:
    raw = ROOT / "results" / "raw"
    primary = [json.loads(l) for l
               in (raw / "jev_banking77_500.jsonl").read_text(encoding="utf-8").splitlines()
               if l.strip()]
    fallback = {r["id"]: r for r in
                (json.loads(l) for l
                 in (raw / "deepseek_banking77_500.jsonl").read_text(encoding="utf-8").splitlines()
                 if l.strip())}
    rows = [Row(p["confidence"],
                p["prediction"] == p["gold_label"],
                fallback[p["id"]]["prediction"] == fallback[p["id"]]["gold_label"],
                p["input_tokens"] / 1e6 * 0.042,
                fallback[p["id"]]["cost_usd"],
                p["latency_ms"],
                fallback[p["id"]]["latency_ms"])
            for p in primary]
    return rows, primary


def capture() -> list[tuple[str, str]]:
    """Rend (texte, role) par ligne, le role servant a la couleur."""
    rows, primary = _rows()
    points = sweep(rows)
    chosen, verdict, reason = choose(points)
    report = calibration_of(primary)

    lines: list[tuple[str, str]] = [
        ("$ janus measure --dataset data/banking77_500.jsonl \\", "prompt"),
        ("      --labels data/banking77.labels.json \\", "prompt"),
        ("      --primary typesafe:jev-latest --fallback deepseek:deepseek-v4-pro", "prompt"),
        ("", "dim"),
        ("CALIBRATION OF THE PRIMARY", "head"),
        (f"  accuracy          : {report.accuracy:.1%} "
         f"[{report.accuracy_ci[0]:.1%}, {report.accuracy_ci[1]:.1%}]", "text"),
        (f"  mean confidence   : {report.mean_confidence:.1%}", "text"),
        (f"  gap               : {report.mean_confidence - report.accuracy:+.1%}", "text"),
        (f"  observed levels   : {len(report.levels)}", "text"),
        ("", "dim"),
        ("OPERATING POINTS, one per observed confidence level", "head"),
        (f"  {'rule':<26}{'thr':>6}{'cov':>8}{'acc':>8}{'cost':>10}{'p50':>9}", "dim"),
    ]

    routed = [p for p in points if p.rule == "primary_if_confidence_ge"]
    best_index = routed.index(chosen) if chosen in routed else 0
    window = set(range(max(0, best_index - KEEP_AROUND), best_index + KEEP_AROUND + 1))

    def render(point) -> str:
        thr = "-" if point.threshold is None else f"{point.threshold:.2f}"
        return (f"  {point.rule:<26}{thr:>6}{point.coverage:>7.1%}{point.accuracy:>8.1%}"
                f"{point.cost_total:>10.4f}{point.latency_p50_ms:>7.0f}ms")

    for point in points:
        if point.rule != "primary_if_confidence_ge":
            lines.append((render(point), "text"))
    # Deux coupures encadrent la fenetre : chacune annonce SON propre compte,
    # pas le total elide.
    pending = 0
    for index, point in enumerate(routed):
        if index in window:
            if pending:
                lines.append((f"  ... {pending} more thresholds, "
                              "written to the report", "dim"))
                pending = 0
            lines.append((render(point), "best" if point is chosen else "text"))
        else:
            pending += 1
    if pending:
        lines.append((f"  ... {pending} more thresholds, written to the report", "dim"))

    lines += [
        ("", "dim"),
        (f"VERDICT: {verdict.upper().replace('_', ' ')}", "head"),
        (f"  rule      : {chosen.rule}", "text"),
        (f"  threshold : {chosen.threshold}", "best"),
        (f"  reason    : {reason}", "text"),
        (f"  ceiling   : {oracle_accuracy(rows):.1%} "
         "(this pair of models, not the task)", "text"),
        ("", "dim"),
        ("policy written to janus.json", "good"),
    ]
    return lines


def render_png(lines: list[tuple[str, str]], path: Path) -> None:
    colours = {"prompt": ACCENT, "head": TEXT, "text": TEXT,
               "dim": DIM, "best": GOOD, "good": GOOD}
    width = max(len(text) for text, _ in lines)
    fig_w = max(9.0, width * 0.085)
    fig_h = max(3.0, len(lines) * 0.215 + 0.5)
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=BACKGROUND)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(BACKGROUND); ax.axis("off")

    step = 1.0 / (len(lines) + 1)
    for index, (text, role) in enumerate(lines):
        weight = "bold" if role in ("head", "best") else "normal"
        ax.text(0.018, 1 - (index + 0.9) * step, text, family="monospace",
                fontsize=11, color=colours[role], weight=weight,
                va="center", ha="left", transform=ax.transAxes)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=BACKGROUND)
    plt.close(fig)


if __name__ == "__main__":
    rendered = capture()
    for text, _ in rendered:
        print(text)
    render_png(rendered, OUT)
    print(f"\nwritten to {OUT}")
