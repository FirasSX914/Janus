"""Etape 4 : le rapport. Zero appel API, tout est relu depuis les JSONL.

Ce qui est mesure est un ACCORD, jamais une justesse. Le script refuse
mecaniquement d'emettre un rapport contenant "accuracy", "correct",
"ground truth" ou "error rate" : la garantie est executable, pas declarative.

Trois vues : janus seul, tenor seul, combine. Si la relation entre confiance et
accord differe entre les sources, c'est un resultat, pas un bruit a moyenner.

    python experiments/gate/analyze_gate.py

Voir docs/METHOD_GATE.md.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "results" / "raw"
Z95 = 1.959963984540054

#: Paliers DISJOINTS. Des paliers emboites partagent leurs lignes et donnent
#: des intervalles qui ne sont pas independants.
TIERS = (("[0.95, 1.00]", 0.95, 1.01),
         ("[0.90, 0.95)", 0.90, 0.95),
         ("[0.80, 0.90)", 0.80, 0.90),
         ("[0.00, 0.80)", 0.00, 0.80))

#: Un palier sous ce seuil est rapporte mais ne participe pas au critere.
MIN_TIER = 10

#: Mots interdits, en correspondance MOT ENTIER. La formule imposee par le
#: protocole est "not correctness" : une correspondance par sous-chaine
#: bannirait la phrase meme que le garde-fou existe pour proteger.
BANNED = (r"\baccurac(?:y|ies)\b", r"\bcorrect(?:ly)?\b",
          r"\bground[ -]truth\b", r"\berror rates?\b")


def wilson(hits: int, n: int) -> tuple[float, float]:
    """Intervalle de Wilson a 95 % pour une proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = hits / n
    denom = 1 + Z95**2 / n
    center = (p + Z95**2 / (2 * n)) / denom
    half = Z95 / denom * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2))
    return max(0.0, center - half), min(1.0, center + half)


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(line) for line
                                 in path.read_text(encoding="utf-8").splitlines()
                                 if line.strip())}


def pct(value: float) -> str:
    return "  n/a " if value != value else f"{value:6.1%}"


def tier_rows(rows: list[dict]) -> list[tuple[str, int, int | None, tuple]]:
    out = []
    for label, low, high in TIERS:
        inside = [r for r in rows if low <= r["confidence"] < high]
        hits = sum(1 for r in inside if r.get("agree")) if inside else 0
        agreed = hits if any("agree" in r for r in inside) else None
        out.append((label, len(inside), agreed,
                    wilson(hits, len(inside)) if inside else (float("nan"),) * 2))
    return out


def report(out: io.StringIO, rows: list[dict], label: str, paired: bool) -> None:
    n = len(rows)
    out.write(f"\n{'=' * 66}\n{label}   N = {n}\n{'=' * 66}\n")
    if not n:
        out.write("  aucune decision\n")
        return

    jev = Counter(r["prediction"] for r in rows)
    out.write("\nClass distribution (Jev):        "
              + "   ".join(f"{k} {v} ({v / n:.1%})" for k, v in jev.most_common()) + "\n")
    if paired:
        ref = Counter(r["reference"] for r in rows)
        out.write("Class distribution (reference):  "
                  + "   ".join(f"{k} {v} ({v / n:.1%})" for k, v in ref.most_common()) + "\n")
        major = max(ref.values()) / n
        out.write(f"Majority-class baseline:         {major:.1%}"
                  "   <- agreement a constant model would reach\n")

    confidences = sorted(r["confidence"] for r in rows)
    out.write(f"\nJev confidence: min {confidences[0]:.2f}  median "
              f"{confidences[n // 2]:.2f}  mean {sum(confidences) / n:.3f}  "
              f"max {confidences[-1]:.2f}\n")
    saturated = sum(1 for c in confidences if c >= 1.0)
    out.write(f"  at 1.00 (atom): {saturated} ({saturated / n:.1%})\n")

    out.write("\n  tier            n   share" + ("   agreement          Wilson 95%\n"
                                                 if paired else "\n"))
    for tier, count, agreed, (lo, hi) in tier_rows(rows):
        line = f"  {tier:14s} {count:4d}  {count / n:6.1%}"
        if paired and count:
            line += f"   {agreed / count:6.1%}   [{pct(lo)}, {pct(hi)}]"
            if count < MIN_TIER:
                line += f"   (n<{MIN_TIER}, hors critere)"
        out.write(line + "\n")

    if not paired:
        return

    hits = sum(1 for r in rows if r["agree"])
    lo, hi = wilson(hits, n)
    out.write(f"\nAgreement with reference, overall: {hits / n:.1%}  "
              f"[{pct(lo)}, {pct(hi)}]\n")
    out.write("  (agreement with the selected reference model, not correctness)\n")

    confirm = [r for r in rows if r["reference"] == "CONFIRM"]
    if confirm:
        h = sum(1 for r in confirm if r["agree"])
        lo2, hi2 = wilson(h, len(confirm))
        out.write(f"\nSecondary, CONFIRM subset only: n={len(confirm)}  "
                  f"{h / len(confirm):.1%}  [{pct(lo2)}, {pct(hi2)}]\n")

    top = [r for r in rows if r["confidence"] >= 0.95 and not r["agree"]]
    out.write(f"\nDivergences at confidence >= 0.95: {len(top)}\n")
    for r in sorted(top, key=lambda r: -r["confidence"]):
        out.write(f"  {r['confidence']:.2f}  {r['source']:6s} {r['tool_name']:<22s} "
                  f"Jev={r['prediction']:<8s} reference={r['reference']}\n")


def stratified(out: io.StringIO, rows: list[dict]) -> None:
    """Accord par palier A CLASSE PREDITE CONSTANTE.

    Ajoutee au protocole avant le run de reference : les deux paliers hauts ne
    contiennent que des ALLOW, donc l'accord global et la classe predite sont
    confondus. A classe constante, si la confiance porte une information
    propre, l'accord doit encore monter avec elle.

    Descriptive : elle s'ajoute au critere preenregistre, ne le remplace pas.
    """
    out.write(f"\n{'=' * 66}\nSTRATIFIED BY PREDICTED CLASS   (added before the "
              f"reference run)\n{'=' * 66}\n")
    for label in ("ALLOW", "CONFIRM"):
        subset = [r for r in rows if r["prediction"] == label]
        out.write(f"\n  Jev predicted {label}  n={len(subset)}\n")
        if not subset:
            continue
        for tier, count, agreed, (lo, hi) in tier_rows(subset):
            line = f"    {tier:14s} {count:4d}"
            if count:
                line += f"   {agreed / count:6.1%}   [{pct(lo)}, {pct(hi)}]"
                if count < MIN_TIER:
                    line += f"   (n<{MIN_TIER}, not interpreted)"
            out.write(line + "\n")
        if label == "CONFIRM":
            out.write("    -> not interpretable: the tiers are degenerate, "
                      "almost every CONFIRM sits in one of them.\n")


def verdict(out: io.StringIO, rows: list[dict]) -> None:
    tiers = {label: (count, agreed, ci) for label, count, agreed, ci in tier_rows(rows)}
    high, low = tiers["[0.95, 1.00]"], tiers["[0.00, 0.80)"]
    out.write(f"\n{'=' * 66}\nPRE-REGISTERED CRITERION\n{'=' * 66}\n")
    if high[0] < MIN_TIER or low[0] < MIN_TIER:
        out.write(f"  inconclusive: tier sizes {high[0]} and {low[0]}, "
                  f"under the pre-registered minimum of {MIN_TIER}.\n")
        return
    separated = high[2][0] > low[2][1]
    rises = high[1] / high[0] > low[1] / low[0]
    # Seconde clause du critere preenregistre, qui manquait ici : un accord
    # global qui ne bat pas la classe majoritaire est plat, quelle que soit la
    # pente entre les paliers.
    overall = sum(1 for r in rows if r["agree"]) / len(rows)
    baseline = max(Counter(r["reference"] for r in rows).values()) / len(rows)
    beats_baseline = overall > baseline
    out.write(f"  [0.95,1.00] {high[1] / high[0]:.1%} "
              f"[{pct(high[2][0])}, {pct(high[2][1])}]\n")
    out.write(f"  [0.00,0.80) {low[1] / low[0]:.1%} "
              f"[{pct(low[2][0])}, {pct(low[2][1])}]\n")
    out.write(f"  overall     {overall:.1%} vs majority-class baseline "
              f"{baseline:.1%}  ({100 * (overall - baseline):+.1f} points)\n")
    usable = rises and separated and beats_baseline
    out.write(f"  -> {'usable' if usable else 'flat'}: intervals "
              f"{'do not overlap' if separated else 'overlap'}, and overall "
              f"{'beats' if beats_baseline else 'does not beat'} the "
              f"majority-class baseline.\n")
    out.write("  The verdict does not replace the table above; both are published.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jev", type=Path, default=RAW / "gate_jev.jsonl")
    parser.add_argument("--reference", type=Path, default=RAW / "gate_reference.jsonl")
    args = parser.parse_args()

    jev = load(args.jev)
    reference = load(args.reference)
    paired = bool(reference)

    rows = []
    for key, record in jev.items():
        row = dict(record)
        if paired and key in reference:
            row["reference"] = reference[key]["prediction"]
            row["agree"] = row["prediction"] == row["reference"]
        elif paired:
            continue
        rows.append(row)

    out = io.StringIO()
    out.write("GATE - agreement with the selected reference model, not correctness\n")
    out.write(f"source: retrospective transcripts, snapshot, NOT reproducible from "
              f"the repository\n")

    unresolved = RAW / "gate_unresolved.jsonl"
    if unresolved.exists():
        states = Counter(json.loads(line)["join_state"] for line
                         in unresolved.read_text(encoding="utf-8").splitlines()
                         if line.strip())
        total = len(rows) + sum(states.values())
        out.write(f"\nObservations: {total}   JOIN_OK {len(rows)}   "
                  + "   ".join(f"{k} {v}" for k, v in states.most_common()) + "\n")

    if not paired:
        out.write("\n** reference model not run yet: distributions only, "
                  "no agreement reported **\n")

    for source in sorted({r["source"] for r in rows}):
        report(out, [r for r in rows if r["source"] == source], f"SOURCE: {source}", paired)
    report(out, rows, "COMBINED", paired)
    if paired:
        stratified(out, rows)
        verdict(out, rows)

    text = out.getvalue()
    # Garantie executable : le rapport ne peut pas laisser croire a une justesse.
    found = [w for w in BANNED if re.search(w, text, re.IGNORECASE)]
    if found:
        raise SystemExit(f"Rapport refuse : mot interdit {found}. "
                         "Ce qui est mesure est un accord, pas une justesse.")
    print(text)


if __name__ == "__main__":
    main()
