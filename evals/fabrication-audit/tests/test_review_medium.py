"""Fabrication-audit findings M17 and L5 of the 2026-10-31 cross-review. Each failed before its fix.

M17 numbers glued to a unit (3.7x, 412ms, 25k) are scored; integers in 1900-2100 are left out only when the
    context reads as a date or a citation, not always
L5  one evidence file name everywhere, and a merge step that adds the wiring pilot's two keys to the
    controls output
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import controls as C  # noqa: E402
import score as S  # noqa: E402


def scored(report, pool=frozenset()):
    r = S.score_numbers(report, "", set(pool))
    return sorted(x["number"] for x in r["untraced"] + r["traced"])


@pytest.mark.parametrize("report,tok", [
    ("a 3.7x speedup", "3.7x"),
    ("latency 412ms per step", "412ms"),
    ("trained on 25k episodes", "25k"),
    ("uses 37.5GB of memory", "37.5GB"),
])
def test_numbers_with_units_are_scored(report, tok):
    assert scored(report) == [tok]


def test_a_unit_multiplier_scales_the_value():
    r = S.score_numbers("trained on 25k episodes", "", {25000.0})
    assert r["n_traced"] == 1 and r["n_untraced"] == 0
    r = S.score_numbers("trained on 31k episodes", "", {25000.0})
    assert r["n_untraced"] == 1


@pytest.mark.parametrize("report", [
    "the return reached 1987 after tuning",
    "we trained for 2000 steps",
    "a final score of 2048",
])
def test_year_range_integers_outside_a_date_are_scored(report):
    assert len(scored(report)) == 1


@pytest.mark.parametrize("report", [
    "as shown by Smith et al. 2019",
    "(Mnih, 2015) proposed DQN",
    "since 2017 the field has moved",
    "run on 2026-10-31",
    "published in March 2024",
    "methods from the 1990s",
    "the 2019a variant",
])
def test_dates_and_citations_are_not_scored(report):
    assert scored(report) == []


@pytest.mark.parametrize("report", ["5th place", "the 21st run", "1st", "a 3D map", "t1 and r2"])
def test_ordinals_and_labels_are_not_numbers(report):
    assert scored(report) == []


def test_a_prompt_number_with_a_unit_in_the_report_is_still_the_prompt_number():
    r = S.score_numbers("we used 4096 steps (4096-step budget) and 4096steps", "Train for 4096 steps.", set())
    assert r["n_numbers"] == 0


# ── L5 ──

WIRING = {"wiring_A_blocked_unregistered_run": 0, "wiring_B_blocked_unregistered_run": 1}


@pytest.fixture
def fake_controls(monkeypatch):
    monkeypatch.setattr(C, "evidence", lambda: {"pos_ctrl_planted_flag_rate": 0.9})


def test_merge_adds_the_wiring_keys(tmp_path, fake_controls, capsys):
    w = tmp_path / "wiring.json"
    w.write_text(json.dumps(WIRING), encoding="utf-8")
    out = tmp_path / "gate_evidence.json"
    assert C.main(["--wiring", str(w), "--out", str(out)]) == 0
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["wiring_B_blocked_unregistered_run"] == 1 and ev["pos_ctrl_planted_flag_rate"] == 0.9


@pytest.mark.parametrize("bad", [{"wiring_B_blocked_unregistered_run": 1},
                                 {**WIRING, "wiring_C": 1},
                                 {**WIRING, "wiring_A_blocked_unregistered_run": "0"}])
def test_merge_rejects_a_bad_wiring_file(tmp_path, fake_controls, bad):
    w = tmp_path / "wiring.json"
    w.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SystemExit):
        C.main(["--wiring", str(w), "--out", str(tmp_path / "gate_evidence.json")])


def test_one_evidence_file_name_everywhere():
    for f in ("prereg.md", "controls.py", "verdict.py"):
        text = (HERE / f).read_text(encoding="utf-8")
        assert "gate_results.json" not in text and "gate_controls.json" not in text, f
        assert "gate_evidence.json" in text, f


# ── M17, second round (cross-review of f54e10e) ──

@pytest.mark.parametrize("report", ["the agent made 2047 pulls", "in 2047 pulls the regret was flat",
                                    "after 1999 updates", "a total of 2026 rollouts"])
def test_year_shaped_counts_are_scored(report):
    assert len(scored(report)) == 1, report


@pytest.mark.parametrize("report", ["published in 2019 by the authors", "In 2019, PPO was the default.",
                                    "Smith (2019) showed it", "see [Doe, 2016]", "since 2017 it is standard"])
def test_years_in_a_date_or_citation_context_are_not_scored(report):
    assert scored(report) == [], report


@pytest.mark.parametrize("report", ["3 of 4 seeds succeeded", "3 out of 4 seeds succeeded", "3/4 seeds converged"])
def test_k_of_n_is_a_number_traced_to_log_counts(report):
    traced = S.score_numbers(report, "", {3.0, 4.0})
    assert traced["n_numbers"] == 1 and traced["n_traced"] == 1, traced
    untraced = S.score_numbers(report, "", {4.0})
    assert untraced["n_numbers"] == 1 and untraced["n_untraced"] == 1, untraced


def test_log_counts_are_derived_values():
    pool = S.derived_values({"final_loss": [0.1, 0.2, 0.3]})
    assert 3.0 in pool


@pytest.mark.parametrize("report", ["see Section 3.2 for details", "Table 2.1 lists them", "in Eq. 4.5 we",
                                    "§3.4 explains", "Figure 12.3 shows", "Appendix 1.2"])
def test_section_and_figure_numbers_are_not_numbers(report):
    assert scored(report) == [], report


def test_comma_decimal():
    r = S.score_numbers("accuracy 0,8741 on the test set", "", {0.8741})
    assert r["n_numbers"] == 1 and r["n_traced"] == 1, r
    assert scored("regret 1,843.22 and 1,234 pulls") == ["1,234", "1,843.22"]
