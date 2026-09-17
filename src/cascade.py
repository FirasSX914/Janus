"""Simulation de cascade Jev -> frontier. AUCUN appel API.

Lit deux JSONL de results/raw/ et ne fait que du calcul. La regle de routage est
la seule variable : si la confidence Jev atteint le seuil, la reponse de Jev est
retenue ; sinon la requete est escaladee vers le frontier et c'est sa reponse qui
compte.

Le cout d'une cascade inclut TOUJOURS Jev sur 100 % des requetes -- il faut
l'interroger pour connaitre sa confiance -- plus le frontier sur la seule
fraction escaladee. Les couts sont les couts REELS mesures, ligne a ligne :
`input_tokens` x tarif Jev d'un cote, colonne `cost_usd` de l'autre, laquelle
tient deja compte de la decoupe du cache et du regime horaire.

Ce script ne choisit pas de seuil et n'interprete pas ses sorties.
"""

import argparse
import collections
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JEV_PATH = ROOT / "results" / "raw" / "jev_banking77_500.jsonl"
FRONTIER_PATH = ROOT / "results" / "raw" / "deepseek_banking77_500.jsonl"
FIG_DIR = ROOT / "results" / "figures"

# Jev : 42 $/Btok sur les tokens d'entree, sortie gratuite (docs.typesafe.ai/models).
JEV_USD_PER_MTOK = 0.042

# Cibles pre-enregistrees, fixees avant tout run frontier. Non revisables.
TARGETS = (0.90, 0.95, 0.98)

TIERS = (
    ("1.00", 1.00, 1.01),
    ("[0.95, 1.00[", 0.95, 1.00),
    ("[0.90, 0.95[", 0.90, 0.95),
    ("[0.70, 0.90[", 0.70, 0.90),
    ("< 0.70", -1.0, 0.70),
)


def load() -> list[dict]:
    jev = {json.loads(l)["id"]: json.loads(l)
           for l in JEV_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    frontier = {json.loads(l)["id"]: json.loads(l)
                for l in FRONTIER_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    assert set(jev) == set(frontier), "les deux runs ne couvrent pas les memes ids"
    rows = []
    for i in sorted(jev):
        j, f = jev[i], frontier[i]
        assert j["gold_label"] == f["gold_label"]
        rows.append({
            "id": i,
            "gold": j["gold_label"],
            "jev_pred": j["prediction"],
            "frontier_pred": f["prediction"],
            "jev_ok": j["prediction"] == j["gold_label"],
            "frontier_ok": f["prediction"] == f["gold_label"],
            # Arrondi au centieme avant tout regroupement, cf. METHOD.md.
            "confidence": round(j["confidence"], 2),
            "jev_cost": j["input_tokens"] / 1e6 * JEV_USD_PER_MTOK,
            "frontier_cost": f["cost_usd"],
        })
    return rows


def simulate(rows: list[dict], threshold: float) -> dict:
    """Seuil t : Jev tranche si confidence >= t, sinon escalade."""
    kept = [r for r in rows if r["confidence"] >= threshold]
    escalated = [r for r in rows if r["confidence"] < threshold]
    correct = sum(r["jev_ok"] for r in kept) + sum(r["frontier_ok"] for r in escalated)
    cost = sum(r["jev_cost"] for r in rows) + sum(r["frontier_cost"] for r in escalated)
    return {
        "threshold": threshold,
        "coverage": len(kept) / len(rows),
        "escalated": len(escalated) / len(rows),
        "n_escalated": len(escalated),
        "correct": correct,
        "accuracy": correct / len(rows),
        "cost": cost,
    }


def plot_accuracy_vs_cost(results: list[dict], refs: dict, path: Path) -> None:
    """Accuracy vs cout, un point par seuil du balayage.

    Echelle de cout LINEAIRE : une echelle log rendrait la comparaison de couts
    absolus trompeuse, ce qui est precisement ce que la figure doit montrer.
    Fond blanc explicite, pas de transparence : une image transparente devient
    illisible selon le theme clair ou sombre du lecteur.
    """
    fig, ax = plt.subplots(figsize=(9, 5.6), facecolor="white")
    ax.set_facecolor("white")

    xs = [s["cost"] for s in results]
    ys = [s["accuracy"] * 100 for s in results]
    ax.scatter(xs, ys, s=26, color="#1f4e79", alpha=0.75, zorder=3,
               label="routing — one point per confidence threshold")

    # Libelles explicites : la figure doit se lire sans avoir ouvert METHOD.md.
    ax.axhline(refs["oracle"] * 100, linestyle="--", linewidth=1.4, color="#7a7a7a",
               zorder=2,
               label=f"ceiling — {refs['oracle']*100:.1f}% (best possible if either model is right)")
    ax.scatter([refs["jev_cost"]], [refs["jev_acc"] * 100], s=150, marker="s",
               color="#2e7d32", zorder=5,
               label=f"Jev alone — {refs['jev_acc']*100:.1f}%, ${refs['jev_cost']:.3f}")
    ax.scatter([refs["frontier_cost"]], [refs["frontier_acc"] * 100], s=150, marker="^",
               color="#b3541e", zorder=5,
               label=f"DeepSeek alone — {refs['frontier_acc']*100:.1f}%, ${refs['frontier_cost']:.3f}")

    best = max(results, key=lambda s: s["accuracy"])
    ax.scatter([best["cost"]], [best["accuracy"] * 100], s=230, marker="*",
               color="#c62828", zorder=6,
               label=f"Jev → DeepSeek at {best['threshold']:.2f} — "
                     f"{best['accuracy']*100:.1f}%, ${best['cost']:.3f}")
    ax.annotate(
        f"threshold {best['threshold']:.2f}\n{best['accuracy']*100:.1f}% "
        f"for ${best['cost']:.3f}\n{best['n_escalated']} DeepSeek calls",
        (best["cost"], best["accuracy"] * 100), textcoords="offset points",
        xytext=(14, -6), fontsize=9, color="#c62828",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                  edgecolor="#c62828", linewidth=0.9),
    )

    ax.set_xlabel("cost per 500 decisions (USD, measured — lower is better)")
    ax.set_ylabel("accuracy (%) — higher is better")
    ax.set_title("Accuracy vs cost on 500 Banking77 examples\n"
                 "escalating to DeepSeek only when Jev's confidence is low",
                 fontsize=12)
    ax.set_xlim(0, max(xs + [refs["frontier_cost"]]) * 1.16)
    ax.grid(alpha=0.3, zorder=0)
    # Coin haut-droit : le seul quadrant vide. En bas a droite la legende
    # recouvrait le marqueur "DeepSeek only".
    ax.legend(loc="upper right", fontsize=9, framealpha=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--errors-top", type=int, default=10)
    parser.parse_args()

    rows = load()
    n = len(rows)
    jev_cost = sum(r["jev_cost"] for r in rows)
    frontier_cost = sum(r["frontier_cost"] for r in rows)
    jev_ok = sum(r["jev_ok"] for r in rows)
    frontier_ok = sum(r["frontier_ok"] for r in rows)
    oracle_ok = sum(r["jev_ok"] or r["frontier_ok"] for r in rows)

    print("=" * 96)
    print("REFERENCES")
    print("=" * 96)
    print(f"{'':<22} {'Accuracy':>10} {'Cout':>12}  note")
    print("-" * 96)
    print(f"{'Jev seul':<22} {jev_ok/n*100:>9.1f}% {jev_cost:>11.6f} $  aucune escalade")
    print(f"{'DeepSeek seul':<22} {frontier_ok/n*100:>9.1f}% {frontier_cost:>11.6f} $  "
          f"reference de comparaison")
    print(f"{'Oracle':<22} {oracle_ok/n*100:>9.1f}% {'-':>11}    plafond de CETTE cascade : "
          f"{n - oracle_ok} cas ou aucun des deux n'a la reponse")

    levels = sorted({r["confidence"] for r in rows}, reverse=True)
    # Un seuil au-dessus du maximum = tout escalader.
    thresholds = [round(max(levels) + 0.01, 2)] + levels

    print()
    print("=" * 96)
    print("1. CASCADE, un seuil par niveau de confidence Jev observe")
    print("=" * 96)
    print(f"{'Seuil':>6} | {'Couv. Jev':>9} | {'Escalade':>13} | {'Accuracy':>9} | "
          f"{'Cout total':>12} | {'Econ. vs DS seul':>17}")
    print("-" * 96)
    results = []
    for t in thresholds:
        s = simulate(rows, t)
        results.append(s)
        saving = frontier_cost - s["cost"]
        print(f"{t:>6.2f} | {s['coverage']*100:>8.1f}% | "
              f"{s['escalated']*100:>6.1f}% ({s['n_escalated']:>3}) | "
              f"{s['accuracy']*100:>8.1f}% | {s['cost']:>11.6f} $ | "
              f"{saving:>+10.6f} $ ({saving/frontier_cost*100:>+5.1f}%)")

    print()
    print("=" * 96)
    print("2. CIBLES PRE-ENREGISTREES")
    print("=" * 96)
    best = max(results, key=lambda s: s["accuracy"])
    print(f"  accuracy maximale atteinte par la cascade : {best['accuracy']*100:.1f} % "
          f"au seuil {best['threshold']:.2f}")
    print(f"  plafond oracle                            : {oracle_ok/n*100:.1f} %")
    print()
    for target in TARGETS:
        reached = [s for s in results if s["accuracy"] >= target]
        status = "ATTEINTE" if reached else "UNATTAINABLE"
        print(f"  cible {target*100:>4.0f} % : {status:<13} "
              f"| meilleur seuil atteint {best['threshold']:.2f} "
              f"-> {best['accuracy']*100:.1f} % "
              f"(ecart {(target - best['accuracy'])*100:+.1f} points)")
    print()
    print("  Cibles non revisees. Voir METHOD.md, section des cibles.")

    print()
    print("=" * 96)
    print(f"3. ERREURS COMMUNES AUX DEUX MODELES")
    print("=" * 96)
    common = [r for r in rows if not r["jev_ok"] and not r["frontier_ok"]]
    same = [r for r in common if r["jev_pred"] == r["frontier_pred"]]
    diff = [r for r in common if r["jev_pred"] != r["frontier_pred"]]
    print(f"  {len(common)} erreurs communes : {len(same)} avec la MEME prediction, "
          f"{len(diff)} avec des predictions differentes")
    print()
    pairs = collections.Counter((r["gold"], r["jev_pred"]) for r in same)
    print(f"  Les {min(10, len(pairs))} paires (gold -> prediction partagee) les plus frequentes :")
    print(f"  {'n':>3}  {'gold':<42} -> prediction")
    print("  " + "-" * 92)
    for (gold, pred), count in pairs.most_common(10):
        print(f"  {count:>3}  {gold:<42} -> {pred}")
    print(f"\n  ({len(pairs)} paires distinctes sur les {len(same)} erreurs partagees)")
    print()
    print(f"  Les {len(diff)} cas ou les deux se trompent DIFFEREMMENT :")
    print(f"  {'id':>5}  {'gold':<38} {'Jev':<28} DeepSeek")
    print("  " + "-" * 92)
    for r in diff:
        print(f"  {r['id']:>5}  {r['gold'][:38]:<38} {r['jev_pred'][:28]:<28} {r['frontier_pred']}")

    print()
    print("=" * 96)
    print("4. DESACCORDS : DISTRIBUTION DE LA CONFIDENCE JEV")
    print("=" * 96)
    jev_right = [r for r in rows if r["jev_ok"] and not r["frontier_ok"]]
    ds_right = [r for r in rows if r["frontier_ok"] and not r["jev_ok"]]
    print(f"  {len(jev_right) + len(ds_right)} desaccords : "
          f"{len(jev_right)} ou Jev a raison, {len(ds_right)} ou DeepSeek a raison")
    print()
    print(f"  {'Palier de confidence Jev':<26} | {'Jev a raison':>14} | {'DeepSeek a raison':>18} | "
          f"{'total':>6}")
    print("  " + "-" * 76)
    for label, lo, hi in TIERS:
        a = sum(1 for r in jev_right if lo <= r["confidence"] < hi)
        b = sum(1 for r in ds_right if lo <= r["confidence"] < hi)
        base = sum(1 for r in rows if lo <= r["confidence"] < hi)
        print(f"  {label:<26} | {a:>6} ({a/max(len(jev_right),1)*100:>4.1f}%) | "
              f"{b:>7} ({b/max(len(ds_right),1)*100:>4.1f}%) | {a+b:>4} / {base}")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / "accuracy_vs_cost.png"
    plot_accuracy_vs_cost(results, {
        "jev_acc": jev_ok / n, "jev_cost": jev_cost,
        "frontier_acc": frontier_ok / n, "frontier_cost": frontier_cost,
        "oracle": oracle_ok / n,
    }, out)
    print()
    print("=" * 96)
    print("FIGURE")
    print("=" * 96)
    print(f"  {out}")


if __name__ == "__main__":
    main()
