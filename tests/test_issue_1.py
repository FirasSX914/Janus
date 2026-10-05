"""Regressions de l'issue #1.

1. `--budget` restait silencieusement inerte pour un modele sans tarif.
2. `pricing_tier` lisait l'heure locale contre des fenetres UTC.
3. Les scripts d'experience exigeaient un `.env` jusque pour `--help`.

Aucun test ne joint un fournisseur : les backends sont des doublures qui
comptent leurs appels.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from janus import Question
from janus.cost import cost_of, is_peak
from janus.measure import BudgetExceeded, measure, run_provider
from janus.types import Answer

ROOT = Path(__file__).resolve().parent.parent

QUESTION = Question(instructions="Pick one.", criteria={"a": "first", "b": "second"})
EXAMPLES = [{"id": i, "text": f"row {i}", "gold_label": "a"} for i in range(40)]

PRICED = "claude-opus-5"        # present dans FLAT_PRICING
UNPRICED = "jev-latest"         # un alias : aucun tarif ne lui est attache


class CountingProvider:
    """Doublure : rend toujours `a`, compte ses appels, se tarife via `cost_of`."""

    def __init__(self, model: str, answers_as: str | None = None) -> None:
        self.name = "fake"
        self.model = model
        self._answers_as = answers_as or model
        self.calls = 0

    def ask(self, input: str, question: Question) -> Answer:
        self.calls += 1
        return Answer(label="a", model_id=self._answers_as, confidence=0.9,
                      distribution={"a": 0.9, "b": 0.1},
                      input_tokens=1000, output_tokens=10)

    def cost_usd(self, answer: Answer, when: datetime) -> float | None:
        return cost_of(answer, when)


# --- 1. --budget ----------------------------------------------------------

def test_budget_on_an_unpriced_model_refuses_before_any_call(tmp_path: Path) -> None:
    provider = CountingProvider(UNPRICED)
    with pytest.raises(BudgetExceeded, match="cannot be enforced"):
        run_provider(provider, EXAMPLES, QUESTION, tmp_path / "p.jsonl",
                     budget=1.0, progress=lambda _: None)
    assert provider.calls == 0
    assert not (tmp_path / "p.jsonl").exists()


def test_unpriced_fallback_is_caught_before_the_primary_spends(tmp_path: Path) -> None:
    primary = CountingProvider(PRICED)
    fallback = CountingProvider(UNPRICED)
    with pytest.raises(BudgetExceeded, match="cannot be enforced"):
        measure(examples=EXAMPLES, question=QUESTION, primary=primary,
                fallback=fallback, artifacts=tmp_path, budget=100.0,
                progress=lambda _: None)
    assert primary.calls == 0
    assert fallback.calls == 0


def test_alias_resolving_to_an_unpriced_version_stops_at_once(tmp_path: Path) -> None:
    # L'identifiant demande a un tarif, la version rendue non : le cas d'un
    # alias qui bouge. On ne peut le savoir qu'apres un appel, on s'arrete la.
    provider = CountingProvider(PRICED, answers_as="claude-opus-6")
    with pytest.raises(BudgetExceeded, match="cannot be enforced"):
        run_provider(provider, EXAMPLES, QUESTION, tmp_path / "p.jsonl",
                     budget=100.0, progress=lambda _: None)
    assert provider.calls == 1


def test_budget_still_stops_a_priced_run_at_call_ten(tmp_path: Path) -> None:
    provider = CountingProvider(PRICED)
    with pytest.raises(BudgetExceeded, match="projected cost"):
        run_provider(provider, EXAMPLES, QUESTION, tmp_path / "p.jsonl",
                     budget=0.00001, progress=lambda _: None)
    assert provider.calls == 10


def test_without_budget_an_unpriced_model_still_runs(tmp_path: Path) -> None:
    provider = CountingProvider(UNPRICED)
    rows = run_provider(provider, EXAMPLES, QUESTION, tmp_path / "p.jsonl",
                        progress=lambda _: None)
    assert provider.calls == len(EXAMPLES)
    assert all(r["cost_usd"] is None for r in rows)


def test_nothing_left_to_do_needs_no_price(tmp_path: Path) -> None:
    out = tmp_path / "p.jsonl"
    run_provider(CountingProvider(UNPRICED), EXAMPLES, QUESTION, out,
                 progress=lambda _: None)
    resumed = CountingProvider(UNPRICED)
    run_provider(resumed, EXAMPLES, QUESTION, out, budget=1.0, progress=lambda _: None)
    assert resumed.calls == 0


# --- 2. pricing_tier ------------------------------------------------------

def test_pricing_tier_is_read_in_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("openai")
    from janus.providers import openai_compat
    from janus.providers.openai_compat import DeepSeekProvider, OpenAICompatProvider

    # Lundi 04:30 UTC : hors heures pleines. La meme heure sur une machine en
    # UTC+2 se lit 06:30, dans une fenetre pleine.
    utc_now = datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return utc_now.astimezone(tz)
            return utc_now.astimezone(timezone(timedelta(hours=2))).replace(tzinfo=None)

    monkeypatch.setattr(openai_compat, "datetime", Clock)
    monkeypatch.setattr(OpenAICompatProvider, "ask", lambda self, input, question: Answer(
        label="a", model_id="deepseek-v4-pro", input_tokens=100, output_tokens=10,
        extra={"cache_hit_tokens": 60, "cache_miss_tokens": 40}))

    provider = DeepSeekProvider.__new__(DeepSeekProvider)
    provider.model = "deepseek-v4-pro"
    answer = provider.ask("x", QUESTION)

    billed_peak = is_peak("deepseek-v4-pro", utc_now)
    assert billed_peak is False
    assert answer.extra["pricing_tier"] == "off_peak"


# --- 3. .env optionnel ------------------------------------------------------

@pytest.mark.parametrize("script", ["experiments/gate/run_gate.py",
                                    "experiments/run_frontier.py"])
def test_experiment_help_needs_no_env_file(script: str, tmp_path: Path) -> None:
    path = ROOT / script
    if not path.exists():
        pytest.skip(f"{script} not in this checkout")
    if (ROOT / ".env").exists():
        pytest.skip("a .env is present: the missing-file path cannot be exercised")
    result = subprocess.run([sys.executable, path.name, "--help"], cwd=path.parent,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
