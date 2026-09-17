# calibre

On Banking77, routing on Jev's confidence reaches 80.2% accuracy at $0.103 per 500 decisions — higher accuracy than DeepSeek V4-Pro alone (78.8%) at 53% lower cost.

This repository measures the calibration of [TypeSafe](https://docs.typesafe.ai/)'s
Jev decision model and evaluates **confidence-based routing**: a Jev → fallback
cascade that escalates only what Jev is unsure about. It answers one question:
**at what confidence level can Jev decide on its own, rather than paying a larger
model, for a given accuracy target?**

The protocol was frozen before any result was looked at
([commit `2384a6b`](../../commit/2384a6b)). The dataset, the raw results and the
analysis code are all in this repository.

## Results

![Accuracy vs cost for confidence-based routing on Banking77. Each dot is one confidence threshold; the star marks the 0.67 threshold at 80.2% for $0.103.](results/figures/accuracy_vs_cost.png)

500 examples from the Banking77 test split, 77 intent labels, one call per example.

| Strategy | Accuracy | Cost / 500 | DeepSeek calls |
|---|---|---|---|
| Jev only | 77.8% | $0.0507 | 0 |
| DeepSeek V4-Pro only | 78.8% | $0.2207 | 500 |
| **Cascade @ 0.67** | **80.2%** | **$0.1033** | **58** (11.6%) |
| Oracle | 83.2% | — | — |

**What this means:** On this dataset, confidence-based routing improves accuracy over
either model alone while reducing DeepSeek usage; the disagreements where DeepSeek is
correct are concentrated at lower Jev confidence levels.

The cascade keeps Jev's answer when its confidence reaches the threshold and
escalates otherwise. Its cost always includes Jev on all 500 requests — the
confidence has to be obtained before anything can be routed on it — plus DeepSeek
on the escalated fraction. Both figures are measured per row, not estimated from
a list price: the DeepSeek side accounts for the cache hit/miss split and the
hourly rate in force at the time of each call.

The oracle counts an example as correct when either model got it right. It is the
ceiling of this cascade, not of the task.

## Calibration

`confidence` is not a probability of being right. It is a statistic derived from
the shape of the probability distribution, and measuring what it actually predicts
is the point of this repository.

**The scale is discrete.** Measured on the raw HTTP body, before any SDK parsing:
across 1,540 probability values, none falls off a 0.01 grid, and `confidence` has
the same granularity as `probabilities`. Nothing is representable between 0.99 and
1.00. On the full run, 44 values out of 38,500 sit up to one double ULP off the
grid, which is float arithmetic, not extra resolution.

![Calibration: reported confidence against empirical accuracy, by tier, with 95% Wilson intervals. The 1.00 atom is shown apart.](results/figures/calibration.png)

Every tier sits below the diagonal: reported confidence runs ahead of measured
accuracy at every level, the 1.00 atom included.

**Accuracy per observed confidence level** (63 distinct levels; the four largest):

| Confidence | N | Correct | Accuracy | 95% Wilson |
|---|---|---|---|---|
| 1.00 | 238 | 228 | 95.8% | [92.4%, 97.7%] |
| 0.99 | 46 | 37 | 80.4% | [66.8%, 89.3%] |
| 0.98 | 24 | 19 | 79.2% | [59.5%, 90.8%] |
| 0.97 | 18 | 14 | 77.8% | [54.8%, 91.0%] |

The 1.00 level carries 47.6% of the traffic at 95.8% accuracy. Accuracy drops to
80.4% at the very next representable level. 58 of the 63 levels hold fewer than 10
observations each, together 32.4% of the mass, so no single row below the top few
supports a conclusion on its own.

**No tested derived statistic improves on `confidence`.** Three alternatives computed from
the raw distribution — `margin_top2`, `entropy_norm`, `ratio_top2` — were compared
by AUROC over the 262 rows outside the 1.00 level, which is the only region where
they are not constant by construction. Paired bootstrap, 10,000 iterations,
seed 1729:

| Statistic | AUROC | Difference vs `confidence` (95% CI) |
|---|---|---|
| `confidence` | 0.706 | — |
| `entropy_norm` | 0.705 | +0.002 [−0.012, +0.015] |
| `margin_top2` | 0.695 | +0.011 [+0.001, +0.021] |
| `ratio_top2` | 0.691 | +0.015 [+0.003, +0.028] |

The data show no improvement of the alternative statistics over `confidence`. The
bootstrap intervals exclude zero for the `margin_top2` and `ratio_top2` differences,
but the observed differences are small. The alternatives were not pre-registered with
a minimum margin to beat, so this is an absence of improvement, not a reversal.

## Agreement between the two models

| | Count | Share |
|---|---|---|
| Both correct | 367 | 73.4% |
| Both wrong, same prediction | 75 | 15.0% |
| Both wrong, different predictions | 9 | 1.8% |
| Jev correct, DeepSeek wrong | 22 | 4.4% |
| DeepSeek correct, Jev wrong | 27 | 5.4% |

Among the 49 disagreements, 74.1% of those DeepSeek wins fall below confidence 0.70,
against 59.1% of those Jev wins. That concentration is what the routing rule exploits:
escalating the low-confidence tail reaches most of the cases DeepSeek would get right.

On the 238 examples where Jev returned confidence = 1.00, DeepSeek produced the
identical prediction in 238 out of 238 cases.

## Limitations

**One dataset, 500 examples, one domain.** Banking77 intent classification, in
English. Nothing here establishes behaviour on other tasks, other languages or
other label sets. A second dataset is in progress; generalisation is not
demonstrated.

**The 0.67 threshold is observed in this data, not a constant of the mechanism.**
It is where accuracy peaks on these 500 examples. It should be re-derived on any
new workload rather than copied.

**The pre-registered targets are unreachable.** 90%, 95% and 98% were fixed before
the frontier run. DeepSeek V4-Pro alone reaches 78.8%, so all three were beyond the
fallback itself, whatever the routing rule. That is a design fault in the protocol
— the targets were set with no known upper bound — and it is reported rather than
corrected. The targets are not revised.

**The oracle belongs to this pair of models, not to the dataset.** On 84 of the 500,
neither Jev nor DeepSeek has the right answer, which caps this cascade at 83.2%. A
different fallback could recover some of those; the ceiling would move.

**The 84 common errors span 47 distinct (gold, prediction) pairs**, the most frequent
accounting for 4 cases. They fall mostly between semantically adjacent classes —
`order_physical_card` → `get_physical_card`, `card_delivery_estimate` →
`card_arrival`, `top_up_reverted` → `top_up_failed`. **How much of this is label
ambiguity in Banking77 rather than model error has not been established**, and this
repository does not attempt to.

**The frontier baseline is DeepSeek V4-Pro.** Claude Opus 5 is announced for v2; the
provider interface is in place and the protocol is frozen, so it is a run to launch,
not a rewrite. An attempt on Gemini 3.8 Flash was abandoned — its free tier allows 20
requests a day, which would make 500 examples take 25 days — and its partial data is
excluded.

**No reproducibility claim for the frontier side.** `temperature` has been removed
from the API generation used by the Anthropic backend and returns a 400; DeepSeek and
Gemini both return an alias rather than a resolved version, unlike Jev's
`jev-1.13.0`. Two runs of the same file may differ.

## Reproduction

Total cost of a full reproduction: **~$0.27** — $0.0507 for Jev, $0.2207 for DeepSeek.

```bash
pip install typesafe-sdk openai numpy matplotlib

cat > .env <<'EOF'
TYPESAFE_API_KEY=...
DEEPSEEK_API_KEY=...
EOF

python src/probe.py                             # one call, prints the raw response
python src/prepare_data.py                      # rebuilds data/banking77_500.jsonl
python src/run_jev.py                           # 500 calls, ~$0.051
python src/run_frontier.py --provider deepseek  # 500 calls, ~$0.221
python src/analyze.py                           # calibration + risk-coverage, writes figures
python src/cascade.py                           # cascade table + figure, no API call
```

Both runners write one line at a time, resume on the ids already present, and refuse
to resume when an existing line carries a different `prompt_hash` — two prompt
versions can never share a file.

The dataset is committed with its hashes, so a re-download that drifts is detectable:

```
sha256(test.csv)              d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d
sha256(banking77_500.jsonl)   33547bc2c3453057fbeb50cc5cb68da32c6da3c1b79b5deae47567c20fcf0bb6
```

`analyze.py` and `cascade.py` never call an API. They read `results/raw/` and compute.

## Layout

```
src/probe.py          one call, prints the raw unparsed response
src/labels.py         the 77 labels, id -> name -> description, shared by all runners
src/prepare_data.py   builds the frozen dataset
src/run_jev.py        Jev on the 500 -> JSONL
src/providers.py      frontier backends behind one interface
src/run_frontier.py   frontier on the 500 -> JSONL
src/analyze.py        calibration, risk-coverage, figures
src/cascade.py        cascade simulation, zero API calls
data/                 frozen dataset + provenance
results/raw/          raw JSONL, one line per example
results/figures/      figures, regenerated by analyze.py and cascade.py
docs/METHOD.md        protocol, measured constraints, related work
```

Both figures are produced from the committed raw results by the scripts above. None
is redrawn by hand.

## Related work

Verified on 2026-09-17 against the repositories themselves. This rests on a name
search on GitHub, so it is not exhaustive, and no claim of the form "nobody has done
X" is drawn from it.

Several open-source reimplementations of the decision pattern appeared after Jev
shipped on 2026-09-15. They differ in whether they expose calibration at all, and
whether they publish measurements against real ground truth — the two come apart in
practice.

- [genai-craft/openvons](https://github.com/genai-craft/openvons) carries the fullest
  calibration surface: temperature, isotonic, and ECE / Brier / NLL / macro-F1.
- [bnsd55/openjev](https://github.com/bnsd55/OpenJev) reports a fitted temperature and
  ECE before and after (0.0870 → 0.0773 at T = 1.7178) on 72 field-level decisions.
- [TheoLeeCJ/openjev](https://github.com/TheoLeeCJ/openjev) publishes balanced accuracy
  on WANLI (256 rows) and on an authored set (144 rows), without calibration metrics.
- [kw2828/OpenJev](https://github.com/kw2828/OpenJev) states outright that its scores
  are uncalibrated, and works on synthetic data.
- [aigodsend9-boop/specter-decision-engine](https://github.com/aigodsend9-boop/specter-decision-engine)
  is a framework with no trained model bundled, exposing temperature via NLL, isotonic
  via PAV, and Brier / NLL / ECE with bootstrap.
- [grishahq/decisionbridge](https://github.com/grishahq/decisionbridge) adapts existing
  LLMs into decision functions with temperature calibration; its bundled evaluation is
  described by its own README as a small, English-only, AI-authored synthetic pilot.
- [dbobo4/local-llm-probabilistic-decision-engine](https://github.com/dbobo4/local-llm-probabilistic-decision-engine)
  scores candidates directly and warns that calibration must be measured separately on
  representative labelled data.
- [hamakyo/jev-starter](https://github.com/hamakyo/jev-starter) targets the closest
  programme to this one — decision contracts, thresholds, fallbacks, and a Jev →
  fallback cascade on a labelled dataset. Its
  [issue #5](https://github.com/hamakyo/jev-starter/issues/5) specifies ECE, Brier,
  threshold sweeps and coverage-versus-risk. At the time of checking those metrics are
  presented as planned rather than published.

Agent-side integrations exist as well, including
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast), which
publishes task-timing measurements and notes itself that they are not a general
reliability benchmark.

TypeSafe publishes its own [workflow evals](https://evals.typesafe.ai/). Their
reference labels are, in their words, "generated via an average of the responses of
GPT-6 Astra and Claude Fable 5.1, both at high thinking", and they state that they
"assume that the code is correct, and measure against the current smartest large
models" rather than optimising for a ground-truth classification.
**TypeSafe's reference methodology evaluates agreement with its reference models,
whereas calibre evaluates predictions against human-labelled ground truth.** These
answer different questions and neither substitutes for the other.

Jev is also available on [Vercel's AI Gateway](https://vercel.com/changelog/typesafe-ai-jev-now-available-on-ai-gateway)
as `typesafe-ai/jev`, announced on 16 September 2026, the day after Jev shipped.

Our contribution is an empirical evaluation of confidence-based selective automation
on a real ground-truth dataset, rather than another implementation of the decision
layer itself.

Full survey, with what was and was not verified: [`docs/METHOD.md`](docs/METHOD.md).

## License

MIT — see [LICENSE](LICENSE).

Banking77 is distributed under CC BY 4.0; see [`data/README.md`](data/README.md) for
provenance and citation.
