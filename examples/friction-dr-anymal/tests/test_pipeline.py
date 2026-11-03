"""End to end on CPU with fake evaluation summaries: aggregate -> verdict gate -> verdict judge.

Uses the example's own verdict.py, frozen in a throwaway copy, so the registered keys of aggregate.py
and verdict.py are checked against each other.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EX = Path(__file__).resolve().parent.parent
EXP = EX / "experiments" / "friction-dr-anymal"
sys.path.insert(0, str(EXP))
import aggregate  # noqa: E402
import core  # noqa: E402
import protocol as P  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="rakfr-"))
        shutil.copytree(EX, self.d / "ex", ignore=shutil.ignore_patterns("__pycache__", "tests"))
        self.ex = self.d / "ex"
        self.evals = self.d / "evals"; self.evals.mkdir()
        rec = {"id": P.PREREG_ID, "prereg": "docs/prereg/friction-dr-anymal.md",
               "prereg_sha256": sha(self.ex / "docs/prereg/friction-dr-anymal.md"),
               "verdict_script": "experiments/friction-dr-anymal/verdict.py",
               "verdict_sha256": sha(self.ex / "experiments/friction-dr-anymal/verdict.py"), "commit": "0" * 40}
        (self.ex / ".rak/frozen").mkdir(parents=True)
        (self.ex / ".rak/frozen" / f"{P.PREREG_ID}.json").write_text(json.dumps(rec))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def summary(self, arm, seed, mu, success, mat_dev=0.0, ground=1.0, **over):
        s = {"policy": {"arm": arm, "seed": seed}, "mu": mu, "n_episodes": P.episodes_per_policy(),
             "success_rate": success, "fall_rate": 0.0, "mean_track_err": 0.1, "command_violations": 0,
             "materials": {"robot_static_max_abs_dev": mat_dev, "robot_dynamic_max_abs_dev": mat_dev,
                           "ground_static": ground, "ground_dynamic": ground},
             "eval_seed": P.EVAL_SEED, **core.provenance()}
        s.update(over)
        name = f"{arm}-{seed}__{'default' if mu is None else mu}.json"
        (self.evals / name).write_text(json.dumps(s))

    def full_set(self, ctrl03=0.40, treat03=0.70, ctrl08=0.92, treat08=0.90, mat_dev=0.0, ice=0.10):
        for s in P.TRAIN_SEEDS:
            self.summary("control", s, 0.3, ctrl03, mat_dev)
            self.summary("treatment", s, 0.3, treat03, mat_dev)
            self.summary("control", s, 0.8, ctrl08, mat_dev)
            self.summary("treatment", s, 0.8, treat08, mat_dev)
            self.summary("control", s, 0.05, ice, mat_dev)
            self.summary("control", s, None, ctrl08 + 0.01)
        self.summary("zero", None, None, 0.0)

    def run_chain(self):
        gate = self.d / "gate.json"; res = self.d / "res.json"
        aggregate.main(["--evals", str(self.evals), "--gate-out", str(gate), "--results-out", str(res)])
        v = self.ex / "experiments/friction-dr-anymal/verdict.py"
        g = subprocess.run([sys.executable, str(v), "gate", "--evidence", str(gate)], cwd=self.ex, capture_output=True, text=True)
        j = subprocess.run([sys.executable, str(v), "judge", "--results", str(res), "--out", str(self.d / "verdict.json")],
                           cwd=self.ex, capture_output=True, text=True)
        return g, j

    def test_expected_world_passes_everything(self):
        self.full_set()
        g, j = self.run_chain()
        self.assertEqual(g.returncode, 0, g.stdout + g.stderr)
        self.assertEqual(j.returncode, 0, j.stdout + j.stderr)
        v = json.loads((self.d / "verdict.json").read_text())["verdicts"]
        self.assertEqual({k: x["verdict"] for k, x in v.items()},
                         {"C1_low_friction_gain": "PASS", "C1b_seed_pairs_agree": "PASS", "C2_nominal_noninferior": "PASS"})

    def test_override_not_applied_fails_gate_and_blocks_judge(self):
        self.full_set(mat_dev=0.5)        # the engine kept the default material
        g, j = self.run_chain()
        self.assertEqual(g.returncode, 1)
        self.assertIn("FAIL  G1_friction_applied", g.stdout)
        self.assertNotEqual(j.returncode, 0)
        self.assertIn("GATE_FAIL", j.stderr)

    def test_criterion_blind_to_ice_fails_gate(self):
        self.full_set(ice=0.90)           # metric does not see a known effect
        g, _ = self.run_chain()
        self.assertEqual(g.returncode, 1)
        self.assertIn("FAIL  G2_ice_drop", g.stdout)

    def test_missing_seed_is_undetermined_not_pass(self):
        self.full_set()
        (self.evals / "treatment-9105__0.3.json").unlink()
        g, j = self.run_chain()
        self.assertEqual(j.returncode, 0, j.stderr)
        v = json.loads((self.d / "verdict.json").read_text())["verdicts"]
        self.assertEqual(v["C1_low_friction_gain"]["verdict"], "UNDETERMINED")
        self.assertEqual(v["C1b_seed_pairs_agree"]["verdict"], "UNDETERMINED")

    def test_aggregate_rejects_foreign_protocol_and_bad_counts(self):
        self.summary("control", 9101, 0.3, 0.5, protocol_sha256="0" * 64)
        with self.assertRaises(core.ProtocolError):
            aggregate.load(self.evals)
        for f in self.evals.iterdir():
            f.unlink()
        self.summary("control", 9101, 0.3, 0.5, n_episodes=1000)
        with self.assertRaises(core.ProtocolError):
            aggregate.load(self.evals)
        for f in self.evals.iterdir():
            f.unlink()
        self.summary("control", 1234, 0.3, 0.5)
        with self.assertRaises(core.ProtocolError):
            aggregate.load(self.evals)

    def test_values_are_not_rounded(self):
        self.full_set(ctrl03=0.40, treat03=0.5500001)   # diff 0.1500001 >= 0.15
        _, j = self.run_chain()
        v = json.loads((self.d / "verdict.json").read_text())["verdicts"]
        self.assertEqual(v["C1_low_friction_gain"]["verdict"], "PASS")
        self.assertGreater(v["C1_low_friction_gain"]["value"], 0.15)


if __name__ == "__main__":
    unittest.main()
