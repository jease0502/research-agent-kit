"""rak-discipline's rules (D1-D6 in docs/policy-engine.md): no experiment launch without a frozen prereg, no reading
results before the gate passes, committed results docs are append-only.

Moved from plugins/rak-discipline/hooks/guard.py unchanged. What "frozen", "gate" and "append-only" mean stays in
rak-discipline's own module (scripts/rak_discipline.py): the adapter passes it in as the event's "discipline"
backend, so the freeze semantics have one home. Each check returns None when the project has not opted in
(no .rak/discipline.json); a bad config raises, and the caller blocks (fail closed).
"""
from __future__ import annotations

import re
from pathlib import Path

EDIT_CONSTRUCTS = [
    r"\bsed\b[^|;&]*\s-i", r"\bperl\b[^|;&]*\s-[a-z]*i", r"(?<![>&0-9])>(?!>)\s*\S", r"\btruncate\b",
    r"\brm\b", r"\bgit\s+rm\b", r"\bmv\b", r"\btee\b(?![^|;&]*\s-a)", r"\bcp\b", r"\bdd\b",
]


def _setup(event):
    rd = event.backends["discipline"]
    root = rd.project_root(event.cwd)
    return rd, root, rd.load_config(root)


def prereg_id(cmd: str, token: str) -> str | None:
    m = re.search(rf"\b{re.escape(token)}=([A-Za-z0-9-]+)", cmd)
    return m.group(1) if m else None


def launch(event) -> str | None:
    """D1, D2: an experiment launch carries a prereg id, frozen and unchanged."""
    rd, root, cfg = _setup(event)
    if cfg is None:
        return None
    cmd, token = event.args.get("command", ""), cfg["prereg_token"]
    if any(re.search(p, cmd) for p in cfg["experiment_patterns"]):
        pid = prereg_id(cmd, token)
        if not pid:
            return (f"this looks like an experiment launch (matches experiment_patterns) but carries no {token}=<id>. "
                    "Freeze a prereg first, then launch with that id.")
        try:
            rd.verify_frozen(root, pid)
        except rd.DisciplineError as e:
            return str(e)
    return None


def verdict(event) -> str | None:
    """D3, D4: reading results needs the id, and its gate PASS against the frozen files."""
    rd, root, cfg = _setup(event)
    if cfg is None:
        return None
    cmd, token = event.args.get("command", ""), cfg["prereg_token"]
    if any(re.search(p, cmd) for p in cfg["verdict_patterns"]):
        pid = prereg_id(cmd, token)
        if not pid:
            return f"reading results needs {token}=<id> so the gate can be checked"
        try:
            rd.require_gate_pass(root, pid)
        except rd.DisciplineError as e:
            return str(e)
    return None


def results_shell(event) -> str | None:
    """D5: no shell edit or delete of a committed results doc."""
    rd, root, cfg = _setup(event)
    if cfg is None:
        return None
    cmd = event.args.get("command", "")
    if cfg["results_globs"] and any(re.search(p, cmd) for p in EDIT_CONSTRUCTS):
        for tok in re.findall(r"[\w./\\-]+\.\w+", cmd):
            rel = tok.replace("\\", "/").lstrip("./")
            if rd.matches_any(rel, cfg["results_globs"]) and rd.head_version(root, rel) is not None:
                return (f"{rel} is an append-only results doc; shell edits/deletes of it are not allowed. "
                        "Use Edit to add an erratum section.")
    return None


def proposed_content(root: Path, event) -> tuple[str, str] | None:
    path = Path(event.args.get("path", ""))
    if not path.is_absolute():
        path = root / path
    try:
        rel = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    cur = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
    if event.tool == "file.write":
        return rel, event.args.get("content", "")
    new = cur
    for e in event.args.get("edits") or []:
        old_s, new_s = e.get("old_string", ""), e.get("new_string", "")
        new = new.replace(old_s, new_s) if e.get("replace_all") else new.replace(old_s, new_s, 1)
    return rel, new


def results_edit(event) -> str | None:
    """D6: an edit of a committed results doc keeps every committed body line."""
    rd, root, cfg = _setup(event)
    if cfg is None:
        return None
    pc = proposed_content(root, event)
    if pc is None:
        return None
    rel, new = pc
    if not rd.matches_any(rel, cfg["results_globs"]):
        return None
    old = rd.head_version(root, rel)
    if old is None:
        return None  # not committed yet: still a draft
    miss = rd.missing_lines(old, new)
    if miss:
        return (f"{rel} is append-only once committed; this edit removes or rewrites {len(miss)} committed line(s), "
                f"first: {miss[0][:120]!r}. Keep the original text and add an erratum section below it.")
    return None
