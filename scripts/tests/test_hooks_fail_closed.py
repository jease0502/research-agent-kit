"""Every command hook in every plugin sets "onFailure": "block".

Without it, Claude Code lets the tool call through when a PreToolUse hook times out, exits with a code other than 0
or 2, or cannot start (hooks reference, "Block the action when a hook fails"; Claude Code 2.1.295 or later). Our
hooks catch their own exceptions and exit 2, but that does not cover a hook that never runs: a missing interpreter,
a wrong path, a hang. Checked against the real CLI on 2026-10-31 (Claude Code 2.1.316, haiku, five throwaway
plugins): exit 1 with the default went through; exit 1, a timeout and a missing interpreter with "block" were
blocked; exit 0 with "block" ran (the control).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


GATES = {"PreToolUse"}   # events whose hooks guard an action; SessionStart's version warning gates nothing


def problems(hooks_json: dict, where: str) -> list[str]:
    out = []
    for event, entries in (hooks_json.get("hooks") or {}).items():
        if event not in GATES:
            continue
        for e in entries:
            for h in e.get("hooks", []):
                if h.get("type") in ("command", "http") and h.get("onFailure") != "block":
                    out.append(f"{where}: {event} hook {h.get('command') or h.get('url')!r} has no \"onFailure\": \"block\"")
    return out


def test_every_plugin_hook_blocks_on_failure():
    files = sorted(REPO.glob("plugins/*/hooks/hooks.json"))
    assert len(files) >= 3, files
    found = [p for f in files for p in problems(json.loads(f.read_text(encoding="utf-8")), f.relative_to(REPO).as_posix())]
    assert not found, "\n".join(found)


def test_checker_flags_a_hook_without_it():
    bad = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python x.py"}]}]}}
    assert problems(bad, "x")
    ok = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python x.py",
                                                                    "onFailure": "block"}]}]}}
    assert not problems(ok, "x")
