#!/usr/bin/env python3
"""Cross-process lock for a shared local GPU, so parallel agents and jobs do not run out of GPU memory.

  python gpulock.py --lock PATH run OWNER [--wait SECONDS] -- command ...   # exit 75 if still busy after --wait
  python gpulock.py --lock PATH status
  RAK_GPU_LOCK=PATH python gpulock.py run OWNER -- command ...
In Python:
  from gpulock import gpu
  with gpu("owner", lock="/path/gpu.lock"): ...

Rule: hold the lock only while something is loaded on the GPU, and unload before releasing.
The lock path has no default: every user of one GPU must name the same file, and a default that differs
between tools is a lock that does not lock.

Stale locks (holder process gone on this host, or not renewed for stale_s) are removed only under a
separate breaker lock, after re-checking them, so two waiters that both see a stale lock cannot both win. Release only removes the lock if it is
still ours (token match), so a holder that was declared stale cannot delete its successor's lock.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid

EX_TEMPFAIL = 75


def _alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read(lock: str) -> dict | None:
    try:
        with open(lock, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _stale(lock: str, stale_s: float) -> bool:
    try:
        age = time.time() - os.path.getmtime(lock)
    except OSError:
        return False
    if age > stale_s:
        return True
    info = read(lock)
    if info is None:
        return False  # unreadable but fresh: someone may be mid-write; wait rather than break it
    return info.get("host") == socket.gethostname() and not _alive(info.get("pid"))


BREAKER_STALE_S = 60
# Windows: O_EXCL on a file that another handle is deleting fails with EACCES, not EEXIST, and a file another
# handle has open (a waiter reading it) cannot be removed. Both are "busy, try again", not a permission problem.
# On POSIX, EACCES is a real permission problem and is raised.
_WINDOWS = os.name == "nt"


def _busy(e: OSError) -> bool:
    return _WINDOWS and isinstance(e, PermissionError)


def _remove(path: str, tries: int = 1) -> bool:
    """Remove path; True if it is gone. On Windows a reader holding it open makes this retry briefly."""
    for i in range(tries):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except PermissionError as e:
            if not _busy(e):
                raise
            time.sleep(0.02 * (i + 1))
    return False


def _take_over(lock: str, stale_s: float) -> None:
    """Remove a stale lock, but only after re-checking it under a separate breaker lock.

    Renaming the lock aside without the breaker is not enough: between "this lock is stale" and the
    rename, another waiter can take the stale lock over and create a fresh one, and the rename would then
    move the *fresh* lock aside, letting two holders in. Under the breaker, the re-check sees the fresh
    lock and leaves it alone.
    """
    breaker = lock + ".break"
    try:
        os.close(os.open(breaker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except PermissionError as e:
        if not _busy(e):
            raise
        return                               # another breaker is being removed: busy
    except FileExistsError:
        with contextlib.suppress(OSError):   # a breaker left behind by a crashed process
            if time.time() - os.path.getmtime(breaker) > BREAKER_STALE_S:
                os.remove(breaker)
        return
    try:
        if _stale(lock, stale_s):
            _remove(lock)                    # if a reader holds it, it stays; the caller loops and re-checks
    finally:
        with contextlib.suppress(OSError):
            _remove(breaker, tries=10)


@contextlib.contextmanager
def gpu(owner: str, lock: str | None = None, poll: float = 10, wait: float | None = None,
        stale_s: float = 3 * 3600, renew_s: float = 600):
    """wait=None blocks; otherwise TimeoutError after `wait` seconds (wait=0: try once)."""
    lock = lock or os.environ.get("RAK_GPU_LOCK")
    if not lock:
        raise ValueError("no lock path: pass lock= or set RAK_GPU_LOCK")
    token = uuid.uuid4().hex
    deadline = None if wait is None else time.time() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"owner": owner, "pid": os.getpid(), "host": socket.gethostname(),
                           "since": time.time(), "token": token}, f)
            break
        except (FileExistsError, PermissionError) as e:
            if isinstance(e, PermissionError) and not _busy(e):
                raise
            if _stale(lock, stale_s):
                _take_over(lock, stale_s)
                continue
            if deadline is not None and time.time() >= deadline:
                held = read(lock) or {}
                raise TimeoutError(f"GPU lock busy: {lock} (owner {held.get('owner')!r}, pid {held.get('pid')})")
            time.sleep(poll if deadline is None else max(0.0, min(poll, deadline - time.time())))
    stop = threading.Event()

    def renew():  # keep mtime fresh so a long job is not taken for stale
        while not stop.wait(renew_s):
            if (read(lock) or {}).get("token") != token:
                return
            with contextlib.suppress(OSError):
                os.utime(lock)

    threading.Thread(target=renew, daemon=True).start()
    try:
        yield
    finally:
        stop.set()
        if (read(lock) or {}).get("token") == token:
            with contextlib.suppress(OSError):
                _remove(lock, tries=50)          # a waiter reading it for a moment must not keep it held


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="gpulock")
    ap.add_argument("--lock", default=os.environ.get("RAK_GPU_LOCK"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("owner")
    r.add_argument("--wait", type=float)
    # split at "--" ourselves: argparse.REMAINDER would swallow "--wait 0" into the command and block forever
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if not a.lock:
        ap.error("no lock path: --lock PATH or RAK_GPU_LOCK")
    if a.cmd == "status":
        info = read(a.lock)
        print(json.dumps(info) if info else ("free" if not os.path.exists(a.lock) else "held (unreadable)"))
        return 0
    if not cmd:
        ap.error("missing command after --")
    try:
        with gpu(a.owner, lock=a.lock, wait=a.wait):
            return subprocess.run(cmd).returncode
    except TimeoutError as e:
        print(e, file=sys.stderr)
        return EX_TEMPFAIL


if __name__ == "__main__":
    sys.exit(main())
