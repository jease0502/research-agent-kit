"""Second round of the lifecycle trees: cross-review of 534dfdd and the maintainer's decisions on it.

A1 a trace that cannot be written does not stop the waiter, and never hides the tick's own exception.
A2 the verified list is parsed exactly as verify_pull parses the manifest.
A3 create with no zones fails with the old message.
D  Timeout without "since" is refused while the pilot runs.
2a a delete that cannot be confirmed is tried at most DELETE_ATTEMPTS times, then the waiter stops (exit 3).
2b a VM gone with outputs not all verified ends gone_unverified (exit 4) and lists every unverified file.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import bt  # noqa: E402
import rak_cloud as rc  # noqa: E402
import test_bt_lifecycle as tl  # noqa: E402
import test_cloud as tc  # noqa: E402


class Round2(tl.BranchEnv):
    def block_trace(self, name=None):
        f = rc.trace_file(self.root, name or self.NAME)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.mkdir()                                   # a folder where the file should be: every write fails

    # -- A1
    def test_unwritable_trace_does_not_stop_the_waiter(self):
        self.block_trace()
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.assertIsNone(self.w.poll())
        self.assertTrue(self.kw("TRACE_WRITE_FAILED"))
        self.job_outputs()
        self.assertEqual(self.w.poll(), "done")

    def test_unwritable_trace_keeps_the_ticks_own_exception(self):
        self.block_trace()
        rc.instances_file(self.root).write_text("{not json")    # _mark_ended will fail inside the tick
        (self.fake / "instances.json").write_text("{}")
        with self.assertRaises(json.JSONDecodeError):
            self.w.poll()

    def test_unwritable_trace_does_not_stop_create(self):
        self.block_trace("rak-c")
        self.assertEqual(rc.create(self.cfg, self.g, self.root, "rak-c", "gs://j/", yes=True, out=self.lines.append), "z-a")
        self.assertTrue(any(l.startswith("TRACE_WRITE_FAILED") for l in self.lines))

    # -- A2
    def test_verified_list_parses_like_verify_pull(self):
        (self.out / "model.pt").write_bytes(b"w"); (self.out / "a b.txt").write_text("x")
        man = (f"{rc.sha256_file(self.out / 'model.pt')} *./model.pt\n"          # binary mode
               f"{rc.sha256_file(self.out / 'a b.txt')}  a b.txt\n")              # text mode, a space in the name
        (self.out / "MANIFEST.sha256").write_text(man); (self.out / "status.txt").write_text("DONE\n")
        self.assertEqual(self.w.poll(), "done")
        self.assertEqual(self.w.bb["verified"], ["model.pt", "a b.txt"])
        self.assertEqual([rel for _, rel in rc.manifest_entries(man)], ["model.pt", "a b.txt"])

    # -- A3
    def test_create_without_zones_says_every_zone_failed(self):
        with self.assertRaisesRegex(rc.CloudError, "^every zone failed$"):
            rc.create(dict(self.cfg, zones=[]), self.g, self.root, "rak-c", "gs://j/", yes=True, out=self.lines.append)

    # -- 2a
    def test_delete_gives_up_after_three_unconfirmed_attempts(self):
        self.job_outputs(); self.knob(delete_fails=True)          # the VM stays: every poll pulls and deletes again
        self.assertIsNone(self.w.poll()); self.assertIsNone(self.w.poll())
        self.assertEqual(self.w.poll(), "delete_unverified")
        self.assertEqual(len(self.kw("DELETE_CHECK_FAILED")), rc.DELETE_ATTEMPTS)
        self.assertTrue(self.kw("DELETE_GAVE_UP"))
        self.assertIn("delete_unverified", self.kw("END")[-1])
        a = [x for x in self.w.tree.trace if x["path"].endswith("give_up_delete")][0]
        self.assertEqual(a["status"], "SUCCESS")
        n = sum(c[:3] == ["compute", "instances", "delete"] for c in self.calls())
        self.assertEqual(n, rc.DELETE_ATTEMPTS)

    def test_delete_that_succeeds_on_the_second_try_is_done(self):
        self.job_outputs(); self.knob(delete_fails=True)
        self.assertIsNone(self.w.poll())
        self.knob(delete_fails=False)
        self.assertEqual(self.w.poll(), "done")

    # -- 2b
    def test_gone_with_verified_outputs_is_gone(self):
        self.job_outputs()
        (self.fake / "instances.json").write_text("{}")
        self.assertEqual(self.w.poll(), "gone")
        self.assertFalse(self.kw("OUTPUTS_UNVERIFIED"))

    def test_gone_without_manifest_is_gone_unverified(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n"); (self.out / "ckpt_100.pt").write_bytes(b"part")
        (self.fake / "instances.json").write_text("{}")
        self.assertEqual(self.w.poll(), "gone_unverified")
        u = self.kw("OUTPUTS_UNVERIFIED")[0]
        self.assertIn("MANIFEST.sha256 missing", u); self.assertIn("required list unknown", u)
        self.assertEqual(self.w.bb["unverified"], ["MANIFEST.sha256 missing (required list unknown)"])

    def test_gone_partly_verified_lists_every_unverified_file(self):
        names = [f"f{i}.bin" for i in range(5)]
        for n in names:
            (self.out / n).write_bytes(n.encode())
        (self.out / "MANIFEST.sha256").write_text("".join(f"{rc.sha256_file(self.out / n)}  ./{n}\n" for n in names))
        (self.out / "f3.bin").write_bytes(b"changed")
        (self.out / "status.txt").write_text("DONE\n")
        self.knob(rsync_drop=["f0.bin", "f4.bin"])
        (self.fake / "instances.json").write_text("{}")
        self.assertEqual(self.w.poll(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["missing f0.bin", "hash differs f3.bin", "missing f4.bin"])
        line = self.kw("OUTPUTS_UNVERIFIED")[0]
        for p in ("f0.bin", "f3.bin", "f4.bin"):
            self.assertIn(p, line)
        r = [x for x in self.w.tree.trace if x["path"].endswith("report_gone_unverified")][0]
        self.assertIn("f4.bin", r["reason"])

    def test_exit_codes(self):
        # stop_unconfirmed was 2 like gone until the maintainer's decision after 8e0c5ee (breaking change): the two mean
        # opposite things to a monitor (VM gone and verified vs VM still running and billing)
        self.assertEqual(rc.EXIT, {"done": 0, "gone": 2, "delete_unverified": 3, "gone_unverified": 4,
                                   "stop_unconfirmed": 5})

    def cli_wait(self):
        import os
        self.write_cfg(self.cfg)
        old = os.environ.get("CLAUDE_PROJECT_DIR"); os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
        try:
            return rc.main(["wait", self.NAME])
        finally:
            if old is None:
                os.environ.pop("CLAUDE_PROJECT_DIR")
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old

    def test_cli_exit_4_for_gone_unverified(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        (self.fake / "instances.json").write_text("{}")
        self.assertEqual(self.cli_wait(), 4)

    def test_cli_exit_3_for_delete_unverified(self):
        self.job_outputs(); self.knob(delete_fails=True)
        self.assertEqual(self.cli_wait(), 3)


class NoTimeoutWithoutSince(unittest.TestCase):
    def test_validator_refuses_timeout_without_since(self):
        spec = {"type": "Timeout", "name": "t", "seconds": 10, "child": {"type": "Action", "name": "a"}}
        with self.assertRaisesRegex(bt.TreeError, "since"):
            bt.Tree(spec, {"a": lambda bb: bt.RUNNING})


if __name__ == "__main__":
    unittest.main()
