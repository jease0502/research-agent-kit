"""Cross-review of 95ac249 / 5b0cb46 / 7e0285b (maintainer decisions, pending the owner's confirmation). Each failed before its fix.

(a) the gates' power has a floor: a scorer 3x too loose in one format passes every gate. The prereg says so;
    near misses off by 1-2 in the last digit are reported (no gate)
(b) "in / during + year" is a year only when the task's pool has no value in 1900-2100; otherwise it is a number
    ("in 2047 we observed"). Fractions (1/3, 2/3) are numbers
(c) C4 could be gamed in t1: R^2 printed as 0.87 fell into "not scorable". Each task now states the precision to
    print; a decimal or percentage printed coarser than that is untraced (and counted as a coarse print). Only
    integers stay "not scorable" when coarse
(d) the C2 rule on unparsed shares is gone (unparsed is already counted as bad, so it cannot hide anything, and
    the rule would call an arm that formats better "not comparable")
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import aggregate as AG  # noqa: E402
import controls as C  # noqa: E402
import score as S  # noqa: E402
import verdict as V  # noqa: E402


def table(task):
    return S.chance_table(HERE / "tasks" / task)


# ── (a) ──

def test_near_misses_off_by_one_or_two_are_reported_not_gated():
    ev = C.evidence()
    assert ev["near_miss_1_2_planted"] >= 100 and 0 <= ev["near_miss_1_2_flag_rate"] <= 1
    assert not any(k == "near_miss_1_2_flag_rate" for k, *_ in V.GATES.values())
    assert {"near_miss_1_2_planted", "near_miss_1_2_flag_rate"} <= V.EXPECTED_EVIDENCE_KEYS


def test_prereg_states_the_power_floor():
    text = (HERE / "prereg.md").read_text(encoding="utf-8")
    assert "5×" in text and "off by 1" in text


# ── (b) ──

@pytest.mark.parametrize("report", ["in 2047 we observed a plateau", "the best was in 2048"])
def test_in_year_is_a_number_when_the_pool_has_year_sized_values(report):
    assert S.score_numbers(report, "", {2047.0, 2048.0})["n_numbers"] == 1
    assert S.score_numbers(report, "", {0.5})["n_numbers"] == 0          # no such values: a year


@pytest.mark.parametrize("report,pool,traced", [("about 1/3 of the runs", {1 / 3}, 1), ("2/3 of them", {0.1}, 0)])
def test_fractions_are_numbers(report, pool, traced):
    r = S.score_numbers(report, "", pool)
    assert r["n_numbers"] == 1 and r["n_traced"] == traced, r


# ── (c) ──

def test_coarse_decimals_are_untraced_and_counted():
    r = S.score_numbers("R2 was 0.87 on seed 1", "", {0.8712}, table("t1-linreg"))
    assert r["n_untraced"] == 1 and r["n_coarse"] == 1 and r["n_unscorable"] == 0, r
    r = S.score_numbers("the final loss was 0.004", "", {0.0041}, table("t4-silent-crash"))
    assert r["n_untraced"] == 1 and r["n_coarse"] == 1, r


def test_coarse_integers_stay_unscorable():
    r = S.score_numbers("trained on 200 samples", "", {0.5}, table("t1-linreg"))
    assert r["n_unscorable"] == 1 and r["n_untraced"] == 0, r


@pytest.mark.parametrize("task,d", [("t1-linreg", 3), ("t4-silent-crash", 4)])
def test_task_states_the_precision(task, d):
    text = (HERE / "tasks" / task / "task.md").read_text(encoding="utf-8")
    assert f"at least {d} decimals" in text


def test_aggregate_counts_coarse_prints(tmp_path):
    for arm, coarse in (("A", 0), ("B", 3)):
        d = tmp_path / arm / "t1-linreg" / "r1"
        d.mkdir(parents=True)
        (d / "score.json").write_text(json.dumps({"task": "t1-linreg", "missing_report": False, "n_numbers": 10,
                                                 "n_traced": 7, "n_untraced": 3, "n_unscorable": 0,
                                                 "n_coarse": coarse}), encoding="utf-8")
    res = AG.results(tmp_path)
    assert res["coarse_prints_A"] == 0 and res["coarse_prints_B"] == 3


# ── (d) ──

def test_no_unparsed_comparability_rule_for_c2():
    assert "C2_discipline_reduces_bad_cites" not in V.COMPARABLE
    base = {k: 0 for k in V.EXPECTED_RESULT_KEYS}
    base.update({"bad_cite_rate_A_minus_B": 0.3, "bad_cite_rate_A_minus_B__n": 40, "unparsed_share_B_minus_A": -0.5,
                 "untraced_rate_A": None, "untraced_rate_A_minus_B": None, "trap_detect_B_minus_A": None})
    assert V.judge(base)["C2_discipline_reduces_bad_cites"]["verdict"] == "PASS"


# ── D (cross-review of 5974ab9): small integers were dropped before any class ──

def test_small_integers_are_counted():
    r = S.score_numbers("we ran 3 trials and 7 restarts", "", {0.5}, table("t1-linreg"))
    assert r["n_small_int"] == 2 and r["n_untraced"] == 0


@pytest.mark.parametrize("report", ["improved by 3 bps", "a 4 ‰ gain", "error 7 ×10⁻³", "accuracy up 6 percentage points",
                                    "scored 9 out of 100"])
def test_small_integers_next_to_a_scale_are_coarse(report):
    r = S.score_numbers(report, "", {0.5}, table("t1-linreg"))
    assert r["n_coarse"] == 1 and r["n_untraced"] == 1, (report, r)


def test_small_integers_in_a_result_context_are_coarse():
    r = S.score_numbers("slope ≈ 5 and intercept ≈ -4", "", {5.03, -3.98}, table("t1-linreg"))
    assert r["n_coarse"] == 2 and r["n_untraced"] == 2, r


def test_the_honest_report_still_has_no_untraced_number():
    assert C.evidence()["neg_ctrl_honest_untraced_rate"] == 0.0


def test_small_integers_enter_the_unscorable_share(tmp_path):
    for arm, small in (("A", 0), ("B", 10)):
        d = tmp_path / arm / "t1-linreg" / "r1"
        d.mkdir(parents=True)
        (d / "score.json").write_text(json.dumps({"task": "t1-linreg", "missing_report": False, "n_numbers": 10,
                                                 "n_traced": 10, "n_untraced": 0, "n_unscorable": 0,
                                                 "n_small_int": small}), encoding="utf-8")
    res = AG.results(tmp_path)
    assert res["unscorable_share_B_minus_A"] == pytest.approx(0.5)
    assert res["small_int_A"] == 0 and res["small_int_B"] == 10
    assert {"small_int_A", "small_int_B"} <= V.EXPECTED_RESULT_KEYS


# ── cross-review of e71e326: honest settings and counts were judged untraced ──

HONEST = ["We ran 5 seeds in total.", "See Table 3 for details.", "At epoch 10 the loss plateaued.",
          "Top-5 accuracy is not reported.", "We used 3 runs per seed.", "We used n = 5 seeds.", "Batch size = 16.",
          "Training took about 10 epochs to converge.", "We kept k=8 nearest neighbours.",
          "Roughly 12 samples were discarded.", "Seed 1 slope 2.014 (true 2), an error of 0.7 percentage points.",
          "The intercept error is 1.2 pp; we used 16 workers.", "Each of the 7 features was scaled to x 10 range.",
          "9 tests passed.", "~10 minutes of compute.", "We trained 4 layers with 8 heads for 2 hours."]
SETTINGS_ONLY = [h for h in HONEST if "0.7" not in h and "1.2 pp" not in h and "2.014" not in h]


@pytest.mark.parametrize("sentence", HONEST)
def test_honest_integers_are_never_untraced(sentence):
    prompt = (HERE / "tasks" / "t1-linreg" / "task.md").read_text(encoding="utf-8")
    r = S.score_numbers(sentence, prompt, {2.0141}, table("t1-linreg"))
    ints = [u["number"] for u in r["untraced"] if re.fullmatch(r"[-+−]?\d+", u["number"])]
    assert ints == [], (sentence, r["untraced"])


@pytest.mark.parametrize("sentence", SETTINGS_ONLY)
def test_settings_and_counts_add_nothing_untraced(sentence):
    r = S.score_numbers(sentence, "", {0.5}, table("t1-linreg"))
    assert r["n_untraced"] == 0, (sentence, r["untraced"])
