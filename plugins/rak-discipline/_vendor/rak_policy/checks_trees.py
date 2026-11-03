"""rak-cloud's rule: the agent does not edit the lifecycle trees (C1-C2 in docs/policy-engine.md).

Moved from plugins/rak-cloud/hooks/tree_guard.py unchanged, except that the plugin root comes from the event's
environment (PLUGIN_ROOT, set by the adapter) instead of the process's. A speed bump, not a wall (docs/bt-pilot.md):
command text can always be got around; the hash pin in rak_cloud.py and review are what hold.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

READ_ONLY = {"cat", "head", "tail", "less", "more", "grep", "rg", "wc", "sha256sum", "diff", "ls", "stat", "file"}
READ_ONLY_GIT = {"diff", "log", "show", "status", "blame"}
SEPARATORS = re.compile(r"\|\||&&|;|\||\n|&(?!>)")
TREE_NAME = re.compile(r"(?i)trees[\\/]+[^\s'\"]*\.json|lifecycle\.json")


def trees_dir(env) -> Path:
    return Path(env["PLUGIN_ROOT"]).resolve() / "trees"


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


def tree_file(event) -> str | None:
    raw = event.args.get("path") or ""
    p = Path(raw)
    if not p.is_absolute():
        p = Path(event.cwd or os.getcwd()) / p
    if under(p.resolve(), trees_dir(event.env)):
        return f"{event.native_tool} on {raw} (under the plugin's trees/)"
    return None


def tree_shell(event) -> str | None:
    for seg in SEPARATORS.split(event.args.get("command", "")):
        if TREE_NAME.search(seg) and not read_only(seg.strip()):
            return f"a command that names a lifecycle tree: {seg.strip()[:120]}"
    return None
