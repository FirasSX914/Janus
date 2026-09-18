# Janus

[![PyPI version](https://img.shields.io/pypi/v/janus-decide.svg)](https://pypi.org/project/janus-decide/)
[![License: MIT](https://img.shields.io/pypi/l/janus-decide.svg)](https://github.com/FirasSX914/Janus/blob/main/LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/janus-decide.svg)](https://pypi.org/project/janus-decide/)

Janus sends each decision to a small model or to a larger one, according to how
confident the small model is. It measures where that line sits on your data
before it routes anything. **Janus ships no default threshold: it measures one.**

It measures from either of two inputs:

- **a labelled dataset** — `--dataset`, with a gold label, so the report is
  about how often each model is right;
- **a log of decisions already taken** — `--log`, with a confidence and no gold
  label, so the report is about how often the logged model **agrees with a
  reference model**. There is no ground truth in a log, and Janus refuses to
  print a word that would suggest one.

[![`janus measure` replayed on the two datasets in this repository. On Banking77 it reaches 80.2% at threshold 0.67 -- better than either model alone -- for $0.1033 and a 302ms median decision, against $0.2207 and 2269ms for the fallback alone. On Web of Science no threshold beats the better single model, and the verdict is DO NOT ROUTE.](https://raw.githubusercontent.com/FirasSX914/Janus/main/results/figures/janus_demo.gif)](https://github.com/FirasSX914/Janus/blob/main/RESEARCH.md)

<sub>Real output, replayed from the raw JSONL committed in this repository. No model is called.</sub>

```bash
pip install janus-decide
```

## Quickstart

Five minutes, on your own data. **Janus ships no default threshold: it measures one.**

**1. Install**

```bash
pip install "janus-decide[typesafe,deepseek]"
```

The bare package depends only on numpy; each backend is an extra. DeepSeek speaks the
OpenAI protocol, so `[deepseek]` and `[openai]` pull the same client.

**2. Prepare a labelled JSONL** — one object per line, three fields:

```json
{"id": 0, "text": "I lost my card", "gold_label": "lost_or_stolen_card"}
{"id": 1, "text": "when does my card arrive", "gold_label": "card_arrival"}
```

and a label file naming every class you allow:

```json
{
  "instructions": "Which banking intent does this customer query express?",
  "labels": {
    "lost_or_stolen_card": "The card has been lost or stolen.",
    "card_arrival": "Chasing a card that was already ordered and has not arrived."
  }
}
```

Start with a few hundred labelled rows; larger samples generally give more stable
estimates. Ours were 500.

**3. Measure**

```bash
janus measure \
  --dataset mydata.jsonl --labels mylabels.json \
  --primary typesafe:jev-latest \
  --fallback deepseek:deepseek-v4-pro \
  --out janus.json
```

Try `--sample 20 --seed 1` first: it checks the wiring and the real cost per call
before you spend on the full set. `--budget 2.00` stops the run if the projected cost
goes over. An interrupted run resumes by id without re-paying for a completed call.

**4. Read the table.** This is the real output for the Banking77 data in this
repository:

```
  rule                         thr     cov     acc       cost      p50
  always_primary                 -  100.0%   77.8%     0.0507    296ms
  always_fallback                -    0.0%   78.8%     0.2207   2269ms
  ... 33 more thresholds, written to the report
  primary_if_confidence_ge    0.67   88.4%   80.2%     0.1033    302ms
  ... 30 more thresholds, written to the report

VERDICT: ROUTE
  threshold   :     0.67
  accuracy    :    80.2%    +1.4%  vs best single model
  cost        :  $0.1033     -53%  vs fallback only
  latency p50 :    302ms     -87%  vs fallback only
  escalation  :    11.6%  of traffic
  ceiling     :    83.2%  this pair of models, not the task
```

The full sweep is written to the measurement report.

The verdict compares each number against the baseline the decision is actually
made against. **accuracy** is read against the better of the two models alone.
**cost** and **latency p50** are read against the fallback, since routing exists
to avoid calling it: here that is less than half the money and a median decision
that still answers in about 300 ms, against 2.3 seconds. If you are building
anything interactive, that last line matters before the other two.

`measure` can also conclude **DO NOT ROUTE**, which is what it does on the second
dataset in this repository: no threshold beat the better single model, so the policy
runs that model alone rather than paying for an escalation that buys nothing.

**5. Route from Python**

```python
from janus import Router, question_from_json, resolve

question = question_from_json("mylabels.json")
router = Router.from_file(
    "janus.json",
    primary=resolve("typesafe:jev-1.13.0"),     # the resolved version, not the alias
    fallback=resolve("deepseek:deepseek-v4-pro"),
)

decision = router.decide(input="I lost my card", question=question)
decision.label       # "lost_or_stolen_card"
decision.source      # "primary" | "fallback"
decision.escalated   # False
decision.cost_usd    # from real tokens; None when the rate is unknown
```

Pin the resolved version here rather than an alias: an alias moves when a release
ships, and a threshold measured on one version does not transfer to the next. Aliases
are fine in `janus measure`, which records whatever the API actually answered.

When the models do change under you, `janus check` says so, and `Router` raises
instead of quietly applying a threshold measured on something else. `janus explain`
shows why one input escalated and another did not.

## Use it from an agent

An agent skill ships in this repository. With it installed, a coding agent can be
asked directly:

> Measure my thresholds with Janus.

and will find the decision logs or labelled data already in the project, work out
their format and the classes actually used, assemble the question from what the
project states, estimate the cost, run the measurement, and read the report back.
It will not invent a log, a label, a question or a number: when something needed
is missing, it says which and stops.

### Claude Code plugin

```bash
claude plugin marketplace add FirasSX914/Janus
claude plugin install janus@janus
```

Invoke it explicitly with `/janus:janus-decide`.

### Other agents via skills.sh

```bash
npx skills add FirasSX914/Janus --skill janus-decide
```

Select your agent when prompted. Installation is project-local by default; add
`-g` to install globally.

| Skill | Purpose |
|---|---|
| [janus-decide](https://github.com/FirasSX914/Janus/blob/main/skills/janus-decide/SKILL.md) | Find the project's decision logs or labelled data, measure the threshold, and report coverage, agreement and cost |

The skill describes the commands and flags of the version it ships with and adds
nothing to them. It reads
[SKILL.md](https://github.com/FirasSX914/Janus/blob/main/skills/janus-decide/SKILL.md) as its
instructions; the [raw Markdown](https://raw.githubusercontent.com/FirasSX914/Janus/main/skills/janus-decide/SKILL.md)
can be fetched by an agent that installs skills another way.

## Why measure at all?

The same pipeline was run on two labelled datasets, 500 examples each, and **no
routing parameter carried over**. The optimal threshold moved from 0.67 to 0.37.
The sign of the accuracy gap between the two models reversed. On one dataset
routing beat both models on its own; on the other it matched the better one while
costing 47% more, so the honest answer there was not to route.

A default threshold would therefore be wrong roughly as often as it was right,
which is the whole reason this tool measures instead of assuming.

Full measurement, raw data and limitations: [RESEARCH.md](https://github.com/FirasSX914/Janus/blob/main/RESEARCH.md).

## Reference

### `janus measure`

Runs both models over your labelled data, sweeps every observed confidence level,
and writes a policy plus its report.

| flag | meaning |
|---|---|
| `--dataset` | JSONL with `id`, `text`, `gold_label` |
| `--labels` | JSON label file; `--labels-module` loads a Python module instead, and executes it |
| `--primary`, `--fallback` | `provider:model`, e.g. `typesafe:jev-latest` |
| `--out` | policy path, `janus.json` by default |
| `--raw-dir` | where the raw JSONL goes; written next to `--out` otherwise |
| `--target-accuracy` | pick the cheapest point reaching it; reported as unattainable rather than revised |
| `--max-cost` | discard points above this total |
| `--sample N --seed S` | smoke test on N random rows; both flags are required together |
| `--budget` | stop if the projected cost goes over |
| `--estimate` | print the plan, call nothing |
| `--top N` | show only N routed thresholds around the chosen one; the full sweep still goes to the report |
| `--replay` | re-measure from raw JSONL already recorded; calls nothing |
| `--task` | replay one of the two measurements committed in this repository; implies `--replay` |

`--color auto|always|never` sits on `janus` itself. `auto` follows the terminal,
and `NO_COLOR` wins over `FORCE_COLOR`.

The run writes one line at a time, flushed and fsynced, and resumes by id. It
refuses to resume a file whose statement has changed rather than mix two prompts.

**`--replay`** re-runs the whole measurement offline, from raw JSONL a previous
run wrote. It is how you sweep to a different `--target-accuracy` without paying
for a single new call. The providers it installs raise if they are asked to
answer, so a replay that is missing a row fails loudly instead of quietly
calling a model; and it writes no policy, because nothing new was measured.

```bash
janus measure --replay --task banking77 --top 3   # the demo above, offline
```

`--task` reads the datasets and raw runs committed in the repository, which the
installed package does not carry, so it needs a clone. It says so plainly if the
files are not there. `--replay` on its own works anywhere, on your own
`--dataset` and `--raw-dir`.

### `janus measure --log` — a decision log instead of a dataset

`--dataset` needs a gold label. A decision log has none: it records what a
decision model **answered** and how confident it was, never whether it was
right. So this source measures, in the wording the protocol imposes,
**agreement with the selected reference model, not correctness** — and the
report refuses to print any other word for it.

```bash
janus measure --log decisions.jsonl --labels verdicts.json   --reference deepseek:deepseek-v4-pro   --input-field command --decision-field verdict --confidence-field confidence
```

| flag | meaning |
|---|---|
| `--log` | JSONL of decisions already taken |
| `--reference` | `provider:model` to compare against |
| `--input-field` | field holding what the model saw (default `text`) |
| `--decision-field` | field holding the decision (default `prediction`) |
| `--confidence-field` | field holding the confidence (default `confidence`) |
| `--id-field` | stable id; the line number otherwise |
| `--output-tokens` | output tokens per call, for the estimate (default 638) |
| `--yes` | skip the confirmation before spending |

The defaults are the columns `janus measure` writes itself, so a Janus raw file
replays as a log unchanged. Any other log is read by pointing the flags at the
names it already uses — Janus renames nobody's log.

It prints the cost before calling anything and asks before spending, then gives
the agreement overall, per confidence tier with Wilson intervals, and the
threshold / coverage / cost trade-off. Projected cost is the production one: in
service the reference is called only on what is escalated.

**The stratification by logged decision is not optional.** On 400 real decisions
the two highest confidence tiers held one class and nothing else, so a high
agreement there measured the class imbalance, not the confidence. At constant
class the agreement still rose with confidence — but only the stratified view
could show it, and without it the overall figure beat its own majority-class
baseline by 0.5 points. The method is written up in
[docs/METHOD_GATE.md](https://github.com/FirasSX914/Janus/blob/main/docs/METHOD_GATE.md).

### `janus check`

Says whether the policy still applies: same statement, same resolved model
versions. `--offline` validates the file's structure without calling anything.

### `janus explain`

Shows why one input escalated and another did not.

```
$ janus explain janus.json --input "I lost my card"

Primary: jev-1.13.0
Prediction: lost_or_stolen_card
Confidence: 0.61

Threshold: 0.67
Decision: ESCALATE

Fallback: deepseek-v4-pro
Final label: lost_or_stolen_card
Source: fallback
```

### Python API

```python
from janus import Router, question_from_json, resolve

router = Router.from_file("janus.json", primary=..., fallback=..., on_drift="raise")
decision = router.decide(input="...", question=question)
decisions = router.decide_many(["...", "..."], question=question)
```

`Decision` carries `label`, `source` (`"primary"` or `"fallback"`), `escalated`,
`confidence`, `cost_usd` and `answers`. `confidence` and a provider's
`distribution` are `None` when it exposes neither, and `cost_usd` is `None` rather
than `0.0` when the rate for the returned model is unknown — an unknown must not
disappear into a sum.

`Router` raises `NoPolicyError` without a policy, and `StalePolicyError` when the
statement or the model versions no longer match the measurement. `on_drift` takes
`"raise"` (the default), `"warn"` or `"ignore"`.

### Providers

| spec | needs | notes |
|---|---|---|
| `typesafe:jev-latest` | `[typesafe]` | exposes a confidence and a full distribution |
| `deepseek:deepseek-v4-pro` | `[deepseek]` | constrained by a strict tool call |
| `anthropic:claude-opus-5` | `[anthropic]` | constrained by structured output |
| `openai_compat:<model>` | `[openai]` | any OpenAI-compatible endpoint, with `base_url` |

Only a provider that reports a confidence can serve as the primary of a
confidence threshold. Register your own with `janus.register`.

### File formats

**Dataset** — one JSON object per line:

```json
{"id": 0, "text": "I lost my card", "gold_label": "lost_or_stolen_card"}
```

**Labels** — `labels` maps each class to a description, or is a bare list of
names:

```json
{"instructions": "Which intent is this?", "labels": {"a": "…", "b": "…"}}
```

Two real ones are in the repository: [`data/banking77.labels.json`](https://github.com/FirasSX914/Janus/blob/main/data/banking77.labels.json) (77 classes) and [`data/wos.labels.json`](https://github.com/FirasSX914/Janus/blob/main/data/wos.labels.json) (145). Both are exact exports of what the measurement sent, checked by recomputing the `prompt_hash` recorded in the raw runs.

**`janus.json`** — the report of a measurement, not a preference. It records the
statement's hash, the resolved model versions, the dataset fingerprint, the rule
and threshold, the operating point with its baselines, the oracle ceiling, and
the full table of observed confidence levels so the sweep can be replayed at
another target without a single new call.

### Layout

```
src/janus/     the package
experiments/   the measurement it is built on, unchanged
tests/         invariants, including that the package still reproduces
               the published numbers from the committed raw JSONL
data/          frozen datasets + provenance
results/       raw JSONL and figures
docs/METHOD.md protocol, measured constraints, related work
```

## Research

Two datasets, 500 examples each, protocol frozen before any result, raw JSONL and
figures committed. The headline is that nothing measured on the first dataset
predicted the second.

- [RESEARCH.md](https://github.com/FirasSX914/Janus/blob/main/RESEARCH.md) — results, calibration, ECE and
  Brier, agreement between the models, limitations, related work.
- [docs/METHOD.md](https://github.com/FirasSX914/Janus/blob/main/docs/METHOD.md) — the protocol, what was
  fixed before each run, and the constraints measured on the APIs themselves.
- [experiments/](https://github.com/FirasSX914/Janus/tree/main/experiments) — the scripts that produced it.

## License

MIT — see [LICENSE](https://github.com/FirasSX914/Janus/blob/main/LICENSE).

Banking77 is distributed under CC BY 4.0; see [`data/README.md`](https://github.com/FirasSX914/Janus/blob/main/data/README.md) for
provenance and citation.
