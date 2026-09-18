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
import os
import sys
from pathlib import Path

from . import cost as cost_mod
from . import labels as labels_mod
from .measure import BudgetExceeded, measure
from .policy import Policy, PolicyError
from .providers.registry import PROVIDERS, resolve
from .agreement import FORMULA, MIN_TIER, analyse, guard
from .logmeasure import ask_reference, estimate
from .logs import LogFormatError, LogSpec, observed_decisions, read_log
from .replay import OfflineProvider, TASKS, resolve_task, stage_artifacts
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


# ------------------------------------------------------------------- couleur
#: Couleur seulement sur un vrai terminal, et jamais si NO_COLOR est pose.
#: Rediriger la sortie dans un fichier doit rendre du texte, pas des sequences
#: d'echappement : un rapport se relit et se diffe.
#: NO_COLOR l'emporte sur FORCE_COLOR : desactiver doit toujours gagner.
_COLOR = (os.environ.get("NO_COLOR") is None
          and os.environ.get("TERM") != "dumb"
          and (os.environ.get("FORCE_COLOR") not in (None, "", "0")
               or sys.stdout.isatty()))


def set_color(mode: str) -> None:
    """auto | always | never. `auto` suit le terminal et NO_COLOR."""
    global _COLOR
    if mode == "always":
        _COLOR = True
    elif mode == "never":
        _COLOR = False


_CODES = {"dim": "2", "bold": "1", "green": "32", "red": "31",
          "white": "97", "highlight": "1;97"}


def _c(text: str, style: str) -> str:
    return f"\033[{_CODES[style]}m{text}\033[0m" if _COLOR and style in _CODES else text


def _fmt(value: float | None, suffix: str = "") -> str:
    return "unknown" if value is None or value != value else f"{value:.4f}{suffix}"


def _delta(value: float | None, base: float | None, *, lower_is_better: bool) -> str:
    """Ecart relatif a une baseline, en pourcentage signe et colore.

    `lower_is_better` dit dans quel sens va le gain : pour un cout ou une
    latence, baisser est un gain ; pour une accuracy, monter en est un. Sans
    cette distinction la couleur dirait l'inverse de ce qu'on lit.

    Rendu "n/a" plutot que 0 quand la baseline manque ou vaut zero : un ecart
    qu'on ne peut pas calculer ne doit pas s'afficher comme un ecart nul.
    """
    if value is None or base in (None, 0) or value != value or base != base:
        return f"{'n/a':>7}"
    ratio = (value - base) / base
    gain = (ratio < 0) if lower_is_better else (ratio > 0)
    return _c(f"{ratio:+.0%}".rjust(7), "green" if gain else "red")


def _points(value: float, base: float, *, lower_is_better: bool = False) -> str:
    """Ecart en points de pourcentage, colore de la meme facon."""
    difference = value - base
    gain = (difference < 0) if lower_is_better else (difference > 0)
    return _c(f"{difference:+.1%}".rjust(7), "green" if gain else "red")


# ------------------------------------------------------------------- measure
def cmd_measure(args) -> int:
    if args.log:
        return cmd_measure_log(args)
    staged = None
    if args.task:
        # Raccourci vers les deux mesures commitees dans le depot. Il implique
        # --replay : ces JSONL sont deja payes, les rejouer ne coute rien.
        paths = resolve_task(args.task, Path.cwd())
        args.dataset = paths["dataset"].relative_to(Path.cwd()).as_posix()
        args.labels = args.labels or str(paths["labels"])
        args.primary = args.primary or "typesafe:jev-latest"
        args.fallback = args.fallback or "deepseek:deepseek-v4-pro"
        args.replay = True
        staged = stage_artifacts(paths["primary"], paths["fallback"])
    for name in ("dataset", "primary", "fallback"):
        if not getattr(args, name):
            raise SystemExit(f"--{name} is required (or use --task)")

    question = _load_question(args)
    examples = [json.loads(line) for line
                in Path(args.dataset).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    out = Path(args.out)
    artifacts = (staged if staged is not None else
                 Path(args.raw_dir) if args.raw_dir else
                 out.with_suffix("").parent / f"{out.stem}.artifacts")

    print(f"dataset   : {args.dataset}, {len(examples)} rows")
    print(f"question  : {len(question)} classes")
    print(f"primary   : {args.primary}")
    print(f"fallback  : {args.fallback}")
    print(_c("replay    : recorded JSONL only, no model is called", "dim")
          if args.replay else f"artifacts : {artifacts}")

    if args.estimate:
        print("\n--estimate: no call is made. Run without it to measure.")
        return 0

    try:
        result = measure(
            examples=examples, question=question,
            primary=(OfflineProvider("typesafe", args.primary.split(":", 1)[-1])
                     if args.replay else resolve(args.primary)),
            fallback=(OfflineProvider("fallback", args.fallback.split(":", 1)[-1])
                      if args.replay else resolve(args.fallback)),
            artifacts=artifacts, target_accuracy=args.target_accuracy,
            max_cost=args.max_cost, budget=args.budget,
            sample=args.sample, seed=args.seed,
            dataset_fingerprint=_fingerprint(Path(args.dataset)),
        )
    except BudgetExceeded as error:
        print(f"\nSTOPPED: {error}", file=sys.stderr)
        return 2

    policy = result.policy
    _print_report(result, top=args.top)
    if args.replay:
        # Rejouer ne produit pas de politique : rien de neuf n'a ete mesure, et
        # ecraser janus.json depuis une relecture serait trompeur.
        print(_c("\nreplayed from recorded JSONL; nothing called, nothing written.",
                 "dim"))
        return 0
    policy.write(out)
    print(f"\npolicy written to {out}")
    print(f"raw JSONL kept in {artifacts} - a policy should be auditable.")
    return 0


def _rates(model: str) -> tuple[float, float] | None:
    """(entree, sortie) en $/Mtok pour une estimation AVANT appel.

    Le tarif en cache miss est retenu pour les modeles a cache : une estimation
    doit majorer, pas flatter.
    """
    if model in cost_mod.FLAT_PRICING:
        return cost_mod.FLAT_PRICING[model]
    if model in cost_mod.CACHED_PRICING:
        _hit, miss, out = cost_mod.CACHED_PRICING[model]
        return miss, out
    return None


def cmd_measure_log(args) -> int:
    """Mesurer l'accord entre un journal de decisions et un modele de reference.

    Il n'y a pas d'etiquette d'or ici, donc pas de justesse : le rapport parle
    d'accord, et `guard()` refuse de l'imprimer s'il parle d'autre chose.
    """
    if not args.reference:
        raise SystemExit("--reference is required with --log: the agreement is "
                         "measured against a model, and it has to be named")
    spec = LogSpec(input_field=args.input_field,
                   decision_field=args.decision_field,
                   confidence_field=args.confidence_field,
                   id_field=args.id_field)
    # La question d'abord : un --labels manquant est une erreur plus
    # fondamentale qu'un nom de champ, et doit se dire en premier.
    question = _load_question(args)
    rows = read_log(Path(args.log), spec)

    seen = observed_decisions(rows)
    unknown = [d for d in seen if d not in question.criteria]
    if unknown:
        raise SystemExit(
            f"the log holds decisions the question does not offer: {unknown}\n"
            f"  question offers: {sorted(question.criteria)}\n"
            "The reference must be asked the same closed question the logged "
            "model answered, otherwise the two are not comparable.")

    artifacts = Path(args.raw_dir) if args.raw_dir else Path(args.out).with_suffix("").parent / "agreement.artifacts"
    print(f"log        : {args.log}, {len(rows)} decisions")
    print(f"fields     : {spec.describe()}")
    # Un journal a 77 classes deverserait la liste entiere sur une ligne. On
    # montre les plus frequentes et on compte le reste.
    counts = sorted(((d, sum(1 for r in rows if r.decision == d)) for d in seen),
                    key=lambda kv: -kv[1])
    head = "  ".join(f"{d} {n}" for d, n in counts[:6])
    if len(counts) > 6:
        head += _c(f"  (+{len(counts) - 6} more classes)", "dim")
    print(f"decisions  : {head}")
    print(f"reference  : {args.reference}")
    print(f"question   : {len(question)} classes")
    print(f"artifacts  : {artifacts}")

    model = args.reference.split(":", 1)[-1]
    rates = _rates(model)
    if rates is None:
        print(_c(f"\nNo price on file for {model}: the run cannot be estimated, "
                 "and its cost will be reported as unknown rather than as zero.", "dim"))
        tokens = None
    else:
        tokens, projected = estimate(rows, question, usd_per_mtok_in=rates[0],
                                     usd_per_mtok_out=rates[1],
                                     output_tokens=args.output_tokens)
        print(f"\nestimate   : ~{tokens:,} input tokens, "
              f"{args.output_tokens} output tokens per decision")
        print(f"             ${projected:.4f} at {model} list price, no cache")
        if args.budget is not None and projected > args.budget:
            raise SystemExit(f"refusing to start: ${projected:.4f} is over the "
                             f"--budget ${args.budget:.2f}")

    if args.estimate:
        print("\n--estimate: no call is made. Run without it to measure.")
        return 0
    if not args.yes:
        # Une mesure d'accord appelle la reference sur CHAQUE ligne. On ne
        # depense pas sans le dire.
        try:
            answer = input("\nRun the reference on every decision? [y/N] ").strip().lower()
        except EOFError:
            raise SystemExit("not a terminal: pass --yes to confirm the spend")
        if answer not in ("y", "yes"):
            return 1

    try:
        verdicts = ask_reference(rows, question, resolve(args.reference), artifacts,
                                 budget=args.budget)
    except BudgetExceeded as error:
        print(f"\nSTOPPED: {error}", file=sys.stderr)
        return 2
    if not verdicts:
        raise SystemExit("no decision was answered by the reference")

    print(guard(_render_agreement(analyse(verdicts), len(rows))))
    print(_c(f"raw JSONL kept in {artifacts} - an agreement should be auditable.", "dim"))
    return 0


def _render_agreement(report, n_log: int) -> str:
    out = ["", "=" * 68, "AGREEMENT WITH THE REFERENCE", "=" * 68,
           f"  {FORMULA}."]
    if report.n != n_log:
        out.append(_c(f"  measured on {report.n} of {n_log} logged decisions "
                      "(the run stopped early)", "dim"))

    out += ["", f"  logged    : " + "   ".join(
        f"{k} {v} ({v / report.n:.1%})" for k, v in
        sorted(report.decisions.items(), key=lambda kv: -kv[1]))]
    out.append(f"  reference : " + "   ".join(
        f"{k} {v} ({v / report.n:.1%})" for k, v in
        sorted(report.reference_decisions.items(), key=lambda kv: -kv[1])))
    out.append(_c(f"  majority-class baseline: {report.majority_baseline:.1%}"
                  "  <- what a constant answer would reach", "dim"))

    lo, hi = report.overall_interval
    beats = report.overall > report.majority_baseline
    out += ["", f"  overall   : {report.overall:.1%}  [{lo:.1%}, {hi:.1%}]  "
                + _c(f"{100 * (report.overall - report.majority_baseline):+.1f} points "
                     "vs baseline", "green" if beats else "red")]

    out += ["", "=" * 68, "BY CONFIDENCE TIER", "=" * 68,
            _c(f"  {'tier':<14} {'n':>5} {'share':>7} {'agreement':>10}"
               f"  {'Wilson 95%':>18}", "dim")]
    for row in report.tiers:
        line = (f"  {row.label:<14} {row.n:>5} {row.n / report.n:>7.1%} "
                f"{row.rate:>10.1%}  [{row.interval[0]:>7.1%}, {row.interval[1]:>7.1%}]"
                if row.n else f"  {row.label:<14} {row.n:>5}")
        if row.n and not row.interpreted:
            line += _c(f"  (n<{MIN_TIER}, not interpreted)", "dim")
        out.append(line)

    out += ["", "=" * 68, "STRATIFIED BY LOGGED DECISION  (not optional)", "=" * 68,
            _c("  Confidence and the logged class are confounded whenever the high\n"
               "  tiers hold one class only. At constant class, confidence has to keep\n"
               "  predicting agreement or it carries nothing of its own.", "dim")]
    for label, tiers in report.stratified.items():
        total = sum(t.n for t in tiers)
        out.append(f"\n  logged {label}  n={total}")
        for row in tiers:
            if not row.n:
                out.append(f"    {row.label:<14} {row.n:>5}")
                continue
            line = (f"    {row.label:<14} {row.n:>5} {row.rate:>10.1%}"
                    f"  [{row.interval[0]:>7.1%}, {row.interval[1]:>7.1%}]")
            if not row.interpreted:
                line += _c(f"  (n<{MIN_TIER}, not interpreted)", "dim")
            out.append(line)

    out += ["", "=" * 68, "THRESHOLD, COVERAGE, COST", "=" * 68,
            _c(f"  {'thr':>5} {'coverage':>9} {'escalated':>10} "
               f"{'agreement kept':>15} {'projected cost':>15}", "dim")]
    shown = [p for p in report.points if p.threshold is None][:1]
    levels = [p for p in report.points if p.threshold is not None]
    step = max(1, len(levels) // 8)
    shown += levels[::step]
    for point in shown:
        thr = "-" if point.threshold is None else f"{point.threshold:.2f}"
        money = "unknown" if point.projected_cost is None else f"${point.projected_cost:.4f}"
        kept = "n/a" if point.n_kept == 0 else f"{point.agreement_kept:.1%}"
        out.append(f"  {thr:>5} {point.coverage:>9.1%} {point.escalation_rate:>10.1%} "
                   f"{kept:>15} {money:>15}")
    out.append(_c("  Projected cost is production, not measurement: in service the\n"
                  "  reference is called only on what is escalated.", "dim"))
    if report.reference_cost_total is not None:
        out.append(f"  This measurement called it on all {report.n}: "
                   f"${report.reference_cost_total:.4f}.")

    out += ["", f"  divergences at confidence >= 0.95: {len(report.divergences)}"]
    for v in sorted(report.divergences, key=lambda v: -v.confidence):
        out.append(f"    {v.confidence:.2f}  logged={v.decision:<10} "
                   f"reference={v.reference}")
    for caveat in report.caveats:
        out.append(_c(f"  note: {caveat}", "dim"))
    return "\n".join(out)


def _print_report(result, top: int | None = None) -> None:
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
    print(_c(f"  {'rule':<26} {'thr':>5} {'cov':>7} {'acc':>7} "
             f"{'cost':>10} {'p50':>8}", "dim"))

    def render(point, style: str = "white") -> str:
        threshold = "-" if point.threshold is None else f"{point.threshold:.2f}"
        # Les largeurs de l'en-tete et des valeurs sont les memes, sinon les
        # colonnes se decalent d'un caractere et le tableau ment a l'oeil.
        return _c(f"  {point.rule:<26} {threshold:>5} {point.coverage:>7.1%} "
                  f"{point.accuracy:>7.1%} {_fmt(point.cost_total):>10} "
                  f"{point.latency_p50_ms:>6.0f}ms", style)

    routed = [p for p in result.sweep if p.threshold is not None]
    # Le point qui porte la decision. Quand rien n'est route, c'est le meilleur
    # cas POUR le routage -- meilleure accuracy, et a egalite celui qui escalade
    # le plus -- car c'est lui qui documente ce que router aurait coute. Un seuil
    # a 100 % de couverture n'escalade rien : c'est always_primary sous un autre
    # nom, il ne dit rien de la decision.
    chosen = next((i for i, p in enumerate(routed)
                   if p.threshold == policy.threshold), None)
    if chosen is None and routed:
        live = [i for i, p in enumerate(routed) if 0.0 < p.coverage < 1.0] \
            or list(range(len(routed)))
        chosen = max(live, key=lambda i: (routed[i].accuracy, -routed[i].coverage))

    shown = set(range(len(routed)))
    if top is not None and top < len(routed):
        half = (top - 1) // 2
        start = max(0, min(chosen - half, len(routed) - top))
        shown = set(range(start, start + top))

    elided = 0
    for point in result.sweep:
        if point.threshold is None:          # always_primary / always_fallback
            print(render(point))
            continue
        index = routed.index(point)
        if index in shown:
            if elided:
                print(_c(f"  ... {elided} more thresholds, written to the report", "dim"))
                elided = 0
            print(render(point, "highlight" if index == chosen else "white"))
        else:
            elided += 1
    if elided:
        print(_c(f"  ... {elided} more thresholds, written to the report", "dim"))

    print("\n" + "=" * 68)
    verdict = result.verdict.upper().replace("_", " ")
    print(_c(f"VERDICT: {verdict}", "green" if policy.route else "red"))
    print("=" * 68)

    singles = {p.rule: p for p in result.sweep if p.threshold is None}
    primary_only = singles.get("always_primary")
    fallback_only = singles.get("always_fallback")

    def row(label: str, value: str, delta: str = "", against: str = "") -> None:
        """Une ligne = une info. Colonnes fixes : libelle, valeur, ecart."""
        line = f"  {label:<12}: {value:>8}"
        if delta:
            line += f"  {delta}  {_c(against, 'dim')}"
        elif against:
            line += f"  {_c(against, 'dim')}"
        print(line)

    if policy.route:
        point = next(p for p in routed if p.threshold == policy.threshold)
        # On route : la baseline qui compte est le modele qu'on evite d'appeler.
        base, label = fallback_only, "vs fallback only"
        best_single = max(primary_only.accuracy, fallback_only.accuracy)
        row("threshold", f"{policy.threshold:.2f}")
        row("accuracy", f"{point.accuracy:.1%}",
            _points(point.accuracy, best_single), "vs best single model")
    else:
        point = routed[chosen] if routed else None
        # On ne route pas : la baseline est le modele qui tourne seul.
        base, label = primary_only, "vs always_primary"
        if point is not None:
            row("best routed", f"{point.threshold:.2f}", "", "would be the best case")
            row("accuracy", f"{point.accuracy:.1%}",
                _points(point.accuracy, primary_only.accuracy), label)

    if point is not None and base is not None:
        money = "unknown" if point.cost_total is None else f"${point.cost_total:.4f}"
        row("cost", money,
            _delta(point.cost_total, base.cost_total, lower_is_better=True), label)
        if policy.route:
            row("latency p50", f"{point.latency_p50_ms:.0f}ms",
                _delta(point.latency_p50_ms, base.latency_p50_ms,
                       lower_is_better=True), label)
            row("escalation", f"{1 - point.coverage:.1%}", "", "of traffic")

    row("ceiling", f"{policy.ceiling.get('oracle_accuracy', float('nan')):.1%}",
        "", "this pair of models, not the task")
    if not policy.route:
        print("\n  " + _c("-> routing costs more for the same accuracy.", "red"))
        print(_c("  Routing was measured and did not pay here. That is a result,\n"
                 "  not a failure: the policy runs the better single model instead.",
                 "dim"))


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
    parser.add_argument("--color", choices=("auto", "always", "never"),
                        default="auto",
                        help="colourise the report; auto follows the terminal "
                             "and NO_COLOR")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_labels(sub):
        sub.add_argument("--labels", help="JSON file: {\"labels\": {...}}")
        sub.add_argument("--labels-module",
                         help="Python module exposing CRITERIA. Executes the file; "
                              "ask for it explicitly.")

    m = subparsers.add_parser("measure", help="measure a policy and write janus.json")
    m.add_argument("--dataset", help="JSONL: id, text, gold_label")
    add_labels(m)
    m.add_argument("--primary",
                   help=f"provider:model, one of {', '.join(PROVIDERS)}")
    m.add_argument("--fallback", help="provider:model")
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
    m.add_argument("--log",
                   help="JSONL of decisions already taken, with their confidence "
                        "and no gold label; measures agreement, not correctness")
    m.add_argument("--reference", help="provider:model to compare the log against")
    m.add_argument("--input-field", default="text",
                   help="log field holding what the model saw (default: text)")
    m.add_argument("--decision-field", default="prediction",
                   help="log field holding the decision taken (default: prediction)")
    m.add_argument("--confidence-field", default="confidence",
                   help="log field holding the confidence (default: confidence)")
    m.add_argument("--id-field", default=None,
                   help="log field holding a stable id; the line number otherwise")
    m.add_argument("--output-tokens", type=int, default=638,
                   help="output tokens per reference call, for the estimate; 638 is "
                        "the measured mean for a reasoning model, not a guess")
    m.add_argument("--yes", action="store_true",
                   help="skip the confirmation before spending")
    m.add_argument("--replay", action="store_true",
                   help="re-measure from recorded raw JSONL; calls nothing, "
                        "fails loudly if a row is missing")
    m.add_argument("--task", choices=sorted(TASKS), default=None,
                   help="replay a measurement committed in the Janus "
                        "repository; implies --replay")
    m.add_argument("--top", type=int, default=None,
                   help="show only N routed thresholds around the chosen one; "
                        "the full sweep always goes to the report")
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
    set_color(args.color)
    try:
        return args.func(args)
    except (PolicyError, LogFormatError) as error:
        # Un format de journal qui ne colle pas est une erreur d'usage, pas un
        # plantage : elle se lit, elle ne se deroule pas.
        print(f"\n{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
