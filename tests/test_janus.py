"""Invariants du paquet.

Le test qui compte est `test_reproduces_published_numbers` : le moteur migre
doit redonner exactement les chiffres publies dans le README, depuis les JSONL
bruts commites. S'il derive, soit le moteur a change, soit les resultats publies
ne sont plus ceux que le code produit -- et les deux doivent faire echouer la
suite.

    pip install -e ".[typesafe]" && python -m pytest tests -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus import Question
from janus.measure import calibration_of
from janus.policy import (InvalidPolicyError, ModelRef, NoPolicyError, Policy,
                          StalePolicyError, build)
from janus.providers.base import prompt_hash
from janus.sweep import Row, choose, oracle_accuracy, sweep
from janus.types import Answer

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results" / "raw"

#: Chiffres publies dans le README, par dataset.
PUBLISHED = {
    "banking77": {"accuracy": 0.778, "ece": 0.1568, "brier": 0.3518,
                  "oracle": 0.832, "verdict": "route", "threshold": 0.67,
                  "point_accuracy": 0.802},
    "wos": {"accuracy": 0.528, "ece": 0.3217, "brier": 0.7491,
            "oracle": 0.560, "verdict": "do_not_route", "threshold": None,
            "point_accuracy": 0.528},
}


def _rows(name: str) -> list[dict]:
    path = RAW / name
    if not path.exists():
        pytest.skip(f"{name} not committed in this checkout")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _paired(task: str) -> list[Row]:
    primary = _rows(f"jev_{task}_500.jsonl")
    fallback = {r["id"]: r for r in _rows(f"deepseek_{task}_500.jsonl")}
    return [Row(confidence=p["confidence"],
                primary_ok=p["prediction"] == p["gold_label"],
                fallback_ok=fallback[p["id"]]["prediction"] == fallback[p["id"]]["gold_label"],
                primary_cost=p["input_tokens"] / 1e6 * 0.042,
                fallback_cost=fallback[p["id"]]["cost_usd"])
            for p in primary if p["id"] in fallback]


@pytest.mark.parametrize("task", sorted(PUBLISHED))
def test_reproduces_published_numbers(task: str) -> None:
    expected = PUBLISHED[task]
    rows = _paired(task)
    report = calibration_of(_rows(f"jev_{task}_500.jsonl"))
    point, verdict, _ = choose(sweep(rows))

    assert report.accuracy == pytest.approx(expected["accuracy"], abs=5e-4)
    assert report.ece_by_level == pytest.approx(expected["ece"], abs=5e-5)
    assert report.brier == pytest.approx(expected["brier"], abs=5e-5)
    assert oracle_accuracy(rows) == pytest.approx(expected["oracle"], abs=5e-4)
    assert verdict == expected["verdict"]
    assert point.threshold == expected["threshold"]
    assert point.accuracy == pytest.approx(expected["point_accuracy"], abs=5e-4)


def test_do_not_route_is_a_first_class_outcome() -> None:
    """Quand router ne paie pas, la politique designe un modele seul."""
    point, verdict, reason = choose(sweep(_paired("wos")))
    assert verdict == "do_not_route"
    assert point.rule == "always_primary"
    assert point.threshold is None
    assert "single model" in reason


def test_cost_of_always_fallback_excludes_the_primary() -> None:
    """La regle `always_fallback` n'interroge pas le primary, donc ne le paie pas."""
    points = {p.rule: p for p in sweep(_paired("banking77"))}
    escalate_all = next(p for p in sweep(_paired("banking77"))
                        if p.rule == "primary_if_confidence_ge"
                        and p.escalation_rate == 1.0)
    assert points["always_fallback"].cost_total < escalate_all.cost_total


# --------------------------------------------------------------- politiques
def _policy(threshold: float = 0.67) -> Policy:
    question = Question(instructions="Which?", criteria={"a": "A", "b": "B"})
    rows = [Row(1.0, True, True, 0.001, 0.01), Row(0.5, False, True, 0.001, 0.01)]
    point, verdict, reason = choose(sweep(rows))
    policy = build(question=question,
                   primary=ModelRef("typesafe", "jev-latest", "jev-1.13.0"),
                   fallback=ModelRef("deepseek", "deepseek-v4-pro", "deepseek-v4-pro"),
                   point=point, verdict=verdict, reason=reason, levels=(),
                   oracle=1.0, unreachable=0, measured_on={"rows": 2},
                   baselines={"primary_only": 0.5, "fallback_only": 1.0})
    return policy


def test_missing_policy_names_the_command_to_run(tmp_path: Path) -> None:
    with pytest.raises(NoPolicyError) as error:
        Policy.read(tmp_path / "janus.json")
    assert "janus measure" in str(error.value)


def test_threshold_off_the_grid_is_refused() -> None:
    data = _policy().to_json()
    data["decision"].update(rule="primary_if_confidence_ge", threshold=0.675)
    with pytest.raises(InvalidPolicyError):
        Policy.from_json(data)


def test_a_different_statement_is_stale() -> None:
    with pytest.raises(StalePolicyError):
        _policy().check_question(Question(instructions="Other?", criteria={"x": ""}))


def test_model_drift_is_reported() -> None:
    drift = _policy().check_models(primary_model_id="jev-1.14.0")
    assert drift and "jev-1.13.0" in drift[0] and "jev-1.14.0" in drift[0]


def test_policy_round_trips(tmp_path: Path) -> None:
    policy = _policy()
    path = tmp_path / "janus.json"
    policy.write(path)
    assert Policy.read(path).to_json() == policy.to_json()


# ------------------------------------------------------------------ enonce
def test_prompt_hash_tracks_order_and_wording() -> None:
    base = Question("Which?", {"a": "A", "b": "B"})
    assert prompt_hash(base) == prompt_hash(Question("Which?", {"a": "A", "b": "B"}))
    # Reordonner les options change le corps de la requete.
    assert prompt_hash(base) != prompt_hash(Question("Which?", {"b": "B", "a": "A"}))
    # Reformuler un critere aussi.
    assert prompt_hash(base) != prompt_hash(Question("Which?", {"a": "A.", "b": "B"}))


def test_answer_keeps_absent_confidence_absent() -> None:
    """Un fournisseur sans distribution ne se voit pas attribuer de valeur."""
    answer = Answer(label="a", model_id="m")
    assert answer.confidence is None
    assert answer.distribution is None
