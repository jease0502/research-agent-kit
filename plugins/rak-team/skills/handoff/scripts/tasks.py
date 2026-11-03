#!/usr/bin/env python3
"""Shared task list (tasks.json) and append-only progress log (progress.md) for several sessions.

    python tasks.py init
    python tasks.py add "title" [--id T7] [--depends T3,T4] [--who lead]
    python tasks.py list [--status open,claimed]
    python tasks.py claim T7 --who worker-a          # fails if someone else holds it or a dependency is not done
    python tasks.py note T7 --who worker-a --text "..."
    python tasks.py done T7 --who worker-a --evidence "commit abc123; results/run1.json"
    python tasks.py block T7 --who worker-a --why "needs the user's decision on X"
    python tasks.py release T7 --who worker-a        # give a claimed task back
    python tasks.py drop T7 --who lead --why "..."
    python tasks.py show T7
    python tasks.py resume                           # what a fresh session reads first

Files (paths relative to --dir, default the current directory):
    tasks.json   the task list; every write takes a lock and replaces the file atomically
    progress.md  one line per change, never rewritten; this is what survives a crash or a restart

Rules the tool enforces:
  * `done` needs --evidence (a commit, a file, a result path): "done" without a pointer is a claim, not a result.
  * A task can only be claimed by one session; claiming a task held by someone else fails.
  * A task whose dependencies are not done cannot be claimed.
  * Nothing is deleted; a task that will not be done is dropped with a reason.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

STATUSES = ("open", "claimed", "blocked", "done", "dropped")
LOCK_TIMEOUT = 30.0
STALE_AFTER = 120.0          # a lock older than this is assumed to belong to a dead process


class TaskError(Exception):
    pass


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Board:
    def __init__(self, directory: Path):
        self.dir = directory
        self.file = directory / "tasks.json"
        self.progress = directory / "progress.md"
        self.lock = directory / "tasks.json.lock"

    # ── locking ──
    def _acquire(self):
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                os.close(fd)
                return
            except FileExistsError:
                try:
                    age = time.time() - self.lock.stat().st_mtime
                    if age > STALE_AFTER:
                        self.lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TaskError(f"could not lock {self.lock} within {LOCK_TIMEOUT:.0f} s "
                                    f"(remove it by hand only if no session is writing)")
                time.sleep(0.05)

    def _release(self):
        self.lock.unlink(missing_ok=True)

    # ── io ──
    def _load(self) -> dict:
        if not self.file.exists():
            raise TaskError(f"{self.file} does not exist; run `tasks.py init` first")
        return json.loads(self.file.read_text(encoding="utf-8"))

    def _save(self, data: dict):
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.file)          # readers see the old file or the new one, never half of one

    def _log(self, who: str, text: str):
        with open(self.progress, "a", encoding="utf-8") as f:
            f.write(f"- {now()} [{who}] {text}\n")

    def change(self, fn):
        """Run fn(data) -> log line under the lock, save, and append the log line."""
        self._acquire()
        try:
            data = self._load()
            who, line = fn(data)
            self._save(data)
            self._log(who, line)
            return data
        finally:
            self._release()

    def read(self) -> dict:
        return self._load()

    # ── commands ──
    def init(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.file.exists():
            raise TaskError(f"{self.file} already exists")
        self._save({"version": 1, "tasks": []})
        if not self.progress.exists():
            self.progress.write_text("# Progress log\n\nAppend-only. One line per change, written by tasks.py.\n\n",
                                     encoding="utf-8")
        self._log("init", "task list created")


def find(data: dict, tid: str) -> dict:
    for t in data["tasks"]:
        if t["id"] == tid:
            return t
    raise TaskError(f"no task {tid}")


def cmd_add(b: Board, title: str, tid: str | None, depends: list[str], who: str):
    def fn(data):
        ids = {t["id"] for t in data["tasks"]}
        new = tid or f"T{len(data['tasks']) + 1}"
        while new in ids and not tid:
            new = f"T{int(new[1:]) + 1}"
        if new in ids:
            raise TaskError(f"task {new} already exists")
        missing = [d for d in depends if d not in ids]
        if missing:
            raise TaskError(f"unknown dependencies {missing}")
        data["tasks"].append({"id": new, "title": title, "status": "open", "owner": None, "depends": depends,
                              "created": now(), "updated": now(), "notes": [], "evidence": ""})
        return who, f"{new} added: {title}" + (f" (after {', '.join(depends)})" if depends else "")
    return b.change(fn)


def _set(b: Board, tid: str, who: str, verb: str, check, apply, text: str):
    def fn(data):
        t = find(data, tid)
        check(t, data)
        apply(t)
        t["updated"] = now()
        if text:
            t["notes"].append({"time": now(), "who": who, "text": f"{verb}: {text}"})
        return who, f"{tid} {verb}" + (f": {text}" if text else "")
    return b.change(fn)


def cmd_claim(b, tid, who):
    def check(t, data):
        if t["status"] in ("done", "dropped"):
            raise TaskError(f"{tid} is {t['status']}")
        if t["status"] == "claimed" and t["owner"] != who:
            raise TaskError(f"{tid} is claimed by {t['owner']}")
        pending = [d for d in t["depends"] if find(data, d)["status"] != "done"]
        if pending:
            raise TaskError(f"{tid} waits for {pending}")
    return _set(b, tid, who, "claimed", check, lambda t: t.update(status="claimed", owner=who), "")


def _owner_only(tid, who):
    def check(t, data):
        if t["status"] != "claimed" or t["owner"] != who:
            raise TaskError(f"{tid} is not claimed by {who} (status {t['status']}, owner {t['owner']})")
    return check


def cmd_done(b, tid, who, evidence):
    if not evidence.strip():
        raise TaskError("done needs --evidence: a commit, a file or a result path")
    return _set(b, tid, who, "done", _owner_only(tid, who),
                lambda t: t.update(status="done", evidence=evidence), evidence)


def cmd_note(b, tid, who, text):
    return _set(b, tid, who, "note", lambda t, d: None, lambda t: None, text)


def cmd_block(b, tid, who, why):
    return _set(b, tid, who, "blocked", _owner_only(tid, who), lambda t: t.update(status="blocked"), why)


def cmd_release(b, tid, who):
    def check(t, data):
        if t["owner"] != who or t["status"] not in ("claimed", "blocked"):
            raise TaskError(f"{tid} is not held by {who}")
    return _set(b, tid, who, "released", check, lambda t: t.update(status="open", owner=None), "")


def cmd_drop(b, tid, who, why):
    if not why.strip():
        raise TaskError("drop needs --why")
    def check(t, data):
        if t["status"] == "done":
            raise TaskError(f"{tid} is done; it cannot be dropped")
    return _set(b, tid, who, "dropped", check, lambda t: t.update(status="dropped"), why)


def fmt(t: dict) -> str:
    owner = f" @{t['owner']}" if t["owner"] else ""
    deps = f" after {','.join(t['depends'])}" if t["depends"] else ""
    return f"{t['id']:>5}  {t['status']:<8}{owner}{deps}  {t['title']}"


def resume(b: Board, tail: int = 20) -> str:
    data = b.read()
    out = ["## Tasks not done"]
    out += [fmt(t) for t in data["tasks"] if t["status"] not in ("done", "dropped")] or ["(none)"]
    out.append("")
    out.append(f"## Last {tail} progress lines")
    lines = b.progress.read_text(encoding="utf-8").splitlines() if b.progress.exists() else []
    out += [ln for ln in lines if ln.startswith("- ")][-tail:] or ["(none)"]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path.cwd())
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("add"); p.add_argument("title"); p.add_argument("--id"); p.add_argument("--depends", default="")
    p.add_argument("--who", default="lead")
    p = sub.add_parser("list"); p.add_argument("--status", default="")
    for name in ("claim", "release", "show"):
        p = sub.add_parser(name); p.add_argument("id")
        if name != "show":
            p.add_argument("--who", required=True)
    p = sub.add_parser("done"); p.add_argument("id"); p.add_argument("--who", required=True)
    p.add_argument("--evidence", default="")
    p = sub.add_parser("note"); p.add_argument("id"); p.add_argument("--who", required=True)
    p.add_argument("--text", required=True)
    for name in ("block", "drop"):
        p = sub.add_parser(name); p.add_argument("id"); p.add_argument("--who", required=True)
        p.add_argument("--why", default="")
    p = sub.add_parser("resume"); p.add_argument("--tail", type=int, default=20)
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    b = Board(a.dir)
    try:
        if a.cmd == "init":
            b.init()
        elif a.cmd == "add":
            cmd_add(b, a.title, a.id, [d for d in a.depends.split(",") if d], a.who)
        elif a.cmd == "list":
            want = set(filter(None, a.status.split(",")))
            for t in b.read()["tasks"]:
                if not want or t["status"] in want:
                    print(fmt(t))
        elif a.cmd == "show":
            print(json.dumps(find(b.read(), a.id), ensure_ascii=False, indent=1))
        elif a.cmd == "claim":
            cmd_claim(b, a.id, a.who)
        elif a.cmd == "release":
            cmd_release(b, a.id, a.who)
        elif a.cmd == "done":
            cmd_done(b, a.id, a.who, a.evidence)
        elif a.cmd == "note":
            cmd_note(b, a.id, a.who, a.text)
        elif a.cmd == "block":
            if not a.why.strip():
                raise TaskError("block needs --why")
            cmd_block(b, a.id, a.who, a.why)
        elif a.cmd == "drop":
            cmd_drop(b, a.id, a.who, a.why)
        elif a.cmd == "resume":
            print(resume(b, a.tail))
    except TaskError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    if a.cmd not in ("list", "show", "resume"):
        print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
