"""rak-team's rule: no whole-tree staging or committing in a shared working tree (T1-T3 in docs/policy-engine.md).

Moved from plugins/rak-team/hooks/git_guard.py unchanged, except that opted_out() reads CLAUDE_PROJECT_DIR from the
event's environment instead of the process's.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

GLOBAL_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
COMMIT_OPTS_WITH_VALUE = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
                          "--author", "--date", "-t", "--template", "--fixup", "--squash", "--cleanup",
                          "--trailer", "--pathspec-from-file", "-S", "--gpg-sign"}
ADD_OPTS_WITH_VALUE = {"--chmod", "--pathspec-from-file"}
WHOLE_TREE = {".", "./", ":/", ":(top)", ":/.", "*", ":(top)."}
SEPARATORS = re.compile(r"\|\||&&|;|\||\n|&(?!>)")


def segments(cmd: str):
    for part in SEPARATORS.split(cmd):
        part = part.strip().lstrip("(").rstrip(")").strip()
        if part:
            yield part


def git_invocation(tokens: list[str]):
    """Return (subcommand, args) if tokens run git, skipping env assignments, sudo/env/command prefixes and
    git's global options; else None."""
    i = 0
    while i < len(tokens) and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[i]) or tokens[i] in ("sudo", "env", "command", "time", "nohup")):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) not in ("git", "git.exe"):
        return None
    i += 1
    while i < len(tokens) and tokens[i].startswith("-"):
        t = tokens[i]
        if t in GLOBAL_OPTS_WITH_VALUE:
            i += 2
        else:
            i += 1
    if i >= len(tokens):
        return None
    return tokens[i], tokens[i + 1:]


def check_add(args: list[str]) -> str | None:
    broad, pathspecs, i, after_dd = False, [], 0, False
    while i < len(args):
        a = args[i]
        if after_dd:
            pathspecs.append(a)
        elif a == "--":
            after_dd = True
        elif a in ("-A", "--all", "-u", "--update", "--no-ignore-removal"):
            broad = True
        elif a in ADD_OPTS_WITH_VALUE:
            i += 1
        elif a.startswith("--"):
            pass
        elif a.startswith("-") and len(a) > 1:
            if "A" in a[1:] or "u" in a[1:]:
                broad = True
        else:
            pathspecs.append(a)
        i += 1
    whole = [p for p in pathspecs if p in WHOLE_TREE]
    if whole:
        return f"`git add {whole[0]}` stages the whole tree"
    if broad and not pathspecs:
        return "`git add -A/-u` without a pathspec stages every change in the tree"
    return None


def check_commit(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a in ("--all", "-a"):
            return "`git commit -a` commits every tracked change, including other sessions'"
        if a in COMMIT_OPTS_WITH_VALUE or (a.startswith("--") and "=" not in a and a in COMMIT_OPTS_WITH_VALUE):
            i += 2
            continue
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            cluster = a[1:]
            # options that take a value consume the rest of the cluster: -mfoo, -Cabc
            for j, ch in enumerate(cluster):
                if ch == "a":
                    return f"`git commit {a}` includes -a: every tracked change gets committed"
                if ch in "mFCctS":
                    if j == len(cluster) - 1:
                        i += 1          # value is the next token
                    break
        i += 1
    return None


def check_command(cmd: str) -> str | None:
    for seg in segments(cmd):
        try:
            tokens = shlex.split(seg, posix=True)
        except ValueError:
            tokens = seg.split()
        inv = git_invocation(tokens)
        if not inv:
            continue
        sub, args = inv
        why = check_add(args) if sub == "add" else check_commit(args) if sub == "commit" else None
        if why:
            return why
    return None


def opted_out(cwd: str | None, env) -> bool:
    p = Path(cwd or env.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        f = d / ".rak" / "team.json"
        if f.is_file():
            cfg = json.loads(f.read_text(encoding="utf-8"))
            unknown = set(cfg) - {"shared_worktree"}
            if unknown:
                raise ValueError(f".rak/team.json has unknown keys {sorted(unknown)}")
            return cfg.get("shared_worktree") is False
        if (d / ".git").exists():
            return False
    return False


def git_whole_tree(event) -> str | None:
    if opted_out(event.cwd, event.env):
        return None
    return check_command(event.args.get("command", ""))
