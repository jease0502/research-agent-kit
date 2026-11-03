"""VM-side scripts (vm_job.sh, idle_check.sh) run under bash with a fake gcloud and fake nvidia-smi.
Needs a bash with coreutils (Linux, or Git Bash on Windows; set RAK_TEST_BASH to choose). Skipped otherwise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
TPL = PLUGIN.parent.parent / "templates" / "cloud"
FAKE = Path(__file__).resolve().parent / "fake_gcloud.py"


def find_bash():
    if os.environ.get("RAK_TEST_BASH"):
        return os.environ["RAK_TEST_BASH"]
    if os.name == "nt":  # System32\bash.exe is WSL and cannot run Windows python; use Git Bash
        for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if os.path.exists(c):
                return c
        return None
    return shutil.which("bash")


BASH = find_bash()
P = lambda p: str(p).replace("\\", "/")  # noqa: E731


@unittest.skipUnless(BASH, "no suitable bash")
class VmSide(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="rakv-"))
        self.fake = self.t / "fake"; (self.fake / "gcs/fake-bkt/rak/vm1").mkdir(parents=True)
        (self.fake / "config.json").write_text("{}")
        self.bin = self.t / "bin"; self.bin.mkdir()
        (self.bin / "gcloud").write_text(f'#!/usr/bin/env bash\nexec "{P(sys.executable)}" "{P(FAKE)}" "$@"\n', newline="\n")
        (self.bin / "nvidia-smi").write_text('#!/usr/bin/env bash\necho "${FAKE_GPU_UTIL:-0}"\n', newline="\n")
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.out = self.t / "out"; self.state = self.t / "state"; self.state.mkdir()

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def env(self, **kw):
        e = dict(os.environ, FAKE_GCLOUD_DIR=P(self.fake), PATH=P(self.bin) + os.pathsep + os.environ["PATH"])
        if os.name == "nt":  # Git Bash expects a POSIX-ish PATH entry for the fake bin
            e["PATH"] = "/" + P(self.bin).replace(":", "", 1) + ":" + "/usr/bin:/bin:" + os.environ["PATH"].replace("\\", "/")
        e.update({k: str(v) for k, v in kw.items()})
        return e

    def knob(self, **kw):
        (self.fake / "config.json").write_text(json.dumps(kw))

    def gcs(self, rel):
        return self.fake / "gcs/fake-bkt/rak/vm1" / rel

    def job(self, steps: str, timeout=120, **kw):
        sf = self.t / "steps.sh"; sf.write_text(steps, newline="\n")
        env = self.env(RAK_OUT_URL="gs://fake-bkt/rak/vm1/out", RAK_STEPS=P(sf), OUT=P(self.out), RAKSTATE=P(self.state),
                       RAK_SKIP_GPU=1, RAK_SELFCHECK_CMD=kw.pop("selfcheck", "printf DELETE_OK\\nWRITE_OK\\n"),
                       STOP_POLL=1, SYNC_BACKOFF=0, HB_EVERY=1, SYNC_EVERY=3600, TERM="unknown", **kw)
        r = subprocess.run([BASH, P(TPL / "vm_job.sh")], env=env, capture_output=True, text=True, timeout=timeout)
        st = self.gcs("out/status.txt")
        return r, (st.read_text().strip() if st.exists() else None)

    # ---- vm_job.sh
    def test_done_with_manifest_and_term(self):
        r, st = self.job('run_steps() { step A 60 "a.txt" -- \'echo "$TERM" > a.txt\'; }\n')
        self.assertEqual(st, "DONE", r.stdout + r.stderr)
        self.assertEqual(self.gcs("out/a.txt").read_text().strip(), "xterm")   # TERM=unknown in, xterm in the step
        sys.path.insert(0, str(PLUGIN / "scripts"))
        import rak_cloud
        pulled = self.t / "pulled"; shutil.copytree(self.gcs("out"), pulled)
        self.assertEqual(rak_cloud.verify_pull(pulled), [])   # the waiter accepts what the job wrote
        (pulled / "a.txt").write_text("changed\n")
        self.assertTrue(rak_cloud.verify_pull(pulled))

    def test_exit_zero_without_output_fails(self):   # a framework that swallows its exception and exits 0
        r, st = self.job('run_steps() { step TRAIN 60 "model.pt" -- \'echo "Error executing task"; exit 0\'; }\n')
        self.assertEqual(st, "FAIL_TRAIN_NO_OUTPUT", r.stdout)

    def test_stale_output_does_not_count(self):
        self.out.mkdir(parents=True); (self.out / "eval.json").write_text("{} from an earlier run")
        time.sleep(1.1)
        r, st = self.job('run_steps() { step EVAL 60 "eval.json" -- true; }\n')
        self.assertEqual(st, "FAIL_EVAL_NO_OUTPUT", r.stdout)

    def test_nonzero_rc_with_output_fails(self):
        r, st = self.job('run_steps() { step D 60 "d.txt" -- \'echo x > d.txt; exit 3\'; }\n')
        self.assertEqual(st, "FAIL_D_RC")

    def test_step_timeout(self):
        r, st = self.job('run_steps() { step F 1 "f.txt" -- \'sleep 5; echo > f.txt\'; }\n')
        self.assertEqual(st, "FAIL_F_TIMEOUT")

    def test_selfcheck_blocks_everything(self):
        r, st = self.job('run_steps() { step A 60 "a.txt" -- \'echo > a.txt\'; }\n', selfcheck="echo WRITE_OK")
        self.assertEqual(st, "FAIL_SELFCHECK_DELETE_PERMISSION")
        self.assertFalse((self.out / "a.txt").exists())
        r, st = self.job('run_steps() { :; }\n', selfcheck="echo DELETE_OK")
        self.assertEqual(st, "FAIL_SELFCHECK_WRITE_PERMISSION")

    def test_stop_request(self):
        self.gcs("control").mkdir(parents=True); self.gcs("control/stop").write_text("stop")
        r, st = self.job('run_steps() { step LONG 60 "x.txt" -- \'sleep 30; echo > x.txt\'; step NEVER 60 "y" -- \'echo > y\'; }\n', timeout=40)
        self.assertEqual(st, "STOPPED_SYNCED", r.stdout)
        self.assertTrue(self.gcs("out/MANIFEST.sha256").exists())
        self.assertFalse((self.out / "y").exists())

    def test_stop_really_stops_the_running_step(self):
        """The stop must kill the step's process tree, not only the subshell around it: otherwise training
        keeps running (and writing, and holding the GPU) after STOPPED_SYNCED."""
        self.gcs("control").mkdir(parents=True); self.gcs("control/stop").write_text("stop")
        r, st = self.job('run_steps() { step LONG 60 "late.txt" -- \'sleep 3; echo late > late.txt\'; }\n', timeout=40)
        self.assertEqual(st, "STOPPED_SYNCED", r.stdout)
        time.sleep(5)                                     # longer than the step would have taken
        self.assertFalse((self.out / "late.txt").exists(), "the stopped step kept running and wrote its output")

    def test_unverifiable_sync_is_fail_sync(self):
        self.knob(rsync_drop=["a.txt"])
        r, st = self.job('run_steps() { step A 60 "a.txt" -- \'echo > a.txt\'; }\n')
        self.assertEqual(st, "FAIL_SYNC")

    def test_missing_run_steps(self):
        r, st = self.job("# nothing defined\n")
        self.assertEqual(st, "FAIL_NO_RUN_STEPS")

    # ---- REQUIRED.txt: the declared outputs, in the bucket before the first step runs
    REQ = "# rak-required v1\na.txt\nb/c.txt\nd.txt\n"

    def test_required_list_is_in_the_bucket_before_the_first_step(self):
        """A VM preempted during any step has already published what it was supposed to produce: the first step
        copies the bucket's REQUIRED.txt, so it was there before any step command ran."""
        seen = 'cp "$FAKE_GCLOUD_DIR/gcs/fake-bkt/rak/vm1/out/REQUIRED.txt" seen.txt; echo > a.txt; mkdir -p b; echo > b/c.txt'
        r, st = self.job("run_steps() {\n  step A 60 \"a.txt b/c.txt\" -- '" + seen + "'\n"
                         "  step B 60 \"d.txt a.txt\" -- 'echo > d.txt; echo >> a.txt'\n}\n")
        self.assertEqual(st, "DONE", r.stdout + r.stderr)
        self.assertEqual((self.out / "seen.txt").read_text(), self.REQ)    # sorted, unique, one path per line
        self.assertEqual(self.gcs("out/REQUIRED.txt").read_text(), self.REQ)
        manifest = self.gcs("out/MANIFEST.sha256").read_text()
        self.assertNotIn("REQUIRED.txt", manifest)                       # like status.txt: not an output
        self.assertIn("./d.txt", manifest)

    def test_required_upload_failure_runs_nothing(self):
        self.knob(rsync_drop=["REQUIRED.txt"])
        r, st = self.job('run_steps() { step A 60 "a.txt" -- \'echo > a.txt\'; }\n')
        self.assertEqual(st, "FAIL_SYNC", r.stdout)
        self.assertFalse((self.out / "a.txt").exists(), "a step ran although REQUIRED.txt was not in the bucket")

    def test_glob_in_declared_outputs_is_refused(self):
        r, st = self.job('run_steps() { step A 60 "ckpt/*.pt" -- \'mkdir -p ckpt; echo > ckpt/1.pt\'; }\n')
        self.assertEqual(st, "FAIL_REQUIRED_GLOB", r.stdout)
        self.assertFalse((self.out / "ckpt").exists())
        r, st = self.job('run_steps() { step A 60 "/abs/a.txt ../up.txt" -- true; }\n')
        self.assertEqual(st, "FAIL_REQUIRED_PATH", r.stdout)

    def test_reading_the_declaration_runs_no_command(self):
        """Outputs are read by calling run_steps with a `step` that only records. Anything else in run_steps would
        run twice (once now); an external command there is refused instead of executed."""
        marker = P(self.t / "side_effect")
        r, st = self.job(f'run_steps() {{ touch "{marker}"; step A 60 "a.txt" -- \'echo > a.txt\'; }}\n')
        self.assertEqual(st, "FAIL_REQUIRED_DECLARE", r.stdout)
        self.assertFalse(Path(marker).exists(), "the declaration pass executed a command")
        self.assertFalse((self.out / "a.txt").exists())

    def test_a_step_cannot_rewrite_the_required_list(self):
        r, st = self.job('run_steps() { step A 60 "a.txt" -- \'echo > a.txt; echo "# rak-required v1" > REQUIRED.txt\'; }\n')
        self.assertEqual(st, "DONE", r.stdout)
        self.assertEqual(self.gcs("out/REQUIRED.txt").read_text(), "# rak-required v1\na.txt\n")
        self.assertIn("REQUIRED.txt was changed", (self.out / "driver.log").read_text())

    # ---- idle_check.sh
    def idle(self, hb_age_min=None, **kw):
        hb = self.state / "heartbeat"
        if hb_age_min is not None:
            hb.write_text("")
            t = time.time() - hb_age_min * 60; os.utime(hb, (t, t))
        dest = self.state / "gcs_dest"; dest.write_text("gs://fake-bkt/rak/vm1/out")
        env = self.env(DRY=1, IDLE_MINUTES=kw.pop("need", 1), STATE=P(self.state / "count"), HEARTBEAT=P(hb),
                       OUT_DIR=P(self.out), GCS_DEST_FILE=P(dest), GCLOUD=P(self.bin / "gcloud"), **kw)
        return subprocess.run([BASH, P(TPL / "idle_check.sh")], env=env, capture_output=True, text=True, timeout=60).stdout

    def test_idle_deletes(self):
        self.assertIn("WOULD DELETE", self.idle(hb_age_min=120))

    def test_delete_failure_falls_back_loudly(self):
        out = self.idle(hb_age_min=120, DRY_DELETE_RC=1)
        self.assertIn("SELF-DELETE FAILED", out); self.assertIn("WOULD FALL BACK TO SHUTDOWN", out)

    def test_failed_final_sync_blocks_delete(self):
        out = self.idle(hb_age_min=120, REQUIRE_SYNC=1, DRY_SYNC_RC=1)
        self.assertNotIn("WOULD DELETE", out); self.assertIn("not deleting", out)

    def test_busy_gpu_or_fresh_heartbeat_resets(self):
        self.assertIn("alive", self.idle(hb_age_min=120, FAKE_GPU_UTIL=80))
        self.assertEqual((self.state / "count").read_text().strip(), "0")
        self.assertIn("alive", self.idle(hb_age_min=0))

    def test_needs_consecutive_checks(self):
        self.assertIn("alive", self.idle(hb_age_min=120, need=2))
        self.assertIn("WOULD DELETE", self.idle(hb_age_min=120, need=2))


if __name__ == "__main__":
    unittest.main()
