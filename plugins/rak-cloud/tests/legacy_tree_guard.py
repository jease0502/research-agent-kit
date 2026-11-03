# FROZEN REFERENCE: plugins/rak-cloud/hooks/tree_guard.py as of f889085, before the hook moved onto the policy engine
# (python/rak/policy). Used only by the differential test python/tests/test_policy_differential.py. Do not edit.
#!/usr/bin/env python3
"""PreToolUse guard (Claude Code hook): the agent does not edit rak-cloud's lifecycle trees.

The job lifecycle (create, wait, pull, verify, delete) is a behaviour tree in <plugin>/trees/, run by code. The
spending decisions in it (which zones, when to delete, when to give up) are the owner's, not the agent's. This
hook blocks Edit / Write / MultiEdit / NotebookEdit on any path under <plugin>/trees/, and Bash command segments
that name a tree file unless they start with a read-only command. rak_cloud.py also pins each tree's hash, so an
edit that gets past this hook stops the run instead of changing it.
A deliberate change to a tree is made by a person (or with this plugin disabled), with the pin updated.
Exit 2 blocks; a crash blocks too (fail closed).
Limit: Bash is matched on command text. A script that writes the file itself is not seen (the pin still is).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

FILE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
READ_ONLY = {"cat", "head", "tail", "less", "more", "grep", "rg", "wc", "sha256sum", "diff", "ls", "stat", "file"}
READ_ONLY_GIT = {"diff", "log", "show", "status", "blame"}
SEPARATORS = re.compile(r"\|\||&&|;|\||\n|&(?!>)")
TREE_NAME = re.compile(r"(?i)trees[\\/]+[^\s'\"]*\.json|lifecycle\.json")


def block(msg: str) -> None:
    print(f"rak-cloud blocked this: {msg}\nThe lifecycle tree is the owner's spending policy and is not edited by "
          "the agent. Describe the change you want; a person makes it and updates the pin in rak_cloud.py.",
          file=sys.stderr)
    sys.exit(2)


def trees_dir() -> Path:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)
    return Path(root).resolve() / "trees"


def under(p: Path, d: Path) -> bool:
    a, b = os.path.normcase(str(p)), os.path.normcase(str(d))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def read_only(segment: str) -> bool:
    try:
        words = shlex.split(segment, posix=True)
    except ValueError:
        return False
    if not words:
        return True
    if words[0] == "git":
        return len(words) > 1 and words[1] in READ_ONLY_GIT
    return words[0] in READ_ONLY and not any(w in (">", ">>") or w.startswith((">", "-i")) for w in words[1:])


def check(data: dict) -> str | None:
    tool, inp = data.get("tool_name"), data.get("tool_input") or {}
    if tool in FILE_TOOLS:
        raw = inp.get(FILE_TOOLS[tool]) or ""
        p = Path(raw)
        if not p.is_absolute():
            p = Path(data.get("cwd") or os.getcwd()) / p
        if under(p.resolve(), trees_dir()):
            return f"{tool} on {raw} (under the plugin's trees/)"
    elif tool == "Bash":
        for seg in SEPARATORS.split(inp.get("command", "")):
            if TREE_NAME.search(seg) and not read_only(seg.strip()):
                return f"a command that names a lifecycle tree: {seg.strip()[:120]}"
    return None


def main() -> None:
    try:
        why = check(json.load(sys.stdin))
        if why:
            block(why)
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        print(f"rak-cloud tree guard error ({type(e).__name__}: {e}); blocking.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
