"""La CLI `janus` : trois sous-commandes.

    janus measure   mesure une politique sur vos donnees, ecrit janus.json
    janus check     la politique s'applique-t-elle encore aux modeles actuels ?
    janus explain   pourquoi cette entree a-t-elle escalade, ou non ?

`measure` ecrit son rapport a chaque passage : il n'y a pas de sous-commande
`report` a oublier de lancer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import labels as labels_mod
from .measure import BudgetExceeded, measure
from .policy import Policy, PolicyError
from .providers.registry import PROVIDERS, resolve
from .router import Router
from .types import Question


# --------------------------------------------------------------------- utils
def _load_question(args) -> Question:
    if args.labels_module:
        return labels_mod.from_module(Path(args.labels_module))
    if not args.labels:
        raise SystemExit("one of --labels or --labels-module is required")
    return labels_mod.from_json(Path(args.labels))


def _fingerprint(path: Path) -> dict:
    return {"dataset": path.name,
            "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fmt(value: float | None, suffix: str = "") -> str:
    return "unknown" if value is None or value != value else f"{value:.4f}{suffix}"


# ------------------------------------------------------------------- measure
def cmd_measure(args) -> int:
    question = _load_question(args)
    examples = [json.loads(line) for line
                in Path(args.dataset).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    out = Path(args.out)
    artifacts = Path(args.raw_dir) if args.raw_dir else out.with_suffix("") .parent / f"{out.stem}.artifacts"

    print(f"dataset   : {args.dataset}, {len(examples)} rows")
    print(f"question  : {len(question)} classes")
    print(f"primary   : {args.primary}")
    print(f"fallback  : {args.fallback}")
    print(f"artifacts : {artifacts}")

    if args.estimate:
        print("\n--estimate: no call is made. Run without it to measure.")
        return 0

    try:
        result = measure(
            examples=examples, question=question,
            primary=resolve(args.primary), fallback=resolve(args.fallback),
            artifacts=artifacts, target_accuracy=args.target_accuracy,
            max_cost=args.max_cost, budget=args.budget,
            sample=args.sample, seed=args.seed,
            dataset_fingerprint=_fingerprint(Path(args.dataset)),
        )
    except BudgetExceeded as error:
        print(f"\nSTOPPED: {error}", file=sys.stderr)
        return 2

    policy = result.policy
    policy.write(out)
    _print_report(result)
    print(f"\npolicy written to {out}")
    print(f"raw JSONL kept in {artifacts} - a policy should be auditable.")
    return 0


def _print_report(result) -> None:
    policy, report = result.policy, result.calibration
    print("\n" + "=" * 68)
    print("CALIBRATION OF THE PRIMARY")
    print("=" * 68)
    print(f"  accuracy          : {report.accuracy:.1%} "
          f"[{report.accuracy_ci[0]:.1%}, {report.accuracy_ci[1]:.1%}]")
    print(f"  mean confidence   : {report.mean_confidence:.1%}")
    print(f"  gap               : {report.mean_confidence - report.accuracy:+.1%}")
    print(f"  ECE by level      : {report.ece_by_level:.4f} "
          f"[{report.ece_by_level_ci[0]:.4f}, {report.ece_by_level_ci[1]:.4f}]")
    print(f"  ECE 10 equal bins : {report.ece_equal_width:.4f}")
    print(f"  Brier             : {report.brier:.4f} "
          f"[{report.brier_ci[0]:.4f}, {report.brier_ci[1]:.4f}]")
    print(f"  observed levels   : {len(report.levels)}")

    print("\n" + "=" * 68)
    print("OPERATING POINTS, one per observed confidence level")
    print("=" * 68)
    print(f"  {'rule':<26} {'thr':>5} {'cov':>7} {'acc':>7} {'cost':>10} {'p50':>8}")
    for point in result.sweep:
        threshold = "-" if point.threshold is None else f"{point.threshold:.2f}"
        print(f"  {point.rule:<26} {threshold:>5} {point.coverage:>6.1%} "
              f"{point.accuracy:>6.1%} {_fmt(point.cost_total):>10} "
              f"{point.latency_p50_ms:>6.0f}ms")

    print("\n" + "=" * 68)
    print(f"VERDICT: {result.verdict.upper().replace('_', ' ')}")
    print("=" * 68)
    print(f"  rule      : {policy.rule}")
    print(f"  threshold : {policy.threshold if policy.threshold is not None else '-'}")
    print(f"  reason    : {policy.reason}")
    baselines = policy.operating_point.get("baselines", {})
    print(f"  baselines : primary only {baselines.get('primary_only', float('nan')):.1%}, "
          f"fallback only {baselines.get('fallback_only', float('nan')):.1%}")
    print(f"  ceiling   : {policy.ceiling.get('oracle_accuracy', float('nan')):.1%} "
          f"(this pair of models, not the task)")
    if not policy.route:
        print("\n  Routing was measured and did not pay here. That is a result, not a\n"
              "  failure: the policy runs the better single model instead.")


# --------------------------------------------------------------------- check
def cmd_check(args) -> int:
    policy = Policy.read(Path(args.policy))
    print(f"policy    : {args.policy}")
    print(f"measured  : {policy.created_at} on {policy.measured_on.get('rows', '?')} rows")
    print(f"rule      : {policy.rule}"
          + (f" @ {policy.threshold}" if policy.threshold is not None else ""))
    print(f"primary   : {policy.primary.provider}:{policy.primary.sent} "
          f"-> {policy.primary.resolved}")
    if policy.fallback:
        print(f"fallback  : {policy.fallback.provider}:{policy.fallback.sent} "
              f"-> {policy.fallback.resolved}")

    if args.offline:
        print("\n--offline: structure is valid; model versions not checked.")
        return 0

    question = _load_question(args) if (args.labels or args.labels_module) else None
    if question is not None:
        try:
            policy.check_question(question)
            print("\nquestion  : matches the measured statement")
        except PolicyError as error:
            print(f"\nSTALE: {error}", file=sys.stderr)
            return 1

    drift: list[str] = []
    for role, ref in (("primary", policy.primary), ("fallback", policy.fallback)):
        if ref is None:
            continue
        provider = resolve(f"{ref.provider}:{ref.sent}")
        answer = provider.ask("ping", question or Question(
            instructions="Which label applies?", criteria={"a": "", "b": ""}))
        drift += policy.check_models(**{f"{role}_model_id": answer.model_id})

    if drift:
        print("\nSTALE:", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        print("  Re-run `janus measure`.", file=sys.stderr)
        return 1
    print("models    : still the versions this policy was measured on")
    return 0


# ------------------------------------------------------------------- explain
def cmd_explain(args) -> int:
    policy = Policy.read(Path(args.policy))
    question = _load_question(args)
    router = Router(
        policy,
        primary=resolve(f"{policy.primary.provider}:{policy.primary.sent}"),
        fallback=(resolve(f"{policy.fallback.provider}:{policy.fallback.sent}")
                  if policy.fallback else None),
        on_drift=args.on_drift,
    )
    decision = router.decide(args.input, question)
    primary = decision.answers.get("primary")
    fallback = decision.answers.get("fallback")

    print()
    if primary is not None:
        print(f"Primary: {primary.model_id}")
        print(f"Prediction: {primary.label}")
        print(f"Confidence: {primary.confidence if primary.confidence is not None else '-'}")
        print()
    if policy.threshold is not None:
        print(f"Threshold: {policy.threshold}")
    else:
        print(f"Rule: {policy.rule} (measured: routing did not pay)")
    print(f"Decision: {'ESCALATE' if decision.escalated else 'KEEP PRIMARY'}")
    if fallback is not None:
        print()
        print(f"Fallback: {fallback.model_id}")
    print()
    print(f"Final label: {decision.label}")
    print(f"Source: {decision.source}")
    print(f"Cost: {_fmt(decision.cost_usd, ' USD')}")
    return 0


# ---------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="janus",
        description="Measure a routing policy on your data, then run it.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_labels(sub):
        sub.add_argument("--labels", help="JSON file: {\"labels\": {...}}")
        sub.add_argument("--labels-module",
                         help="Python module exposing CRITERIA. Executes the file; "
                              "ask for it explicitly.")

    m = subparsers.add_parser("measure", help="measure a policy and write janus.json")
    m.add_argument("--dataset", required=True, help="JSONL: id, text, gold_label")
    add_labels(m)
    m.add_argument("--primary", required=True,
                   help=f"provider:model, one of {', '.join(PROVIDERS)}")
    m.add_argument("--fallback", required=True, help="provider:model")
    m.add_argument("--out", default="janus.json")
    m.add_argument("--raw-dir", default=None,
                   help="override where the raw JSONL goes; written next to --out otherwise")
    m.add_argument("--target-accuracy", type=float, default=None)
    m.add_argument("--max-cost", type=float, default=None)
    m.add_argument("--sample", type=int, default=None,
                   help="smoke test on N random rows; requires --seed")
    m.add_argument("--seed", type=int, default=None)
    m.add_argument("--budget", type=float, default=None,
                   help="stop if the projected cost exceeds this")
    m.add_argument("--estimate", action="store_true", help="print the plan, call nothing")
    m.set_defaults(func=cmd_measure)

    c = subparsers.add_parser("check", help="does this policy still apply?")
    c.add_argument("policy", nargs="?", default="janus.json")
    add_labels(c)
    c.add_argument("--offline", action="store_true", help="validate structure only")
    c.set_defaults(func=cmd_check)

    e = subparsers.add_parser("explain", help="why did this input escalate, or not?")
    e.add_argument("policy", nargs="?", default="janus.json")
    e.add_argument("--input", required=True)
    add_labels(e)
    e.add_argument("--on-drift", choices=("raise", "warn", "ignore"), default="warn")
    e.set_defaults(func=cmd_explain)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PolicyError as error:
        print(f"\n{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
