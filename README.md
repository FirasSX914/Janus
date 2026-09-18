# Janus

Janus sends each decision to a small model or to a larger one, according to how
confident the small model is. It measures where that line sits on your data
before it routes anything. **Janus ships no default threshold: it measures one.**

[![`janus measure` on 500 Banking77 examples: Jev is 77.8% accurate but 90.7% confident, a 12.9-point gap over 63 observed confidence levels. The sweep picks threshold 0.67, which reaches 80.2% accuracy for $0.1033 -- better than either model alone -- and keeps the median decision at 302ms against 2269ms for the fallback alone.](https://raw.githubusercontent.com/FirasSX914/Janus/main/results/figures/cli_measure.png)](https://github.com/FirasSX914/Janus/blob/main/RESEARCH.md)

<sub>Real output, replayed from the raw JSONL committed in this repository.</sub>

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
  always_primary                 - 100.0%  77.8%     0.0507    296ms
  always_fallback                -   0.0%  78.8%     0.2207   2269ms
  primary_if_confidence_ge    0.67  88.4%  80.2%     0.1033    302ms

VERDICT: ROUTE
  rule      : primary_if_confidence_ge
  threshold : 0.67
  reason    : beats the better single model by +1.4%
  ceiling   : 83.2% (this pair of models, not the task)
```

The full sweep is written to the measurement report.

Three columns decide it. **acc** — routing is more accurate here than either model on
its own. **cost** — it costs less than half of the fallback alone. **p50** — the median
decision still answers in about 300 ms, because most requests never escalate; the
fallback alone takes 2.3 seconds. If you are building anything interactive, that last
column matters before the other two.

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

The run writes one line at a time, flushed and fsynced, and resumes by id. It
refuses to resume a file whose statement has changed rather than mix two prompts.

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
