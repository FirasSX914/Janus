"""La source `--log` : lecture, garde-fou de vocabulaire, stratification.

Fichier separe de test_janus.py, qui pin les chiffres publies de la source
`--dataset` et ne doit pas bouger.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from janus.agreement import MIN_TIER, Verdict, analyse, guard, ForbiddenWording
from janus.logs import LogFormatError, LogSpec, observed_decisions, read_log

#: Vocabulaire d'un vrai journal d'approbations : le champ d'entree s'appelle
#: `command`, la decision `verdict`. Rien n'oblige un journal a parler janus.
HERMES = LogSpec(input_field="command", decision_field="verdict",
                 confidence_field="confidence", id_field="ts")


def write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "log.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_reads_a_foreign_vocabulary(tmp_path):
    path = write(tmp_path, [
        {"ts": 1, "command": "git status", "verdict": "APPROVE", "confidence": 0.97},
        {"ts": 2, "command": "rm -rf /", "verdict": "DENY", "confidence": 0.41},
    ])
    rows = read_log(path, HERMES)
    assert [r.decision for r in rows] == ["APPROVE", "DENY"]
    assert [r.id for r in rows] == ["1", "2"]
    assert rows[0].input == "git status"


def test_missing_field_names_itself_and_what_is_there(tmp_path):
    path = write(tmp_path, [{"ts": 1, "cmd": "ls", "verdict": "APPROVE",
                             "confidence": 0.9}])
    with pytest.raises(LogFormatError) as error:
        read_log(path, HERMES)
    message = str(error.value)
    assert "'command'" in message          # le champ demande
    assert "cmd" in message and "verdict" in message   # ceux presents


def test_confidence_outside_the_unit_interval_is_refused(tmp_path):
    path = write(tmp_path, [{"ts": 1, "command": "ls", "verdict": "APPROVE",
                             "confidence": 97}])
    with pytest.raises(LogFormatError, match="outside"):
        read_log(path, HERMES)


def test_duplicate_ids_are_refused(tmp_path):
    path = write(tmp_path, [{"ts": 1, "command": "ls", "verdict": "APPROVE", "confidence": 0.9},
                            {"ts": 1, "command": "pwd", "verdict": "APPROVE", "confidence": 0.9}])
    with pytest.raises(LogFormatError, match="repeats id"):
        read_log(path, HERMES)


def test_decision_order_follows_the_log(tmp_path):
    path = write(tmp_path, [
        {"ts": 1, "command": "a", "verdict": "ESCALATE", "confidence": 0.3},
        {"ts": 2, "command": "b", "verdict": "APPROVE", "confidence": 0.9},
        {"ts": 3, "command": "c", "verdict": "ESCALATE", "confidence": 0.4},
    ])
    # L'ordre entre dans le prompt_hash de la reference : le reordonner
    # changerait la question posee.
    assert observed_decisions(read_log(path, HERMES)) == ["ESCALATE", "APPROVE"]


# ----------------------------------------------------------------- garde-fou
def test_guard_rejects_a_claim_of_correctness():
    for wording in ("overall accuracy 91%", "the model was correct",
                    "no ground truth here", "error rate 3%"):
        with pytest.raises(ForbiddenWording):
            guard(wording)


def test_guard_allows_the_mandated_formula():
    text = "agreement with the selected reference model, not correctness"
    assert guard(text) == text


# -------------------------------------------------------------- analyse()
def verdicts(n: int, *, high_class: str = "APPROVE") -> list[Verdict]:
    out = []
    for i in range(n):
        top = i % 3 == 0
        decision = high_class if top else "ESCALATE"
        confidence = 0.98 if top else 0.40
        agree = i % 7 != 0
        reference = decision if agree else "DENY"
        out.append(Verdict(str(i), confidence, decision, reference, agree, 0.001, 500))
    return out


def test_stratification_is_always_produced():
    report = analyse(verdicts(60))
    # Obligatoire, pas optionnelle : sans elle un accord eleve peut n'etre que
    # le desequilibre des classes.
    assert set(report.stratified) == {"APPROVE", "ESCALATE"}
    assert all(len(rows) == 4 for rows in report.stratified.values())


def test_tiers_are_disjoint():
    report = analyse(verdicts(60))
    assert sum(row.n for row in report.tiers) == report.n


def test_degenerate_stratum_is_flagged_not_hidden():
    report = analyse(verdicts(60))
    # Chaque classe ne vit que dans un palier ici : c'est exactement le cas que
    # l'experience gate a rencontre, et il doit se voir.
    assert any("degenerate" in caveat for caveat in report.caveats)


def test_small_tiers_are_reported_but_not_interpreted():
    rows = [Verdict(str(i), 0.99, "APPROVE", "APPROVE", True) for i in range(5)]
    rows += [Verdict(str(100 + i), 0.20, "DENY", "DENY", True) for i in range(40)]
    report = analyse(rows)
    top = next(t for t in report.tiers if t.label == "[0.95, 1.00]")
    assert top.n == 5 and not top.interpreted and top.n < MIN_TIER


def test_baseline_is_the_reference_majority():
    rows = [Verdict(str(i), 0.9, "APPROVE", "APPROVE", True) for i in range(90)]
    rows += [Verdict(str(100 + i), 0.9, "DENY", "APPROVE", False) for i in range(10)]
    report = analyse(rows)
    assert report.reference_decisions == {"APPROVE": 100}
    assert report.majority_baseline == 1.0
    # L'accord global ne bat pas une reponse constante : c'est le fait qui doit
    # ressortir, pas le 90 %.
    assert report.overall < report.majority_baseline


def test_projected_cost_is_production_not_measurement():
    rows = [Verdict(str(i), 1.0 if i < 80 else 0.1, "APPROVE", "APPROVE", True,
                    reference_cost=0.01) for i in range(100)]
    report = analyse(rows)
    keep_all = next(p for p in report.points if p.threshold == 1.0)
    # 20 lignes sous le seuil, donc 20 appels, pas 100.
    assert keep_all.escalation_rate == pytest.approx(0.20)
    assert keep_all.projected_cost == pytest.approx(0.20)
    assert report.reference_cost_total == pytest.approx(1.00)


def test_unknown_price_is_left_out_not_zeroed():
    rows = [Verdict(str(i), 0.9, "APPROVE", "APPROVE", True,
                    reference_cost=None if i == 0 else 0.01) for i in range(20)]
    report = analyse(rows)
    assert report.reference_cost_total is None
    assert any("zero" in caveat for caveat in report.caveats)


def test_rendered_report_passes_its_own_guard():
    from janus import cli
    report = analyse(verdicts(60))
    assert guard(cli._render_agreement(report, 60))
