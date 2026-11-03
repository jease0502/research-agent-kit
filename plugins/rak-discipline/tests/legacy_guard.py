# FROZEN REFERENCE: plugins/rak-discipline/hooks/guard.py as of f889085, before the hook moved onto the policy engine
# (python/rak/policy). Used only by the differential test python/tests/test_policy_differential.py. Do not edit.
#!/usr/bin/env python3
"""PreToolUse guard for rak-discipline (Claude Code hook). Exit 2 blocks the tool call.

Rules (only active when the project has .rak/discipline.json):
  1. A Bash command matching `experiment_patterns` must carry RAK_PREREG=<id>, and <id> must be
     frozen with its prereg and verdict script unchanged since freezing.
  2. A Bash command matching `verdict_patterns` (reading results) is blocked unless the gate for
     its RAK_PREREG id is PASS (and recorded against the frozen files).
  3. Edit / MultiEdit / Write on a file matching `results_globs` is blocked if any committed line
     (HEAD version, frontmatter exempt) would be removed or rewritten. Bash commands that name such
     a file together with an in-place editing / deleting construct are blocked too.

This is a second line of defence. The verdict script enforces rule 2 itself, and the git pre-commit
hook enforces rule 3 on whatever reached the index. See README "Limits" for what this cannot catch.
If the hook itself crashes it blocks (exit 2) rather than letting the call through.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rak_discipline as rd  # noqa: E402

EDIT_CONSTRUCTS = [
    r"\bsed\b[^|;&]*\s-i", r"\bperl\b[^|;&]*\s-[a-z]*i", r"(?<![>&0-9])>(?!>)\s*\S", r"\btruncate\b",
    r"\brm\b", r"\bgit\s+rm\b", r"\bmv\b", r"\btee\b(?![^|;&]*\s-a)", r"\bcp\b", r"\bdd\b",
]


def block(msg: str) -> None:
    print(f"rak-discipline blocked this call: {msg}", file=sys.stderr)
    sys.exit(2)


def prereg_id(cmd: str, token: str) -> str | None:
    m = re.search(rf"\b{re.escape(token)}=([A-Za-z0-9-]+)", cmd)
    return m.group(1) if m else None


def check_bash(root: Path, cfg: dict, cmd: str) -> None:
    token = cfg["prereg_token"]
    if any(re.search(p, cmd) for p in cfg["experiment_patterns"]):
        pid = prereg_id(cmd, token)
        if not pid:
            block(f"this looks like an experiment launch (matches experiment_patterns) but carries no {token}=<id>. "
                  "Freeze a prereg first, then launch with that id.")
        try:
            rd.verify_frozen(root, pid)
        except rd.DisciplineError as e:
            block(str(e))
    if any(re.search(p, cmd) for p in cfg["verdict_patterns"]):
        pid = prereg_id(cmd, token)
        if not pid:
            block(f"reading results needs {token}=<id> so the gate can be checked")
        try:
            rd.require_gate_pass(root, pid)
        except rd.DisciplineError as e:
            block(str(e))
    if cfg["results_globs"] and any(re.search(p, cmd) for p in EDIT_CONSTRUCTS):
        for tok in re.findall(r"[\w./\\-]+\.\w+", cmd):
            rel = tok.replace("\\", "/").lstrip("./")
            if rd.matches_any(rel, cfg["results_globs"]) and rd.head_version(root, rel) is not None:
                block(f"{rel} is an append-only results doc; shell edits/deletes of it are not allowed. "
                      "Use Edit to add an erratum section.")


def proposed_content(root: Path, tool: str, ti: dict) -> tuple[str, str] | None:
    path = Path(ti.get("file_path", ""))
    if not path.is_absolute():
        path = root / path
    try:
        rel = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    cur = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
    if tool == "Write":
        return rel, ti.get("content", "")
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    new = cur
    for e in edits or []:
        old_s, new_s = e.get("old_string", ""), e.get("new_string", "")
        new = new.replace(old_s, new_s) if e.get("replace_all") else new.replace(old_s, new_s, 1)
    return rel, new


def check_edit(root: Path, cfg: dict, tool: str, ti: dict) -> None:
    pc = proposed_content(root, tool, ti)
    if pc is None:
        return
    rel, new = pc
    if not rd.matches_any(rel, cfg["results_globs"]):
        return
    old = rd.head_version(root, rel)
    if old is None:
        return  # not committed yet: still a draft
    miss = rd.missing_lines(old, new)
    if miss:
        block(f"{rel} is append-only once committed; this edit removes or rewrites {len(miss)} committed line(s), "
              f"first: {miss[0][:120]!r}. Keep the original text and add an erratum section below it.")


def main() -> None:
    try:
        data = json.load(sys.stdin)
        root = rd.project_root(data.get("cwd"))
        cfg = rd.load_config(root)
        if cfg is None:
            return
        tool, ti = data.get("tool_name", ""), data.get("tool_input") or {}
        if tool == "Bash":
            check_bash(root, cfg, ti.get("command", ""))
        elif tool in ("Edit", "MultiEdit", "Write"):
            check_edit(root, cfg, tool, ti)
    except SystemExit:
        raise
    except Exception as e:  # fail closed: a broken guard must not wave calls through
        block(f"guard error ({type(e).__name__}: {e}); fix the guard or .rak/discipline.json, do not disable it")


if __name__ == "__main__":
    main()
