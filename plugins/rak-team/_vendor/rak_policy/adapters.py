"""Adapters: an agent's native tool call -> an engine Event. Only Claude Code for now.

The Claude Code hooks block a deny (exit 2) and answer an ask with claude_code_ask() on stdout and exit 0, so
Claude Code asks the person (cross-review of fb10c8b). No rule uses "ask" yet.
"""
from __future__ import annotations

import json

from .engine import Decision, Event

_CC_FILE = {"Edit": "file.edit", "MultiEdit": "file.edit", "Write": "file.write", "NotebookEdit": "notebook.edit"}


def claude_code_event(data: dict, env: dict, backends: dict | None = None) -> Event:
    """A PreToolUse hook's JSON -> Event. Values are passed through as they come (including None), so a malformed
    call fails inside the check the same way it did inside the hook, and the hook blocks it."""
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    if tool == "Bash":
        name, args = "shell", {"command": ti.get("command", "")}
    elif tool == "Write":
        name, args = "file.write", {"path": ti.get("file_path", ""), "content": ti.get("content", "")}
    elif tool == "Edit":
        name, args = "file.edit", {"path": ti.get("file_path", ""), "edits": [ti]}
    elif tool == "MultiEdit":
        name, args = "file.edit", {"path": ti.get("file_path", ""), "edits": ti.get("edits")}
    elif tool == "NotebookEdit":
        name, args = "notebook.edit", {"path": ti.get("notebook_path")}
    else:
        name, args = f"other:{tool}", dict(ti)
    return Event(tool=name, args=args, cwd=data.get("cwd"), env=env, native_tool=tool, backends=backends or {})


def claude_code_ask(d: Decision, plugin: str) -> str:
    """The PreToolUse hook output that hands an "ask" decision to Claude Code's permission prompt."""
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                              "permissionDecisionReason": f"{plugin} ({d.rule}): {d.reason}"}})
