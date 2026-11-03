"""Tests that the rak-discipline guards actually block. Run: python -m unittest discover -s tests -v

Each test builds a throwaway git repo, so nothing here touches the real project.
The hook is exercised the way Claude Code calls it: JSON on stdin, exit code 2 = blocked.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
GUARD = PLUGIN / "hooks" / "guard.py"
CLI = PLUGIN / "scripts" / "rak_discipline.py"
TEMPLATES = PLUGIN.parent.parent / "templates"

PREREG = """---
id: "demo-run"
title: "demo"
status: draft
verdict_script: "verdict.py"
created: "2026-01-01"
---

# demo

## 4. Criteria
C1: treatment_minus_control >= 0.05
"""

RESULTS = """---
title: "demo results"
updated: "2026-01-02"
---

# Results

C1 PASS: 0.071 (n=5).
The treatment arm was faster.
"""


def run(cmd, cwd, **kw):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, **kw)


class Repo:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="rakd-"))
        run(["git", "init", "-q"], self.dir)
        run(["git", "config", "user.email", "t@example.invalid"], self.dir)
        run(["git", "config", "user.name", "t"], self.dir)
        run(["git", "config", "core.autocrlf", "false"], self.dir)

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    def commit(self, *paths, msg="c"):
        run(["git", "add", "--", *paths], self.dir)
        r = run(["git", "commit", "-q", "-m", msg], self.dir)
        assert r.returncode == 0, r.stderr

    def cli(self, *args):
        return run([sys.executable, str(CLI), *args], self.dir)

    def hook(self, tool, tool_input):
        payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(self.dir),
                              "hook_event_name": "PreToolUse"})
        return run([sys.executable, str(GUARD)], self.dir, input=payload)

    def bash(self, cmd):
        return self.hook("Bash", {"command": cmd})

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def verdict_source() -> str:
    src = (TEMPLATES / "verdict.py").read_text(encoding="utf-8").replace("__PREREG_ID__", "demo-run")
    src = src.replace('    # "positive_control_recovers_known_value": ("pos_ctrl_rel_err", None, 0.05),',
                      '    "positive_control_recovers_known_value": ("pos_ctrl_rel_err", None, 0.05),')
    src = src.replace('    # "treatment_beats_control": ("treatment_minus_control", ">=", 0.05, 5),',
                      '    "treatment_beats_control": ("treatment_minus_control", ">=", 0.05, 5),')
    src = src.replace("EXPECTED_RESULT_KEYS: set[str] = set()",
                      'EXPECTED_RESULT_KEYS: set[str] = {"treatment_minus_control", "treatment_minus_control__n"}')
    src = src.replace("EXPECTED_EVIDENCE_KEYS: set[str] = set()", 'EXPECTED_EVIDENCE_KEYS: set[str] = {"pos_ctrl_rel_err"}')
    assert '"positive_control_recovers_known_value": ("pos' in src and "# \"positive" not in src
    return src


class Base(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        cfg = json.loads((TEMPLATES / "discipline.json").read_text(encoding="utf-8"))
        self.r.write(".rak/discipline.json", json.dumps(cfg))
        self.r.write("prereg.md", PREREG)
        self.r.write("verdict.py", verdict_source())
        self.r.commit(".rak/discipline.json", "prereg.md", "verdict.py")

    def tearDown(self):
        self.r.close()

    def freeze(self):
        r = self.r.cli("freeze", "prereg.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.r.commit(".rak/frozen/demo-run.json")

    def assertBlocked(self, r):
        self.assertEqual(r.returncode, 2, f"expected block, got {r.returncode}: {r.stderr}")

    def assertAllowed(self, r):
        self.assertEqual(r.returncode, 0, f"expected allow, got {r.returncode}: {r.stderr}")


SCORER = "def matches(a, b):\n    return abs(a - b) <= 0.005\n"
PREREG_WITH_FILES = PREREG.replace('verdict_script: "verdict.py"\n',
                                   'verdict_script: "verdict.py"\nfrozen_files:\n  - "score.py"\n  - "tasks/expected.json"\n')


class FrozenFiles(Base):
    """frozen_files: the scorer, thresholds and tables the verdict depends on are frozen with the prereg."""

    def setUp(self):
        super().setUp()
        self.r.write("prereg.md", PREREG_WITH_FILES)
        self.r.write("score.py", SCORER)
        self.r.write("tasks/expected.json", '{"chance": 0.05}\n')
        self.r.commit("prereg.md", "score.py", "tasks/expected.json")

    def gate_and_results(self):
        self.r.write("ev.json", json.dumps({"pos_ctrl_rel_err": 0.01}))
        self.r.write("res.json", json.dumps({"treatment_minus_control": 0.07, "treatment_minus_control__n": 5}))

    def test_freeze_records_the_listed_files(self):
        self.freeze()
        rec = json.loads((self.r.dir / ".rak/frozen/demo-run.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(rec.get("frozen_files", {})), ["score.py", "tasks/expected.json"])

    def test_loosened_scorer_blocks_experiment_launch(self):
        self.freeze()
        self.r.write("score.py", SCORER.replace("0.005", "0.05"))     # 10x looser after freezing
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_loosened_scorer_makes_verdict_refuse(self):
        self.freeze(); self.gate_and_results()
        self.assertEqual(run([sys.executable, "verdict.py", "gate", "--evidence", "ev.json"], self.r.dir).returncode, 0)
        self.r.write("score.py", SCORER.replace("0.005", "0.05"))
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json"], self.r.dir)
        self.assertNotEqual(r.returncode, 0, "verdict judged with a scorer changed after freezing")
        self.assertIn("score.py", r.stderr)
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python verdict.py judge --results res.json"))

    def test_rewritten_table_blocks_gate_too(self):
        self.freeze(); self.gate_and_results()
        self.r.write("tasks/expected.json", '{"chance": 0.5}\n')
        r = run([sys.executable, "verdict.py", "gate", "--evidence", "ev.json"], self.r.dir)
        self.assertNotEqual(r.returncode, 0, "gate ran against a table rewritten after freezing")

    def test_deleted_frozen_file_blocks(self):
        self.freeze()
        (self.r.dir / "score.py").unlink()
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_crlf_checkout_of_a_frozen_file_is_fine(self):
        self.freeze()
        p = self.r.dir / "score.py"; p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertAllowed(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_freeze_refuses_uncommitted_or_missing_or_outside_files(self):
        self.r.write("score.py", SCORER + "# local edit\n")
        r = self.r.cli("freeze", "prereg.md")
        self.assertNotEqual(r.returncode, 0); self.assertIn("score.py", r.stderr)
        self.r.commit("score.py")
        for bad in ('  - "nope.py"\n', '  - "../outside.py"\n'):
            self.r.write("prereg.md", PREREG_WITH_FILES.replace('  - "tasks/expected.json"\n', bad))
            self.r.commit("prereg.md")
            self.assertNotEqual(self.r.cli("freeze", "prereg.md").returncode, 0, bad)

    def test_inline_list_form(self):
        self.r.write("prereg.md", PREREG.replace('verdict_script: "verdict.py"\n',
                                                 'verdict_script: "verdict.py"\nfrozen_files: ["score.py", "tasks/expected.json"]\n'))
        self.r.commit("prereg.md")
        self.freeze()
        rec = json.loads((self.r.dir / ".rak/frozen/demo-run.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(rec["frozen_files"]), ["score.py", "tasks/expected.json"])


PREREG_WITH_TREE = PREREG.replace('verdict_script: "verdict.py"\n',
                                  'verdict_script: "verdict.py"\nfrozen_trees:\n  - "plugin"\n')


class FrozenTrees(Base):
    """frozen_trees: a whole folder (e.g. the plugin that is the treatment) is frozen, file by file."""

    def setUp(self):
        super().setUp()
        self.r.write("prereg.md", PREREG_WITH_TREE)
        self.r.write("plugin/skills/a/SKILL.md", "---\nname: a\n---\nsay A\n")
        self.r.write("plugin/scripts/tool.py", "print('tool')\n")
        self.r.commit("prereg.md", "plugin")

    def judge_refuses(self):
        self.r.write("ev.json", json.dumps({"pos_ctrl_rel_err": 0.01}))
        return run([sys.executable, "verdict.py", "gate", "--evidence", "ev.json"], self.r.dir).returncode != 0

    def test_freeze_records_every_file(self):
        self.freeze()
        rec = json.loads((self.r.dir / ".rak/frozen/demo-run.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(rec["frozen_trees"]["plugin"]), ["scripts/tool.py", "skills/a/SKILL.md"])

    def test_edited_file_in_tree_blocks_launch_and_verdict(self):
        self.freeze()
        self.r.write("plugin/skills/a/SKILL.md", "---\nname: a\n---\nsay B\n")
        r = self.r.bash("RAK_PREREG=demo-run python train.py")
        self.assertBlocked(r)
        self.assertIn("skills/a/SKILL.md", r.stderr)
        self.assertTrue(self.judge_refuses(), "verdict ran with the treatment changed")

    def test_added_file_in_tree_blocks(self):
        self.freeze()
        self.r.write("plugin/skills/b/SKILL.md", "---\nname: b\n---\nnew skill\n")
        r = self.r.bash("RAK_PREREG=demo-run python train.py")
        self.assertBlocked(r)
        self.assertIn("added", r.stderr)
        self.assertTrue(self.judge_refuses())

    def test_deleted_file_in_tree_blocks(self):
        self.freeze()
        (self.r.dir / "plugin/scripts/tool.py").unlink()
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py"))
        self.assertTrue(self.judge_refuses())

    def test_caches_and_crlf_are_ignored(self):
        self.freeze()
        self.r.write("plugin/scripts/__pycache__/tool.cpython-314.pyc", "bytecode")
        self.r.write("plugin/.pytest_cache/x", "cache")
        p = self.r.dir / "plugin/scripts/tool.py"; p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertAllowed(self.r.bash("RAK_PREREG=demo-run python train.py"))
        self.assertFalse(self.judge_refuses())

    def test_freeze_refuses_dirty_untracked_missing_or_outside(self):
        self.r.write("plugin/skills/c/SKILL.md", "untracked\n")
        r = self.r.cli("freeze", "prereg.md")
        self.assertNotEqual(r.returncode, 0); self.assertIn("plugin", r.stderr)
        (self.r.dir / "plugin/skills/c/SKILL.md").unlink()
        for bad in ('  - "nope"\n', '  - "../outside"\n', '  - "verdict.py"\n'):
            self.r.write("prereg.md", PREREG_WITH_TREE.replace('  - "plugin"\n', bad))
            self.r.commit("prereg.md")
            self.assertNotEqual(self.r.cli("freeze", "prereg.md").returncode, 0, bad)


class Rule1ExperimentNeedsFrozenPrereg(Base):
    def test_no_token_blocked(self):
        self.assertBlocked(self.r.bash("python train.py --seed 101"))

    def test_token_but_not_frozen_blocked(self):
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py --seed 101"))

    def test_frozen_allowed(self):
        self.freeze()
        self.assertAllowed(self.r.bash("RAK_PREREG=demo-run python train.py --seed 101"))

    def test_vm_create_counts_as_experiment(self):
        self.assertBlocked(self.r.bash("bash create_vm.sh --yes"))
        self.assertAllowed(self.r.bash("bash create_vm.sh"))  # dry-run is not a launch

    def test_prereg_edited_after_freeze_blocked(self):
        self.freeze()
        self.r.write("prereg.md", PREREG.replace(">= 0.05", ">= 0.03"))
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_verdict_script_edited_after_freeze_blocked(self):
        self.freeze()
        self.r.write("verdict.py", verdict_source().replace("0.05, 5)", "0.03, 5)"))
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_crlf_checkout_does_not_unfreeze(self):
        self.freeze()
        p = self.r.dir / "prereg.md"
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        self.assertAllowed(self.r.bash("RAK_PREREG=demo-run python train.py"))

    def test_refreeze_refused(self):
        self.freeze()
        self.assertNotEqual(self.r.cli("freeze", "prereg.md").returncode, 0)

    def test_freeze_requires_committed_file(self):
        self.r.write("prereg.md", PREREG + "\nlate edit\n")
        r = self.r.cli("freeze", "prereg.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)

    def test_unrelated_command_allowed(self):
        self.assertAllowed(self.r.bash("ls -la && git status"))


class Rule2VerdictNeedsGatePass(Base):
    def evidence(self, err):
        self.r.write("ev.json", json.dumps({"pos_ctrl_rel_err": err}))
        return run([sys.executable, "verdict.py", "gate", "--evidence", "ev.json"], self.r.dir)

    def results(self):
        self.r.write("res.json", json.dumps({"treatment_minus_control": 0.071, "treatment_minus_control__n": 5}))

    def test_judge_before_gate_blocked_by_hook_and_by_script(self):
        self.freeze(); self.results()
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python verdict.py judge --results res.json"))
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json"], self.r.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GATE_FAIL", r.stderr)

    def test_gate_fail_blocks(self):
        self.freeze(); self.results()
        self.assertEqual(self.evidence(0.20).returncode, 1)
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python verdict.py judge --results res.json"))
        self.assertNotEqual(run([sys.executable, "verdict.py", "judge", "--results", "res.json"], self.r.dir).returncode, 0)

    def test_gate_pass_allows_and_judges(self):
        self.freeze(); self.results()
        self.assertEqual(self.evidence(0.01).returncode, 0)
        self.assertAllowed(self.r.bash("RAK_PREREG=demo-run python verdict.py judge --results res.json"))
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json", "--out", "v.json"], self.r.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        v = json.loads((self.r.dir / "v.json").read_text(encoding="utf-8"))
        self.assertEqual(v["verdicts"]["treatment_beats_control"]["verdict"], "PASS")
        self.assertIn("verdict_sha256", v)
        r2 = run([sys.executable, "verdict.py", "judge", "--results", "res.json", "--out", "v.json"], self.r.dir)
        self.assertNotEqual(r2.returncode, 0, "verdict file must be written once")

    def test_gate_exactly_at_threshold_is_not_rounded(self):
        self.freeze()
        self.assertEqual(self.evidence(0.0500001).returncode, 1)  # 0.0500001 > 0.05: FAIL, even if it prints as 0.05

    def test_unknown_result_key_raises(self):
        self.freeze(); self.assertEqual(self.evidence(0.01).returncode, 0)
        self.r.write("res.json", json.dumps({"treatment_minus_control": 0.07, "treatment_minus_control__n": 5, "renamed_metric": 1}))
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json"], self.r.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not registered", r.stderr)

    def test_small_n_is_undetermined(self):
        self.freeze(); self.assertEqual(self.evidence(0.01).returncode, 0)
        self.r.write("res.json", json.dumps({"treatment_minus_control": 0.2, "treatment_minus_control__n": 2}))
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json", "--out", "v.json"], self.r.dir)
        v = json.loads((self.r.dir / "v.json").read_text(encoding="utf-8"))
        self.assertEqual(v["verdicts"]["treatment_beats_control"]["verdict"], "UNDETERMINED")

    def test_unknown_flag_raises(self):
        self.freeze()
        r = run([sys.executable, "verdict.py", "judge", "--results", "res.json", "--seed", "1"], self.r.dir)
        self.assertNotEqual(r.returncode, 0)

    def test_stale_gate_blocked(self):
        self.freeze(); self.assertEqual(self.evidence(0.01).returncode, 0)
        g = self.r.dir / ".rak/gates/demo-run.json"
        d = json.loads(g.read_text(encoding="utf-8")); d["prereg_sha256"] = "0" * 64
        g.write_text(json.dumps(d), encoding="utf-8")
        self.assertBlocked(self.r.bash("RAK_PREREG=demo-run python verdict.py judge --results res.json"))


class Rule3ResultsAppendOnly(Base):
    def setUp(self):
        super().setUp()
        self.r.write("docs/results/demo.md", RESULTS)
        self.r.commit("docs/results/demo.md")
        self.path = str(self.r.dir / "docs/results/demo.md")

    def test_append_erratum_allowed(self):
        self.assertAllowed(self.r.hook("Edit", {"file_path": self.path, "old_string": "The treatment arm was faster.\n",
                                                "new_string": "The treatment arm was faster.\n\n## Erratum 1\n> The treatment arm was faster.\n\nIt was not.\n"}))

    def test_rewrite_committed_line_blocked(self):
        self.assertBlocked(self.r.hook("Edit", {"file_path": self.path, "old_string": "C1 PASS: 0.071 (n=5).",
                                                "new_string": "C1 PASS: 0.068 (n=5)."}))

    def test_delete_committed_line_blocked(self):
        self.assertBlocked(self.r.hook("Edit", {"file_path": self.path, "old_string": "The treatment arm was faster.\n", "new_string": ""}))

    def test_write_over_blocked(self):
        self.assertBlocked(self.r.hook("Write", {"file_path": self.path, "content": "# Results\n\nall good\n"}))

    def test_write_that_keeps_everything_allowed(self):
        self.assertAllowed(self.r.hook("Write", {"file_path": self.path, "content": RESULTS + "\n## Erratum 1\nmore\n"}))

    def test_multiedit_blocked_if_any_edit_rewrites(self):
        self.assertBlocked(self.r.hook("MultiEdit", {"file_path": self.path, "edits": [
            {"old_string": "faster.", "new_string": "faster.\nadded"},
            {"old_string": "0.071", "new_string": "0.07"}]}))

    def test_frontmatter_change_allowed(self):
        self.assertAllowed(self.r.hook("Edit", {"file_path": self.path, "old_string": 'updated: "2026-01-02"', "new_string": 'updated: "2026-01-09"'}))

    def test_uncommitted_draft_is_free(self):
        self.r.write("docs/results/draft.md", RESULTS)
        self.assertAllowed(self.r.hook("Write", {"file_path": str(self.r.dir / "docs/results/draft.md"), "content": "rewritten\n"}))

    def test_non_results_file_free(self):
        self.r.write("notes.md", "a\n"); self.r.commit("notes.md")
        self.assertAllowed(self.r.hook("Write", {"file_path": str(self.r.dir / "notes.md"), "content": "b\n"}))

    def test_bash_inplace_edit_and_delete_blocked(self):
        self.assertBlocked(self.r.bash("sed -i 's/0.071/0.068/' docs/results/demo.md"))
        self.assertBlocked(self.r.bash("rm docs/results/demo.md"))
        self.assertBlocked(self.r.bash("git rm docs/results/demo.md"))
        self.assertBlocked(self.r.bash("echo x > docs/results/demo.md"))
        self.assertAllowed(self.r.bash("cat docs/results/demo.md"))
        self.assertAllowed(self.r.bash("echo erratum >> docs/results/demo.md"))

    # --- known gap of the hook, and the second line of defence that closes it ---
    def test_known_gap_python_write_passes_hook_but_precommit_blocks(self):
        cmd = f"{Path(sys.executable).name} -c \"import pathlib; pathlib.Path('docs/results/demo.md').write_text('gone')\""
        self.assertAllowed(self.r.bash(cmd))  # documented limit: the hook cannot see inside a python one-liner
        (self.r.dir / "docs/results/demo.md").write_text("gone\n", encoding="utf-8")
        run(["git", "add", "docs/results/demo.md"], self.r.dir)
        r = self.r.cli("check-append-only", "--staged")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("removed or rewritten", r.stderr)

    def test_installed_precommit_hook_rejects_commit(self):
        self.assertEqual(self.r.cli("install-git-hook").returncode, 0)
        (self.r.dir / "docs/results/demo.md").write_text(RESULTS.replace("0.071", "0.068"), encoding="utf-8")
        run(["git", "add", "docs/results/demo.md"], self.r.dir)
        r = run(["git", "commit", "-q", "-m", "rewrite"], self.r.dir)
        self.assertNotEqual(r.returncode, 0, "pre-commit should have rejected the rewrite")
        (self.r.dir / "docs/results/demo.md").write_text(RESULTS + "\n## Erratum 1\nok\n", encoding="utf-8")
        run(["git", "add", "docs/results/demo.md"], self.r.dir)
        self.assertEqual(run(["git", "commit", "-q", "-m", "erratum"], self.r.dir).returncode, 0)

    def test_precommit_blocks_deleting_results_doc(self):
        run(["git", "rm", "-q", "docs/results/demo.md"], self.r.dir)
        self.assertEqual(self.r.cli("check-append-only", "--staged").returncode, 1)


class GuardBehaviour(unittest.TestCase):
    def test_no_config_means_no_op(self):
        r = Repo()
        try:
            self.assertEqual(r.bash("python train.py").returncode, 0)
        finally:
            r.close()

    def test_bad_config_fails_closed(self):
        r = Repo()
        try:
            r.write(".rak/discipline.json", json.dumps({"experiment_pattern": ["train"]}))  # typo'd key
            self.assertEqual(r.bash("python train.py").returncode, 2)
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
