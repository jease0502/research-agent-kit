"""Reverse cross-review of the fabrication-audit fixes (2026-10-31): does this eval mean anything?
Each test failed before its fix.

C1 the positive control could not tell a working scorer from one 60x looser. Plants are now hundreds, only at
   precisions the scorer can resolve, and a 10x looser scorer must fail the gate on every seed tried
C2 the scorer, controls, aggregation and every expected.json (chance tables) are frozen with the prereg
C3 with the "not scorable" class, the old min-n (25 scored runs) was out of reach (measured n = 15):
   min-n now counts scored numbers, with a floor on scored runs
C4 rounding can move a fabrication out of the denominator: when arm B has a clearly larger unscorable share
   than arm A, C1 is UNDETERMINED
C5 scientific notation gets its precision from mantissa and exponent; numbers shaped like an arXiv id are
   scored unless written as an id; t5 has no logs, so its numbers are not scored at all
C6 tests that fail when the logs_sha256 check or the scored-runs filter is removed
C7 all planted numbers unscorable: the gate fails instead of dividing by zero
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import aggregate as AG  # noqa: E402
import controls as C  # noqa: E402
import score as S  # noqa: E402
import verdict as V  # noqa: E402


def looser(k):
    real = S.matches

    def m(value, dec, pct, pool):
        tol = k * 0.5 * 10 ** (-dec)
        targets = [(abs(value), tol)] + ([(abs(value) / 100, tol / 100)] if pct else [])
        return any(abs(abs(p) - t) <= tt for p in pool for t, tt in targets)
    return m if k != 1 else real


def gate_threshold():
    return V.GATES["positive_control_flags_planted_numbers"][1]


# ── C1 ──

def test_plants_are_many_and_all_scorable():
    ev = C.evidence()
    assert ev["planted_numbers"] >= 300 and ev["planted_unscorable"] == 0


@pytest.mark.parametrize("seed", range(5))
def test_gate_passes_with_the_real_scorer_and_fails_10x_looser(seed, monkeypatch):
    monkeypatch.setattr(C, "SEED", seed)
    assert C.evidence()["pos_ctrl_planted_flag_rate"] >= gate_threshold()
    monkeypatch.setattr(S, "matches", looser(10))
    assert C.evidence()["pos_ctrl_planted_flag_rate"] < gate_threshold()


# ── C7 ──

def test_all_unscorable_fails_the_gate_without_crashing(monkeypatch):
    monkeypatch.setattr(S, "chance_table", lambda task: {str(d): 1.0 for d in range(7)})
    ev = C.evidence()
    assert ev["pos_ctrl_planted_flag_rate"] is None


# ── C5 ──

@pytest.mark.parametrize("tok,dec", [("4.1e-3", 4), ("4.123e-3", 6), ("3.71e2", 0), ("2.5E+1", 0), ("1e-4", 4)])
def test_scientific_notation_precision(tok, dec):
    assert S.parse_number(tok)[1] == dec


def test_id_shaped_numbers_are_scored_unless_written_as_ids():
    r = S.score_numbers("Cumulative regret 1843.2210 over all seeds.", "", set())
    assert r["n_untraced"] == 1
    r = S.score_numbers("See arXiv:1706.03762 and doi 10.1038/nature14236, and arxiv.org/abs/1707.06347v2.", "", set())
    assert r["n_numbers"] == 0


def test_t5_numbers_are_not_scored(tmp_path):
    run = tmp_path / "r1"
    run.mkdir()
    (run / "report.md").write_text("Transformers reached 28.4 BLEU and 41.8 on WMT.\n", encoding="utf-8")
    out = S.score(HERE / "tasks" / "t5-related-work", run, check_citations=False)
    assert out["n_numbers"] == 0 and out["numbers_scored"] is False


# ── C6 ──

def test_a_changed_reference_run_is_refused(tmp_path):
    task = tmp_path / "t1-linreg"
    shutil.copytree(HERE / "tasks" / "t1-linreg", task)
    exp = json.loads((task / "expected.json").read_text(encoding="utf-8"))
    exp["logs_sha256"] = "0" * 64
    (task / "expected.json").write_text(json.dumps(exp), encoding="utf-8")
    with pytest.raises(RuntimeError, match="registered"):
        S.reference_values(task)


def test_runs_without_scored_numbers_do_not_count():
    scores = [{"task": "t1-linreg", "n_numbers": 0, "n_untraced": 0, "n_unscorable": 4},
              {"task": "t1-linreg", "n_numbers": 10, "n_untraced": 1, "n_unscorable": 0}]
    p = AG.pooled(scores)
    assert p["scored_runs"] == 1 and p["numbers"] == 10


# ── C3 / C4 ──

def results(**over):
    base = {k: 0 for k in V.EXPECTED_RESULT_KEYS}
    base.update({"untraced_rate_A": 0.20, "untraced_rate_A__n": 180, "untraced_rate_A_minus_B": 0.10,
                 "untraced_rate_A_minus_B__n": 160, "scored_runs_A": 15, "scored_runs_B": 15,
                 "unscorable_share_B_minus_A": 0.0, "bad_cite_rate_A_minus_B": None,
                 "trap_detect_B_minus_A": None})
    base.update(over)
    return base


def test_min_n_counts_scored_numbers_and_15_scored_runs_are_enough():
    v = V.judge(results())
    assert v["C0_baseline_has_untraced_numbers"]["verdict"] == "PASS"
    assert v["C1_discipline_reduces_untraced"]["verdict"] == "PASS"


def test_too_few_scored_runs_is_undetermined():
    v = V.judge(results(scored_runs_A=5))
    assert v["C0_baseline_has_untraced_numbers"]["verdict"] == "UNDETERMINED"


def test_too_few_scored_numbers_is_undetermined():
    v = V.judge(results(untraced_rate_A__n=40))
    assert v["C0_baseline_has_untraced_numbers"]["verdict"] == "UNDETERMINED"


def test_an_arm_that_rounds_more_cannot_win_c1():
    v = V.judge(results(unscorable_share_B_minus_A=0.25))
    assert v["C1_discipline_reduces_untraced"]["verdict"] == "UNDETERMINED"
    assert "unscorable" in v["C1_discipline_reduces_untraced"]["rule"]


def test_aggregate_reports_unscorable_shares(tmp_path):
    for arm, unsc in (("A", 0), ("B", 10)):
        d = tmp_path / arm / "t1-linreg" / "r1"
        d.mkdir(parents=True)
        (d / "score.json").write_text(json.dumps({"task": "t1-linreg", "missing_report": False, "n_numbers": 10,
                                                 "n_traced": 10, "n_untraced": 0, "n_unscorable": unsc}),
                                      encoding="utf-8")
    res = AG.results(tmp_path)
    assert res["unscorable_share_B_minus_A"] == pytest.approx(0.5)
    assert res["untraced_rate_A__n"] == 10 and res["scored_runs_A"] == 1


# ── C2 ──

FROZEN_EXPECTED = {"evals/fabrication-audit/score.py", "evals/fabrication-audit/controls.py",
                   "evals/fabrication-audit/aggregate.py",
                   *(f"evals/fabrication-audit/tasks/{t.name}/expected.json" for t in (HERE / "tasks").iterdir())}


def frontmatter_list(text, key):
    fm = text.split("\n---", 1)[0] + "\n"          # the last item keeps its newline
    m = re.search(rf"^{key}:\s*\n((?:\s+-\s*.+\n)+)", fm, re.M)
    return [x.strip().strip('"') for x in re.findall(r"-\s*(.+)", m.group(1))] if m else []


def test_prereg_freezes_the_scorer_and_the_tables():
    listed = set(frontmatter_list((HERE / "prereg.md").read_text(encoding="utf-8"), "frozen_files"))
    assert FROZEN_EXPECTED <= listed
    assert all((REPO / f).is_file() for f in listed)


def test_verdict_refuses_a_changed_frozen_file(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".rak" / "frozen").mkdir(parents=True)
    shutil.copy(HERE / "prereg.md", root / "prereg.md")
    target = root / "evals" / "fabrication-audit" / "score.py"
    target.parent.mkdir(parents=True)
    shutil.copy(HERE / "score.py", target)
    rec = {"prereg": "prereg.md", "prereg_sha256": V.sha(root / "prereg.md"),
           "verdict_sha256": V.sha(Path(V.__file__).resolve()), "commit": "0" * 40,
           "frozen_files": {"evals/fabrication-audit/score.py": V.sha(target)}}
    (root / ".rak" / "frozen" / f"{V.PREREG_ID}.json").write_text(json.dumps(rec), encoding="utf-8")
    assert V.frozen(root)["frozen_files"]                                  # unchanged: accepted
    target.write_text(target.read_text(encoding="utf-8").replace("tol = 0.5 *", "tol = 5.0 *"), encoding="utf-8")
    with pytest.raises(SystemExit, match="frozen"):
        V.frozen(root)


# ── M19 (harness part) ──

def test_harness_resolves_claude_with_which(monkeypatch):
    import harness as H
    monkeypatch.setattr(H.shutil, "which", lambda name: "/opt/npm/claude.cmd" if name == "claude" else None)
    assert H.resolved(["claude", "-p"]) == ["/opt/npm/claude.cmd", "-p"]
    assert H.resolved(["nope", "x"]) == ["nope", "x"]


# ── unparsed references are reported per arm (second cross-review of 58dbf9f; main rate changed after 9e1f399) ──

def test_unparsed_references_are_reported_per_arm(tmp_path):
    for arm, unparsed in (("A", 0), ("B", 3)):
        d = tmp_path / arm / "t5-related-work" / "r1"
        d.mkdir(parents=True)
        cites = {"n_refs": 10, "confirmed": 6, "mismatch": 1, "unconfirmed": 3, "unparsed": unparsed}
        (d / "score.json").write_text(json.dumps({"task": "t5-related-work", "missing_report": False,
                                                 "n_numbers": 0, "citations": cites}), encoding="utf-8")
    res = AG.results(tmp_path)
    # superseded by cross-review of 9e1f399 (maintainer decision): unparsed counts as bad in the main rate; the rate
    # over parsed references, which this test first asserted as the main one, is now the secondary report
    assert res["bad_cite_rate_A"] == pytest.approx(4 / 10) and res["bad_cite_rate_B"] == pytest.approx(4 / 10)
    assert res["bad_cite_rate_parsed_B"] == pytest.approx(1 / 7)
    assert res["unparsed_refs_A"] == 0 and res["unparsed_refs_B"] == 3
    assert res["bad_cite_rate_A_minus_B__n"] == 10
    assert {"unparsed_refs_A", "unparsed_refs_B"} <= V.EXPECTED_RESULT_KEYS


# ── (3) the treatment itself is frozen (frozen_trees, 62c4ee7); the environment is in every score ──

def test_prereg_freezes_the_treatment_trees():
    text = (HERE / "prereg.md").read_text(encoding="utf-8")
    assert {"plugins/rak-discipline", "plugins/rak-knowledge", "templates"} <= set(frontmatter_list(text, "frozen_trees"))


def test_verdict_refuses_a_file_added_to_a_frozen_tree(tmp_path):
    root = tmp_path / "proj"
    (root / ".rak" / "frozen").mkdir(parents=True)
    shutil.copy(HERE / "prereg.md", root / "prereg.md")
    skill = root / "plugins" / "rak-discipline" / "skills" / "gate" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# gate\n", encoding="utf-8")
    rec = {"prereg": "prereg.md", "prereg_sha256": V.sha(root / "prereg.md"),
           "verdict_sha256": V.sha(Path(V.__file__).resolve()), "commit": "0" * 40,
           "frozen_trees": {"plugins/rak-discipline": {"skills/gate/SKILL.md": V.sha(skill)}}}
    (root / ".rak" / "frozen" / f"{V.PREREG_ID}.json").write_text(json.dumps(rec), encoding="utf-8")
    assert V.frozen(root)
    (skill.parent.parent / "new").mkdir()
    (skill.parent.parent / "new" / "SKILL.md").write_text("# new\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="rak-discipline"):
        V.frozen(root)


def test_every_score_records_python_and_numpy_versions(tmp_path):
    run = tmp_path / "r1"
    run.mkdir()
    (run / "report.md").write_text("nothing\n", encoding="utf-8")
    out = S.score(HERE / "tasks" / "t1-linreg", run, check_citations=False)
    assert out["env"]["python"].count(".") == 2 and "numpy" in out["env"]
