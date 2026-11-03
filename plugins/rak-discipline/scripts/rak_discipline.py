#!/usr/bin/env python3
"""rak-discipline: freeze a pre-registration, record gates, enforce append-only result docs.

Standard library only. Subcommands:

  freeze PREREG.md            record the prereg + verdict-script hashes at the current commit
  status ID                   show freeze / gate state for a prereg id
  check-frozen ID             exit 0 if the prereg and its verdict script still match the freeze record
  gate-status ID              print PASS / FAIL / NONE
  check-append-only FILE      committed lines of FILE must survive, in order (default base: HEAD)
  check-append-only --staged  same check for every staged file matching results_globs (git pre-commit)
  install-git-hook            install a pre-commit hook that runs check-append-only --staged

State lives in <project>/.rak/ (frozen/<id>.json, gates/<id>.json). Commit it.
Configuration: <project>/.rak/discipline.json (see templates/discipline.json).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CONFIG = {
    "experiment_patterns": [],          # regexes; a Bash command matching one is an experiment launch
    "verdict_patterns": [r"verdict\.py\s+judge"],
    "results_globs": [],                # glob patterns (relative to project root) of append-only docs
    "prereg_token": "RAK_PREREG",       # experiment commands carry RAK_PREREG=<id>
}


class DisciplineError(Exception):
    pass


# ---------- project / config ----------

def project_root(start: str | os.PathLike | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    p = Path(start or env or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / ".rak").is_dir() or (d / ".git").exists():
            return d
    return p


def load_config(root: Path) -> dict | None:
    """None when the project has not opted in (no .rak/discipline.json) -> hooks do nothing."""
    f = root / ".rak" / "discipline.json"
    if not f.is_file():
        return None
    cfg = dict(DEFAULT_CONFIG)
    user = json.loads(f.read_text(encoding="utf-8"))
    unknown = set(user) - set(DEFAULT_CONFIG)
    if unknown:  # a typo in a guard's config must not silently disable the guard
        raise DisciplineError(f"unknown keys in .rak/discipline.json: {sorted(unknown)}")
    cfg.update(user)
    return cfg


# ---------- hashing / git ----------

def norm_sha256(path: Path) -> str:
    """sha256 of the file with CRLF normalised to LF (autocrlf must not change the hash)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise DisciplineError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def committed_clean(root: Path, rel: str) -> str:
    """Return the last commit touching rel; raise if rel is untracked or has uncommitted changes."""
    if git(root, "status", "--porcelain", "--", rel).strip():
        raise DisciplineError(f"{rel} has uncommitted changes (or is untracked); commit it first")
    h = git(root, "log", "-1", "--format=%H", "--", rel).strip()
    if not h:
        raise DisciplineError(f"{rel} is not committed")
    return h


def head_version(root: Path, rel: str, rev: str = "HEAD") -> str | None:
    r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=root, capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8").replace("\r\n", "\n")


# ---------- frontmatter ----------

def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-", "#")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def frontmatter_list(text: str, key: str) -> list[str]:
    """A list-valued frontmatter key, as `key: [a, b]` or as a block of `  - a` lines. Missing -> []."""
    m = re.match(r"^---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    if not m:
        return []
    lines = m.group(1).splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        rest = line.split(":", 1)[1].strip()
        if rest.startswith("["):
            if not rest.endswith("]"):
                raise DisciplineError(f"`{key}` inline list is not closed on its line")
            return [v.strip().strip('"').strip("'") for v in rest[1:-1].split(",") if v.strip()]
        if rest:
            raise DisciplineError(f"`{key}` must be a list ([a, b] or `- item` lines)")
        out = []
        for nxt in lines[i + 1:]:
            if re.match(r"^\s+-\s", nxt):
                out.append(nxt.split("-", 1)[1].strip().strip('"').strip("'"))
            elif nxt.strip() and not nxt.startswith((" ", "\t")):
                break
        return out
    return []


def split_frontmatter(text: str) -> tuple[str, str]:
    text = text.replace("\r\n", "\n")
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    return (m.group(0), text[m.end():]) if m else ("", text)


# ---------- freeze ----------

TREE_IGNORE_DIRS = {"__pycache__", ".pytest_cache", ".git"}
TREE_IGNORE_SUFFIXES = (".pyc", ".pyo")


def tree_hashes(folder: Path) -> dict[str, str]:
    """{relative path: LF-normalised sha256} for every file under folder, caches excluded. Every file counts,
    tracked or not: a skill added to a plugin folder changes the treatment as much as an edit does."""
    out = {}
    for f in sorted(folder.rglob("*")):
        rel = f.relative_to(folder)
        if not f.is_file() or set(rel.parts) & TREE_IGNORE_DIRS or f.name.endswith(TREE_IGNORE_SUFFIXES):
            continue
        out[rel.as_posix()] = norm_sha256(f)
    return out


def tree_diff(frozen: dict[str, str], now: dict[str, str]) -> list[str]:
    return ([f"added {p}" for p in sorted(set(now) - set(frozen))]
            + [f"removed {p}" for p in sorted(set(frozen) - set(now))]
            + [f"changed {p}" for p in sorted(set(now) & set(frozen)) if now[p] != frozen[p]])


def freeze(prereg: Path, root: Path) -> dict:
    rel = prereg.resolve().relative_to(root).as_posix()
    fm = frontmatter(prereg.read_text(encoding="utf-8"))
    pid = fm.get("id")
    if not pid or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", pid):
        raise DisciplineError(f"{rel}: frontmatter `id` missing or not kebab-case")
    vs = fm.get("verdict_script")
    if not vs:
        raise DisciplineError(f"{rel}: frontmatter `verdict_script` is required (write the reading rules before the data)")
    vpath = (root / vs).resolve()
    if not vpath.is_file():
        raise DisciplineError(f"verdict_script {vs} does not exist")
    vrel = vpath.relative_to(root).as_posix()
    rec_path = root / ".rak" / "frozen" / f"{pid}.json"
    if rec_path.exists():
        raise DisciplineError(f"{pid} is already frozen ({rec_path}); changes after freezing go in an erratum, not a re-freeze")
    commit = committed_clean(root, rel)
    committed_clean(root, vrel)
    # Everything else the verdict depends on - the scorer, thresholds, chance tables, task definitions - is
    # frozen with it. Freezing only the prereg and the verdict script left the scorer editable after the fact
    # (2026-10-31 review C2: a 10x looser scorer still passed the gate, and nothing noticed).
    frozen_files = {}
    for f in frontmatter_list(prereg.read_text(encoding="utf-8"), "frozen_files"):
        p = (root / f).resolve()
        if not p.is_relative_to(root):
            raise DisciplineError(f"frozen_files: {f} is outside the project")
        if not p.is_file():
            raise DisciplineError(f"frozen_files: {f} does not exist (list files, not folders)")
        frel = p.relative_to(root).as_posix()
        committed_clean(root, frel)
        frozen_files[frel] = norm_sha256(p)
    # Whole folders, file by file - typically the plugin or prompt set that *is* the treatment (review of the
    # fabrication audit: the harness loads plugins from the working tree at run time, so an edit after freezing
    # silently changed what the arms compared).
    frozen_trees = {}
    for d in frontmatter_list(prereg.read_text(encoding="utf-8"), "frozen_trees"):
        p = (root / d).resolve()
        if not p.is_relative_to(root):
            raise DisciplineError(f"frozen_trees: {d} is outside the project")
        if not p.is_dir():
            raise DisciplineError(f"frozen_trees: {d} is not a folder (use frozen_files for single files)")
        drel = p.relative_to(root).as_posix()
        if git(root, "status", "--porcelain", "--untracked-files=all", "--", drel).strip():
            raise DisciplineError(f"frozen_trees: {drel} has uncommitted or untracked files; commit or remove them first")
        frozen_trees[drel] = tree_hashes(p)
        if not frozen_trees[drel]:
            raise DisciplineError(f"frozen_trees: {drel} has no files")
    rec = {
        "id": pid,
        "prereg": rel,
        "prereg_sha256": norm_sha256(prereg),
        "verdict_script": vrel,
        "verdict_sha256": norm_sha256(vpath),
        "frozen_files": frozen_files,
        "frozen_trees": frozen_trees,
        "commit": commit,
        "frozen_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return rec


def freeze_record(root: Path, pid: str) -> dict | None:
    f = root / ".rak" / "frozen" / f"{pid}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def verify_frozen(root: Path, pid: str) -> dict:
    """Raise unless pid is frozen and both files still hash to the frozen values."""
    rec = freeze_record(root, pid)
    if rec is None:
        raise DisciplineError(f"prereg `{pid}` is not frozen (run: rak_discipline.py freeze <prereg.md>)")
    for key in ("prereg", "verdict_script"):
        p = root / rec[key]
        if not p.is_file():
            raise DisciplineError(f"{rec[key]} (frozen {key}) is missing")
        if norm_sha256(p) != rec[f"{'prereg' if key == 'prereg' else 'verdict'}_sha256"]:
            raise DisciplineError(
                f"{rec[key]} changed after freezing; the frozen version is in commit {rec['commit'][:10]}. "
                "Corrections go in an erratum section of the results doc, not in the prereg.")
    for frel, sha in (rec.get("frozen_files") or {}).items():
        p = root / frel
        if not p.is_file():
            raise DisciplineError(f"{frel} (frozen with the prereg) is missing")
        if norm_sha256(p) != sha:
            raise DisciplineError(
                f"{frel} (frozen with the prereg) changed after freezing; the frozen version is in commit "
                f"{rec['commit'][:10]}. A changed scorer or table is a new registration, not an edit.")
    for drel, files in (rec.get("frozen_trees") or {}).items():
        p = root / drel
        diff = tree_diff(files, tree_hashes(p) if p.is_dir() else {})
        if diff:
            raise DisciplineError(
                f"{drel}/ (frozen with the prereg) changed after freezing: {'; '.join(diff[:5])}"
                f"{' ...' if len(diff) > 5 else ''}. The frozen version is in commit {rec['commit'][:10]}.")
    return rec


# ---------- gates ----------

def write_gate(root: Path, pid: str, results: dict[str, dict]) -> str:
    """results: name -> {"value": float, "lo": float|None, "hi": float|None, "passed": bool}.
    Called by the frozen verdict script, never by hand."""
    rec = verify_frozen(root, pid)
    status = "PASS" if results and all(r["passed"] for r in results.values()) else "FAIL"
    out = {
        "id": pid,
        "status": status,
        "prereg_sha256": rec["prereg_sha256"],
        "verdict_sha256": rec["verdict_sha256"],
        "checks": results,
        "written_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    f = root / ".rak" / "gates" / f"{pid}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    return status


def gate_status(root: Path, pid: str) -> str:
    f = root / ".rak" / "gates" / f"{pid}.json"
    if not f.is_file():
        return "NONE"
    g = json.loads(f.read_text(encoding="utf-8"))
    rec = freeze_record(root, pid)
    if rec is None or g.get("prereg_sha256") != rec["prereg_sha256"] or g.get("verdict_sha256") != rec["verdict_sha256"]:
        return "STALE"  # gate was recorded against a different prereg / verdict script
    return g.get("status", "NONE")


def require_gate_pass(root: Path, pid: str) -> None:
    verify_frozen(root, pid)
    s = gate_status(root, pid)
    if s != "PASS":
        raise DisciplineError(f"gate for `{pid}` is {s}; the verdict refuses to read results until the gate passes")


# ---------- append-only ----------

def missing_lines(old: str, new: str) -> list[str]:
    """Lines of old's body that do not survive, in order, in new's body. Frontmatter is exempt."""
    _, ob = split_frontmatter(old)
    _, nb = split_frontmatter(new)
    new_lines = nb.split("\n")
    j, missing = 0, []
    for line in ob.split("\n"):
        if not line.strip():
            continue  # blank-line reflow is allowed
        k = j
        while k < len(new_lines) and new_lines[k] != line:
            k += 1
        if k == len(new_lines):
            missing.append(line)
        else:
            j = k + 1
    return missing


def matches_any(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) for g in globs)


def check_append_only_staged(root: Path, cfg: dict) -> list[str]:
    errors = []
    names = git(root, "diff", "--cached", "--name-status", "--no-renames").splitlines()
    for row in names:
        st, _, rel = row.partition("\t")
        if not matches_any(rel, cfg["results_globs"]):
            continue
        old = head_version(root, rel)
        if old is None:
            continue
        if st.startswith("D"):
            errors.append(f"{rel}: deleting a committed results doc is not allowed")
            continue
        new = git(root, "show", f":{rel}").replace("\r\n", "\n")
        miss = missing_lines(old, new)
        if miss:
            errors.append(f"{rel}: {len(miss)} committed line(s) removed or rewritten, first: {miss[0][:120]!r}")
    return errors


PRE_COMMIT = """#!/bin/sh
# installed by rak-discipline: committed lines of results docs may only be added to, never removed or rewritten
exec python "{script}" check-append-only --staged
"""


def install_git_hook(root: Path) -> Path:
    hooks = Path(git(root, "rev-parse", "--git-path", "hooks").strip())
    hooks = hooks if hooks.is_absolute() else root / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    f = hooks / "pre-commit"
    if f.exists() and "rak-discipline" not in f.read_text(encoding="utf-8", errors="replace"):
        raise DisciplineError(f"{f} exists and is not ours; chain it by hand")
    f.write_text(PRE_COMMIT.format(script=Path(__file__).resolve().as_posix()), encoding="utf-8", newline="\n")
    f.chmod(0o755)
    return f


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rak_discipline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("freeze"); p.add_argument("prereg")
    p = sub.add_parser("status"); p.add_argument("id")
    p = sub.add_parser("check-frozen"); p.add_argument("id")
    p = sub.add_parser("gate-status"); p.add_argument("id")
    p = sub.add_parser("check-append-only"); p.add_argument("file", nargs="?"); p.add_argument("--staged", action="store_true"); p.add_argument("--base", default="HEAD")
    sub.add_parser("install-git-hook")
    a = ap.parse_args(argv)  # unknown flags raise: a silently ignored flag runs a different check
    root = project_root()
    try:
        if a.cmd == "freeze":
            rec = freeze(Path(a.prereg), root)
            print(json.dumps(rec, indent=2))
            print(f"frozen. commit .rak/frozen/{rec['id']}.json now.")
        elif a.cmd == "status":
            rec = freeze_record(root, a.id)
            print(f"frozen: {'yes @ ' + rec['commit'][:10] if rec else 'no'}  gate: {gate_status(root, a.id)}")
        elif a.cmd == "check-frozen":
            verify_frozen(root, a.id); print("OK")
        elif a.cmd == "gate-status":
            print(gate_status(root, a.id))
        elif a.cmd == "check-append-only":
            cfg = load_config(root) or dict(DEFAULT_CONFIG)
            if a.staged:
                errs = check_append_only_staged(root, cfg)
            else:
                if not a.file:
                    ap.error("FILE or --staged required")
                rel = Path(a.file).resolve().relative_to(root).as_posix()
                old = head_version(root, rel, a.base)
                errs = [] if old is None else [f"{rel}: removed/rewritten: {m[:120]!r}" for m in
                                               missing_lines(old, (root / rel).read_text(encoding="utf-8"))]
            for e in errs:
                print("BLOCKED", e, file=sys.stderr)
            if errs:
                print("Results docs are append-only: add an erratum section instead (see the erratum skill).", file=sys.stderr)
                return 1
            print("OK")
        elif a.cmd == "install-git-hook":
            print(install_git_hook(root))
    except DisciplineError as e:
        print(f"rak-discipline: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
