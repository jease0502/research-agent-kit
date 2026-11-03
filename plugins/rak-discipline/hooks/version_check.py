#!/usr/bin/env python3
"""SessionStart hook: warn when Claude Code is too old for this kit's hooks to fail closed.

The kit's PreToolUse hooks set "onFailure": "block". Before Claude Code 2.1.295 that field does not exist, and a hook
that times out, exits with an unexpected code or cannot start lets the tool call through (hooks reference). This
hook asks `claude --version` and, below 2.1.295 or when the version cannot be read, shows a warning to the user
(systemMessage) and tells Claude (additionalContext). An unreadable version is a warning, never a pass.
Limit: it asks the `claude` on PATH, which may not be the one running this session.

The same file is in every plugin that has hooks (a test keeps the copies identical); the first copy to run in a
session prints the warning, the others stay quiet.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

MIN = (2, 1, 295)


def installed_version() -> tuple[tuple[int, int, int] | None, str]:
    exe = shutil.which("claude")
    if not exe:
        return None, "`claude` is not on PATH"
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"`claude --version` failed ({type(e).__name__})"
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", r.stdout or "")
    if r.returncode != 0 or not m:
        return None, f"`claude --version` gave no version (exit {r.returncode}: {(r.stdout or r.stderr).strip()[:80]!r})"
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)


def warning(version, detail: str) -> str | None:
    need = ".".join(map(str, MIN))
    if version is None:
        return (f"research-agent-kit: could not read the Claude Code version: {detail}. The kit's guard hooks need "
                f"{need} or later to block a call when the hook itself fails; until this is checked, assume a hook "
                "that times out or cannot start LETS THE CALL THROUGH.")
    if version < MIN:
        return (f"research-agent-kit: Claude Code {detail} is older than {need}. On this version a guard hook that "
                "times out, crashes or cannot start LETS THE CALL THROUGH (\"onFailure\": \"block\" is not "
                f"supported). Upgrade Claude Code before relying on the kit's guards.")
    return None


def first_in_session(session_id: str) -> bool:
    if not session_id:
        return True
    marker = os.path.join(tempfile.gettempdir(), f"rak-version-check-{re.sub(r'[^A-Za-z0-9_-]', '', session_id)[:80]}")
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except FileExistsError:
        return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    msg = warning(*installed_version())
    if msg and first_in_session(str(data.get("session_id") or "")):
        print(json.dumps({"systemMessage": msg,
                          "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))


if __name__ == "__main__":
    main()
