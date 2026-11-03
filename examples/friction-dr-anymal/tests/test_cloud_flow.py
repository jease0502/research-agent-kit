"""Whole cloud flow on a laptop: freeze -> prepare_job -> vm_job.sh with this example's steps (fake gcloud, fake Isaac)
-> rak-cloud waiter pulls, verifies against the manifest, deletes.

Real code everywhere except the physics: rak_discipline freeze, prepare_job, rak-cloud's vm_job.sh, the example's
train/evaluate argument handling and checks, aggregate.py, verdict.py, rak_cloud.Waiter.
Needs bash with coreutils (Linux, or Git Bash on Windows; RAK_TEST_BASH to choose); skipped otherwise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

EX = Path(__file__).resolve().parent.parent
REPO = EX.parent.parent
FAKE_GCLOUD = REPO / "plugins/rak-cloud/tests/fake_gcloud.py"
FAKE_ISAAC = Path(__file__).resolve().parent / "fake_isaac.py"
DISC = REPO / "plugins/rak-discipline/scripts/rak_discipline.py"
sys.path.insert(0, str(REPO / "plugins/rak-cloud/scripts"))
sys.path.insert(0, str(EX / "cloud"))


def find_bash():
    if os.environ.get("RAK_TEST_BASH"):
        return os.environ["RAK_TEST_BASH"]
    if os.name == "nt":
        for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if os.path.exists(c):
                return c
        return None
    return shutil.which("bash")


BASH = find_bash()
P = lambda p: str(p).replace("\\", "/")  # noqa: E731


def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


@unittest.skipUnless(BASH and FAKE_GCLOUD.exists(), "needs bash and the rak-cloud plugin")
class CloudFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """One frozen repo + job folder for all cases (freezing is the slow, shared part)."""
        cls.t = Path(tempfile.mkdtemp(prefix="rakflow-"))
        cls.repo = cls.t / "repo"; ex = cls.repo / "examples/friction-dr-anymal"
        shutil.copytree(EX, ex, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests", "frozen", "gates"))
        (cls.repo / "templates/cloud").mkdir(parents=True)
        shutil.copy(REPO / "templates/cloud/vm_job.sh", cls.repo / "templates/cloud/vm_job.sh")
        for c in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"],
                  ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-q", "-m", "example"]):
            assert run(["git", *c], cls.repo).returncode == 0
        r = run([sys.executable, str(DISC), "freeze", "docs/prereg/friction-dr-anymal.md"], ex)
        assert r.returncode == 0, r.stderr
        assert run(["git", "add", "-A"], cls.repo).returncode == 0
        assert run(["git", "commit", "-q", "-m", "freeze"], cls.repo).returncode == 0
        import prepare_job
        cls.job = cls.t / "job"
        cls.info = prepare_job.prepare(cls.repo, cls.job, cls.repo / "templates/cloud/vm_job.sh")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.t, ignore_errors=True)

    def setUp(self):
        self.w = Path(tempfile.mkdtemp(prefix="rakflow-run-", dir=self.t))
        self.fake = self.w / "fake"; code = self.fake / "gcs/fake-bkt/rak/vm1/code"; code.mkdir(parents=True)
        shutil.copy(self.job / "code.tgz", code); shutil.copy(self.job / "code.sha256", code)
        (self.fake / "config.json").write_text("{}")
        (self.fake / "instances.json").write_text(json.dumps({"vm1": {"zone": "z-a", "status": "RUNNING"}}))
        self.bin = self.w / "bin"; self.bin.mkdir()
        for name, target in (("gcloud", FAKE_GCLOUD), ("expy", FAKE_ISAAC)):
            (self.bin / name).write_text(f'#!/usr/bin/env bash\nexec "{P(sys.executable)}" "{P(target)}" "$@"\n', newline="\n")
        (self.bin / "syspy").write_text(f'#!/usr/bin/env bash\nexec "{P(sys.executable)}" "$@"\n', newline="\n")
        (self.bin / "fake_install").write_text('#!/usr/bin/env bash\necho "isaacsim==5.1.0 (fake)"\n', newline="\n")
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.out = self.w / "out"; self.state = self.w / "state"; self.state.mkdir()

    def vm(self, world=None, steps=None, timeout=600):
        env = dict(os.environ, FAKE_GCLOUD_DIR=P(self.fake), RAK_OUT_URL="gs://fake-bkt/rak/vm1/out",
                   RAK_STEPS=P(steps or self.job / "steps.sh"), OUT=P(self.out), RAKSTATE=P(self.state),
                   RAK_SKIP_GPU="1", RAK_SELFCHECK_CMD="printf DELETE_OK\\nWRITE_OK\\n", STOP_POLL="0.2",
                   SYNC_BACKOFF="0", HB_EVERY="1", SYNC_EVERY="3600", EX_PY=P(self.bin / "expy"),
                   SYS_PY=P(self.bin / "syspy"), EX_INSTALL=P(self.bin / "fake_install"), FAKE_WORLD=json.dumps(world or {}))
        if os.name == "nt":
            env["PATH"] = "/" + P(self.bin).replace(":", "", 1) + ":/usr/bin:/bin:" + os.environ["PATH"].replace("\\", "/")
        else:
            env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        r = subprocess.run([BASH, P(self.job / "vm_job.sh")], env=env, capture_output=True, text=True, timeout=timeout)
        st = self.fake / "gcs/fake-bkt/rak/vm1/out/status.txt"
        return r, (st.read_text().strip() if st.exists() else None)

    def gcs(self, rel):
        return self.fake / "gcs/fake-bkt/rak/vm1/out" / rel

    def steps_run(self):
        f = self.gcs("steps.tsv")
        return [ln.split("\t")[0] for ln in f.read_text().splitlines()] if f.exists() else []

    # ---- the whole chain
    def test_full_flow_then_waiter_verifies_and_deletes(self):
        r, st = self.vm()
        self.assertEqual(st, "DONE", r.stdout[-3000:] + r.stderr[-2000:])
        steps = self.steps_run()
        self.assertEqual(len([s for s in steps if s.startswith("TRAIN_")]), 10)
        self.assertEqual(len([s for s in steps if s.startswith("EVAL_")]), 31)
        v = json.loads(self.gcs("verdict.json").read_text())
        self.assertEqual({k: x["verdict"] for k, x in v["verdicts"].items()},
                         {"C1_low_friction_gain": "PASS", "C1b_seed_pairs_agree": "PASS", "C2_nominal_noninferior": "PASS"})
        self.assertEqual(self.gcs("gate_status.txt").read_text().strip(), "0")
        # rak-cloud's waiter: pull, verify every file against the manifest, delete, confirm gone
        import rak_cloud as rc
        os.environ["FAKE_GCLOUD_DIR"] = str(self.fake)
        os.environ["RAK_GCLOUD"] = json.dumps([sys.executable, str(FAKE_GCLOUD)])
        root = self.w / "proj"; (root / ".rak").mkdir(parents=True)
        cfg = {"account": "a@example.com", "project": "p", "bucket": "gs://fake-bkt/rak", "price_per_vm_hour": 1.0,
               "report_at_usd": 8, "stop_at_usd": 12, "stall_min": 45, "stop_wait_min": 25, "local_dir": str(self.w / "pulled")}
        rc.record_instance(root, "vm1", "z-a")
        lines = []
        w = rc.Waiter(cfg, rc.Gcloud(cfg), root, "vm1", out=lines.append)
        self.assertEqual(w.poll(), "done", lines)
        self.assertTrue(any(l.startswith("PULLED_OK") for l in lines) and any(l.startswith("DELETED") for l in lines), lines)
        self.assertEqual(json.loads((self.fake / "instances.json").read_text()), {})
        self.assertTrue((self.w / "pulled/vm1/verdict.json").is_file())

    # ---- the declaration pass: what a VM owes is published before the first step
    def test_required_lists_every_output_including_the_judge(self):
        r, st = self.vm(world={"preflight_dev": 0.5})      # stops early; the list was published before that
        self.assertEqual(st, "FAIL_PREFLIGHT_G1_RC", r.stdout[-2000:])
        lines = self.gcs("REQUIRED.txt").read_text().splitlines()
        self.assertEqual(lines[0], "# rak-required v1")
        # verdict.json matters most: a run_steps that returns early when gate_status.txt is absent would drop it here
        for must in ("code/COMMIT", "budget.json", "runs/train/treatment-9105/DONE", "runs/eval/zero__default.json",
                     "gate_status.txt", "verdict.json"):
            self.assertIn(must, lines)
        self.assertEqual(len(lines) - 1, 61)   # 5 setup + 20 train + 31 eval + 2 aggregate + 2 gate + 1 judge

    # ---- fail early, before money is spent
    def test_preflight_g1_stops_before_training(self):
        r, st = self.vm(world={"preflight_dev": 0.5})
        self.assertEqual(st, "FAIL_PREFLIGHT_G1_RC", r.stdout[-2000:])
        self.assertFalse(any(s.startswith(("SMOKE", "TRAIN_")) for s in self.steps_run()))

    def test_budget_rule_stops_before_main_training(self):
        r, st = self.vm(world={"smoke_learn_s": 600.0})   # 12 s/iteration -> about 10 h of training
        self.assertEqual(st, "FAIL_BUDGET_RC", r.stdout[-2000:])
        b = json.loads(self.gcs("budget.json").read_text())
        self.assertTrue(b["over"]); self.assertGreater(b["total_h"], 8.0)
        self.assertFalse(any(s.startswith("TRAIN_") for s in self.steps_run()))

    def test_tampered_code_is_refused(self):
        code = self.fake / "gcs/fake-bkt/rak/vm1/code/code.tgz"
        code.write_bytes(code.read_bytes()[:-10] + b"0123456789")
        r, st = self.vm()
        self.assertEqual(st, "FAIL_FETCH_NO_OUTPUT", r.stdout[-2000:])

    def test_gate_failure_means_no_verdict(self):
        r, st = self.vm(world={"ice": 0.90})               # the metric cannot see ice: G2 fails
        self.assertEqual(st, "DONE", r.stdout[-2000:])
        self.assertEqual(self.gcs("gate_status.txt").read_text().strip(), "1")
        self.assertIn("FAIL  G2_ice_drop", self.gcs("gate_stdout.txt").read_text())
        self.assertFalse(self.gcs("verdict.json").exists())
        self.assertNotIn("JUDGE", self.steps_run())


class PrepareRefusals(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="rakprep-"))
        self.repo = self.t / "repo"; self.ex = self.repo / "examples/friction-dr-anymal"
        shutil.copytree(EX, self.ex, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "tests", "frozen", "gates"))
        for c in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"],
                  ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
            run(["git", *c], self.repo)
        import prepare_job
        self.pj = prepare_job

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def test_not_frozen(self):
        with self.assertRaisesRegex(self.pj.PrepareError, "not frozen"):
            self.pj.prepare(self.repo, self.t / "job", REPO / "templates/cloud/vm_job.sh")

    def test_dirty_tree(self):
        (self.ex / "README.md").write_text("edited\n")
        with self.assertRaisesRegex(self.pj.PrepareError, "uncommitted"):
            self.pj.prepare(self.repo, self.t / "job", REPO / "templates/cloud/vm_job.sh")

    def test_frozen_scorer_changed_at_head_is_refused(self):
        run([sys.executable, str(DISC), "freeze", "docs/prereg/friction-dr-anymal.md"], self.ex)
        run(["git", "add", "-A"], self.repo); run(["git", "commit", "-q", "-m", "freeze"], self.repo)
        core = self.ex / "experiments/friction-dr-anymal/core.py"
        core.write_text(core.read_text(encoding="utf-8").replace("mean <= self.max_err", "mean <= 10 * self.max_err"),
                        encoding="utf-8", newline="\n")
        run(["git", "commit", "-q", "-am", "loosen the success rule after freezing"], self.repo)
        with self.assertRaisesRegex(self.pj.PrepareError, "core.py"):
            self.pj.prepare(self.repo, self.t / "job", REPO / "templates/cloud/vm_job.sh")

    def test_frozen_tree_changed_at_head_is_refused(self):
        pr = self.ex / "docs/prereg/friction-dr-anymal.md"
        pr.write_text(pr.read_text(encoding="utf-8").replace(
            "created:", 'frozen_trees:\n  - "experiments/friction-dr-anymal"\ncreated:', 1), encoding="utf-8", newline="\n")
        run(["git", "commit", "-q", "-am", "freeze the whole experiment folder"], self.repo)
        r = run([sys.executable, str(DISC), "freeze", "docs/prereg/friction-dr-anymal.md"], self.ex)
        self.assertEqual(r.returncode, 0, r.stderr)
        run(["git", "add", "-A"], self.repo); run(["git", "commit", "-q", "-m", "freeze"], self.repo)
        train = self.ex / "experiments/friction-dr-anymal/train.py"           # inside the tree, not in frozen_files
        train.write_text(train.read_text(encoding="utf-8") + "\n# changed after freezing\n", encoding="utf-8", newline="\n")
        run(["git", "commit", "-q", "-am", "edit train.py after freezing"], self.repo)
        with self.assertRaisesRegex(self.pj.PrepareError, "train.py"):
            self.pj.prepare(self.repo, self.t / "job", REPO / "templates/cloud/vm_job.sh")

    def test_archive_carries_the_commit(self):
        run([sys.executable, str(DISC), "freeze", "docs/prereg/friction-dr-anymal.md"], self.ex)
        run(["git", "add", "-A"], self.repo); run(["git", "commit", "-q", "-m", "freeze"], self.repo)
        info = self.pj.prepare(self.repo, self.t / "job", REPO / "templates/cloud/vm_job.sh")
        with tarfile.open(self.t / "job/code.tgz") as tf:
            self.assertEqual(tf.extractfile("COMMIT").read().decode().strip(), info["commit"])
        self.assertIn(info["commit"], (self.t / "job/steps.sh").read_text())
        self.assertNotIn("@@COMMIT@@", (self.t / "job/steps.sh").read_text())


if __name__ == "__main__":
    unittest.main()
