---
name: janus-decide
license: MIT
description: >
  Measure where a confidence threshold belongs before routing decisions between
  a small model and a larger one, using the janus-decide package. Janus ships no
  default threshold: it measures one on the project's own data, and it can
  conclude that routing does not pay. Use when asked to measure thresholds,
  calibrate or audit a router, decide whether escalating to a bigger model is
  worth the money, or check whether a confidence signal carries anything. Works
  from a labelled dataset with gold labels, or from a log of decisions already
  taken, which has none. Never invent a log, a label, a question, a threshold or
  a result: when the project does not hold what a measurement needs, say exactly
  what is missing.
---

# Measure thresholds with Janus

`janus-decide` answers one question: **at what confidence can the small model
decide alone, rather than paying a larger one?** It answers it by measuring, on
the data in front of it. It has no default threshold to offer and will say so.

Install it when it is absent: `pip install janus-decide`, plus the extras for the
providers in play — `janus-decide[typesafe,deepseek,anthropic,openai]`.

## The rule that governs everything else

**Nothing in a Janus run may be invented.** Not a log file, not a label, not the
question text, not a class, not a number in the report. Every input comes from
the project or from the user. When something is missing, name it and stop; a
fabricated input produces a real-looking threshold that means nothing, and that
is worse than no answer.

## Two sources, and they measure different things

| | `--dataset` | `--log` |
|---|---|---|
| what it holds | `id`, `text`, `gold_label` | decisions already taken, with a confidence |
| ground truth | yes, the gold label | **none** |
| what is measured | how often each model is right | **agreement with a reference model** |
| verdict | ROUTE / DO NOT ROUTE, writes `janus.json` | threshold / coverage / cost trade-off |

With `--log` there is no ground truth and therefore no correctness. The reference
model is a second opinion, not an oracle. Janus enforces this: its report
refuses to print `accuracy`, `correct`, `ground truth` or `error rate`. Do not reintroduce
those words when explaining the result. The wording to use, unbroken:
**agreement with the selected reference model, not correctness**.

## Step 1 — find out what the project actually has

Look before asking, and look before assuming. Search the repository for JSONL
holding a confidence next to a decision:

```bash
rg -l '"confidence"' --glob '*.jsonl' .
rg -l 'gold_label|"label"' --glob '*.jsonl' .
fd -e jsonl . | head -50
```

Then read **one line** of each candidate and list its keys. That single line
settles the source and every flag:

```bash
head -1 path/to/file.jsonl | python -m json.tool
```

- A `gold_label` (or an equivalent truth column) → `--dataset`.
- A decision plus a confidence and no truth column → `--log`.
- Neither → this file is not a Janus input. Say so and keep looking.

Also read the code that writes the file. It names the classes and often carries
the prompt the decision model was given — both are needed below, and both must
come from the project rather than from guesswork.

## Step 2 — map the fields

`--dataset` expects the three column names exactly: `id`, `text`, `gold_label`.

`--log` renames nothing. Point the flags at the names the log already uses:

```bash
janus measure --log decisions.jsonl \
  --input-field command --decision-field verdict --confidence-field confidence \
  --id-field ts
```

Defaults are `text` / `prediction` / `confidence`, which are the columns
`janus measure` writes itself, so a Janus raw file replays as a log with no flags
at all. Anything else needs the flags. Janus refuses a log whose confidence is
outside `[0, 1]`, whose ids repeat, or whose field is absent — the error names
the field and lists the ones present; read it rather than guessing again.

## Step 3 — the classes, and the labels file

The classes are the ones **actually present in the log or dataset**, not the ones
that seem plausible. Count them from the file:

```bash
python - <<'PY'
import json, collections
rows = [json.loads(l) for l in open("decisions.jsonl", encoding="utf-8") if l.strip()]
print(collections.Counter(r["verdict"] for r in rows))
PY
```

Janus needs a labels file, because the reference has to be asked the **same
closed question** the logged model answered. It looks like this:

```json
{
  "instructions": "May an AI coding agent execute this shell command?",
  "labels": {
    "APPROVE": "Safe to run without asking.",
    "DENY": "Must not run.",
    "ESCALATE": "A human must decide."
  }
}
```

A bare list is also accepted: `{"labels": ["APPROVE", "DENY", "ESCALATE"]}`, which
leaves the class names to carry the meaning alone.

**Build this file only from what the project already states.** The class names
come from the data. The instruction text and the per-class criteria come from the
code, prompt, config or docs that produced the decisions — search for the prompt
that was actually sent. If the project already ships such a file, use it.

If the project does not state the question anywhere, **do not compose one**. The
threshold would be measured against a question the logged model was never asked.
Report that the instruction text is missing, show where you looked, and ask for
it.

`--labels-module` loads a Python module exposing `CRITERIA` instead. It executes
the file, so only use it when the user asks for it by name.

## Step 4 — estimate before spending

`janus measure` calls real models and costs real money. **Always run `--estimate`
first.** It prints the plan and calls nothing:

```bash
janus measure --log decisions.jsonl --labels question.json \
  --reference deepseek:deepseek-v4-pro --estimate
```

Report the figure to the user before running for real. `--budget N` refuses to
start above `N` and stops mid-run if the cumulative cost passes it. `--sample N
--seed S` measures a random subset first; both flags are required together,
because a draw without a documented seed is not reproducible.

With `--log`, Janus asks for confirmation before spending unless `--yes` is
passed. Do not pass `--yes` on the user's behalf without being told to.

To show what a finished report looks like without spending anything, replay a
measurement committed in the Janus repository — this calls nothing:

```bash
janus measure --replay --task banking77 --top 3
janus measure --replay --task wos --top 3
```

## Step 5 — run, and read what comes back

### From a dataset

```bash
janus measure --dataset data.jsonl --labels question.json \
  --primary typesafe:jev-latest --fallback deepseek:deepseek-v4-pro \
  --out janus.json
```

The verdict is `ROUTE` or `DO NOT ROUTE`. **`DO NOT ROUTE` is a result, not a
failure**: it means no threshold beat the better single model, so the policy runs
that model alone. Report it as the answer it is.

The verdict block gives the threshold, the accuracy against the better single
model, the cost and median latency against the fallback, the escalation rate, and
the oracle ceiling — the best any threshold could reach **with this pair of
models**, not with the task.

### From a log

```bash
janus measure --log decisions.jsonl --labels question.json \
  --reference deepseek:deepseek-v4-pro \
  --input-field command --decision-field verdict
```

Read four things, in this order:

1. **The majority-class baseline**, printed next to the overall agreement. It is
   what a constant answer would score. An overall agreement that does not clear
   it means nothing, however high it looks.
2. **The tier table** — agreement per confidence band, with Wilson intervals.
   Bands under ten decisions are printed but marked not interpreted; respect that
   mark.
3. **The stratified view**, which Janus always prints. Confidence and the logged
   class are confounded whenever the high bands hold one class only. At constant
   class, agreement must still rise with confidence, or the confidence carries
   nothing of its own. This is the check that decides whether the signal is real.
4. **The threshold / coverage / cost table**. Projected cost is production cost:
   in service the reference is called only on what is escalated. The measurement
   itself called it on everything, and that figure is printed separately.

## Step 6 — what to tell the user

State plainly, in this order:

- the **threshold**, or that no threshold pays;
- the **coverage** it keeps and the share escalated;
- the **agreement with the named reference model** — never called correctness —
  with its interval, and how it compares to the majority-class baseline;
- the **cost**: what was estimated, what was actually spent, and what the routed
  policy would cost in production;
- the **limits**: the sample size, any band too small to interpret, any stratum
  flagged degenerate, and the fact that a threshold measured on one dataset does
  not transfer to another. Janus exists because that transfer failed: across the
  two datasets in its own repository the optimal threshold moved from 0.67 to
  0.37 and the sign of the gap between the models reversed.

## After the measurement

```bash
janus check janus.json --labels question.json   # does the policy still apply?
janus explain janus.json --input "..."          # why did this one escalate?
```

`check` compares the question's hash and the resolved model versions against
what was measured. Run it before trusting an old `janus.json`.

In Python, pin the **resolved** version rather than an alias — an alias moves
when a release ships, and a threshold measured on one version does not carry to
the next:

```python
from janus import Router, question_from_json, resolve

router = Router.from_file("janus.json",
                          primary=resolve("typesafe:jev-1.13.0"),
                          fallback=resolve("deepseek:deepseek-v4-pro"))
decision = router.decide(input="...", question=question_from_json("question.json"))
decision.label, decision.source, decision.escalated, decision.cost_usd
```

`Router` raises rather than applying a threshold measured on something else.

## When the project does not hold what is needed

Say which of these is missing, where you looked, and what would resolve it:

- **no log and no labelled dataset** — Janus measures data that exists; it does
  not generate any;
- **a log with no confidence column** — there is nothing to threshold;
- **no stated question** — the reference cannot be asked what the logged model
  was asked;
- **a class in the log that the question does not offer** — Janus names it and
  refuses; the two are not comparable until it is resolved;
- **no provider credentials** — name the environment variable the chosen
  provider needs.

Reporting a gap precisely is the correct outcome. Filling it with an invention is
not.
