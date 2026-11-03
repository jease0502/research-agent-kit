"""gpulock: mutual exclusion, stale takeover, and never deleting someone else's lock."""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import gpulock  # noqa: E402

CLI = Path(__file__).resolve().parent.parent / "scripts" / "gpulock.py"


class GpuLock(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="rakl-")); self.lock = str(self.d / "gpu.lock")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def fake_holder(self, pid, age_s=0, host=None):
        Path(self.lock).write_text(json.dumps({"owner": "other", "pid": pid, "host": host or socket.gethostname(),
                                               "since": time.time(), "token": "theirs"}))
        t = time.time() - age_s; os.utime(self.lock, (t, t))

    def test_acquire_release(self):
        with gpulock.gpu("a", lock=self.lock, wait=0):
            self.assertEqual(gpulock.read(self.lock)["owner"], "a")
        self.assertFalse(os.path.exists(self.lock))

    def test_second_holder_times_out(self):
        with gpulock.gpu("a", lock=self.lock, wait=0):
            with self.assertRaises(TimeoutError):
                with gpulock.gpu("b", lock=self.lock, wait=0.3, poll=0.1):
                    pass

    def test_live_holder_is_respected(self):
        self.fake_holder(os.getpid())          # this process is alive
        with self.assertRaises(TimeoutError):
            with gpulock.gpu("b", lock=self.lock, wait=0):
                pass

    def test_dead_holder_is_taken_over(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.fake_holder(p.pid)
        with gpulock.gpu("b", lock=self.lock, wait=0):
            self.assertEqual(gpulock.read(self.lock)["owner"], "b")

    def test_other_host_only_by_age(self):
        self.fake_holder(999999, host="elsewhere")
        with self.assertRaises(TimeoutError):
            with gpulock.gpu("b", lock=self.lock, wait=0):
                pass
        self.fake_holder(999999, age_s=4 * 3600, host="elsewhere")
        with gpulock.gpu("b", lock=self.lock, wait=0):
            pass

    def test_unreadable_fresh_lock_is_not_broken(self):
        Path(self.lock).write_text("{half a json")
        with self.assertRaises(TimeoutError):
            with gpulock.gpu("b", lock=self.lock, wait=0):
                pass

    def test_release_does_not_delete_successor(self):
        with gpulock.gpu("a", lock=self.lock, wait=0):
            self.fake_holder(os.getpid())       # someone took it over meanwhile
        self.assertEqual(gpulock.read(self.lock)["token"], "theirs")

    def test_only_one_wins_concurrent_contention(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.fake_holder(p.pid)                  # stale: both workers will try to take it over
        inside, overlaps, errs = [0], [0], []
        def worker(n):
            try:
                with gpulock.gpu(f"w{n}", lock=self.lock, wait=20, poll=0.05):
                    inside[0] += 1
                    if inside[0] > 1:
                        overlaps[0] += 1
                    time.sleep(0.2)
                    inside[0] -= 1
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual((overlaps[0], errs), (0, []))

    def test_stale_takeover_cannot_steal_a_fresh_lock(self):
        """Deterministic version of the race behind the occasional failure of the contention test:
        B judges the old lock stale; before B moves it aside, A takes it over and creates a fresh lock;
        B must not then move A's fresh lock aside and enter too."""
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.fake_holder(p.pid)                          # dead holder: stale
        real_stale = gpulock._stale
        entered_a = []
        a_ctx = gpulock.gpu("A", lock=self.lock, wait=0)

        def stale_then_a_wins(lock, stale_s):
            verdict = real_stale(lock, stale_s)
            if verdict and not entered_a:                # B has seen the dead lock; now A gets in first
                entered_a.append(True)
                gpulock._stale = real_stale
                a_ctx.__enter__()
                gpulock._stale = stale_then_a_wins
            return verdict

        gpulock._stale = stale_then_a_wins
        try:
            with self.assertRaises(TimeoutError, msg="B entered while A held the lock"):
                with gpulock.gpu("B", lock=self.lock, wait=0):
                    pass
            self.assertEqual(gpulock.read(self.lock)["owner"], "A")
        finally:
            gpulock._stale = real_stale
            if entered_a:
                a_ctx.__exit__(None, None, None)

    # ---- Windows: a file being deleted by another handle answers O_EXCL with EACCES (PermissionError), not EEXIST,
    # and a file another handle has open cannot be removed. Both mean "busy", not "you may not". Injected, so the
    # same tests run (and check the POSIX side) on every platform.

    def flaky(self, fn, path_suffix, times=1):
        """fn, but the first `times` calls on a path ending with path_suffix raise PermissionError(13)."""
        left = [times]

        def wrapped(path, *a, **kw):
            if str(path).endswith(path_suffix) and left[0] > 0:
                left[0] -= 1
                raise PermissionError(13, "Access is denied (injected)", str(path))
            return fn(path, *a, **kw)
        return wrapped, left

    def patched(self, windows, **fns):
        from unittest import mock
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(gpulock, "_WINDOWS", windows, create=True))
        for name, f in fns.items():
            stack.enter_context(mock.patch.object(gpulock.os, name, f))
        return stack

    def test_eacces_on_the_breaker_is_busy_on_windows(self):            # F1
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.fake_holder(p.pid)
        f, left = self.flaky(os.open, ".break")
        with self.patched(True, open=f):
            with gpulock.gpu("b", lock=self.lock, wait=5, poll=0.01):
                self.assertEqual(gpulock.read(self.lock)["owner"], "b")
        self.assertEqual(left[0], 0)
        self.fake_holder(p.pid)                                                   # stale again, so the breaker is used
        f, _ = self.flaky(os.open, ".break")
        with self.patched(False, open=f), self.assertRaises(PermissionError):   # POSIX: a real permission problem
            with gpulock.gpu("b", lock=self.lock, wait=5, poll=0.01):
                pass

    def test_eacces_on_the_lock_is_busy_and_bounded_by_the_deadline(self):   # F2
        f, left = self.flaky(os.open, "gpu.lock")
        with self.patched(True, open=f):
            with gpulock.gpu("b", lock=self.lock, wait=5, poll=0.01):
                self.assertEqual(gpulock.read(self.lock)["owner"], "b")
        f, _ = self.flaky(os.open, "gpu.lock", times=10 ** 6)
        with self.patched(True, open=f), self.assertRaises(TimeoutError):        # never an endless loop
            with gpulock.gpu("b", lock=self.lock, wait=0.2, poll=0.01):
                pass
        f, _ = self.flaky(os.open, "gpu.lock")
        with self.patched(False, open=f), self.assertRaises(PermissionError):
            with gpulock.gpu("b", lock=self.lock, wait=5, poll=0.01):
                pass

    def test_reader_holding_a_stale_lock_does_not_crash_the_takeover(self):  # F3
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.fake_holder(p.pid)
        f, left = self.flaky(os.remove, "gpu.lock")
        with self.patched(True, remove=f):
            with gpulock.gpu("b", lock=self.lock, wait=5, poll=0.01):
                self.assertEqual(gpulock.read(self.lock)["owner"], "b")
        self.assertEqual(left[0], 0)

    def test_reader_at_release_does_not_leave_the_lock_behind(self):        # F4
        f, left = self.flaky(os.remove, "gpu.lock", times=3)
        with self.patched(True, remove=f):
            with gpulock.gpu("a", lock=self.lock, wait=0):
                pass
        self.assertEqual(left[0], 0)
        self.assertFalse(os.path.exists(self.lock), "the released lock was left behind")

    def test_no_lock_path(self):
        os.environ.pop("RAK_GPU_LOCK", None)
        with self.assertRaises(ValueError):
            with gpulock.gpu("a"):
                pass

    def test_cli_runs_and_reports_busy(self):
        r = subprocess.run([sys.executable, str(CLI), "--lock", self.lock, "run", "me", "--", sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertEqual(r.returncode, 3)
        self.fake_holder(os.getpid())
        r = subprocess.run([sys.executable, str(CLI), "--lock", self.lock, "run", "me", "--wait", "0", "--", sys.executable, "-c", "pass"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, gpulock.EX_TEMPFAIL)
        self.assertIn("busy", r.stderr)


if __name__ == "__main__":
    unittest.main()
