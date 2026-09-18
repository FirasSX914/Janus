# Janus — reference

Every flag and file format `janus` reads and writes. For what Janus is and how to get a first measurement, see the [README](https://github.com/FirasSX914/Janus#janus).

## `janus measure`

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

## `janus measure --log` — a decision log instead of a dataset

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

## `janus check`

Says whether the policy still applies: same statement, same resolved model
versions. `--offline` validates the file's structure without calling anything.

## `janus explain`

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

## Python API

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

## Providers

| spec | needs | notes |
|---|---|---|
| `typesafe:jev-latest` | `[typesafe]` | exposes a confidence and a full distribution |
| `deepseek:deepseek-v4-pro` | `[deepseek]` | constrained by a strict tool call |
| `anthropic:claude-opus-5` | `[anthropic]` | constrained by structured output |
| `openai_compat:<model>` | `[openai]` | any OpenAI-compatible endpoint, with `base_url` |

Only a provider that reports a confidence can serve as the primary of a
confidence threshold. Register your own with `janus.register`.

## File formats

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

## Layout

```
src/janus/     the package
experiments/   the measurement it is built on, unchanged
tests/         invariants, including that the package still reproduces
               the published numbers from the committed raw JSONL
data/          frozen datasets + provenance
results/       raw JSONL and figures
docs/METHOD.md protocol, measured constraints, related work
```
