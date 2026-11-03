"""Differential test: each Claude Code hook before the policy engine (plugins/*/tests/legacy_*.py, frozen copies)
against the hook now (an adapter over python/rak/policy), on the same inputs. Exit code and stderr must be equal
for every sample.

Generated samples only; nothing from real sessions is in this file. The run over real commands from this machine's
transcripts is test_policy_differential_local.py, which reads them at test time and commits only counts.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "plugins"
HOOKS = {
    "team": (PLUGINS / "rak-team/tests/legacy_git_guard.py", PLUGINS / "rak-team/hooks/git_guard.py"),
    "discipline": (PLUGINS / "rak-discipline/tests/legacy_guard.py", PLUGINS / "rak-discipline/hooks/guard.py"),
    "trees": (PLUGINS / "rak-cloud/tests/legacy_tree_guard.py", PLUGINS / "rak-cloud/hooks/tree_guard.py"),
}
_MODS: dict[Path, object] = {}


def module(path: Path):
    if path not in _MODS:
        spec = importlib.util.spec_from_file_location(f"hook_{len(_MODS)}_{path.stem}", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MODS[path] = m
    return _MODS[path]


def call(path: Path, payload: dict, env: dict) -> tuple[int, str]:
    """Run a hook's main() in-process: (exit code, stderr)."""
    m = module(path)
    err, old_in, old_env = io.StringIO(), sys.stdin, dict(os.environ)
    sys.stdin = io.StringIO(json.dumps(payload))
    for k in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    code = 0
    try:
        with contextlib.redirect_stderr(err):
            m.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old_in
        os.environ.clear(); os.environ.update(old_env)
    return code, err.getvalue()


def compare(kind: str, payloads, env: dict | None = None) -> dict:
    old, new = HOOKS[kind]
    stats = {"n": 0, "blocked": 0, "errors": 0}
    for p in payloads:
        a, b = call(old, p, env or {}), call(new, p, env or {})
        assert a == b, f"{kind}: {json.dumps(p)[:300]}\n old={a}\n new={b}"
        stats["n"] += 1
        stats["blocked"] += a[0] == 2
        stats["errors"] += "error (" in a[1]
    return stats


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, capture_output=True, check=True)


# ---------------------------------------------------------------- rak-team

PREFIX = ["", "", "", "FOO=1 ", "sudo ", "env ", "command ", "time ", "nohup ", "GIT_DIR=.git "]
GLOBAL = ["", "", "", "-C /some/repo ", "-c core.autocrlf=false ", "--git-dir=.git ", "--no-pager ", "-C ", "--work-tree x "]
ADD_ARGS = ["-A", "--all", "-u", "--update", "-Av", "-uv", "-n", "-v", "-p", "--", ".", "./", ":/", ":(top)", "*", ":/.",
            "src/a.py", "docs/", "--chmod=+x", "--chmod", "+x", "--pathspec-from-file", "f.txt", "--no-ignore-removal",
            "-N", "--intent-to-add", "'.'", '"-A"', "-", "-fA"]
COMMIT_ARGS = ["-a", "--all", "-am", "-ma", "-m", "'msg -a'", "x", "-F", "msg.txt", "-C", "HEAD", "-c", "--amend",
               "--no-edit", "--", "a.py", "-avm", "-mfoo", "-S", "--fixup", "abc", "--author='A <a@example.com>'",
               "-v", "--message=x", "-t", "tpl", "-q", "--trailer", "k=v", "-Sa", "-Fa"]
OTHER = ["status", "diff --cached", "log -1", "push", "rm -r .", "checkout -- .", "stash -a", "reset --hard"]
WRAP = ["{}", "{}", "{}", "({})", "echo '{}'", "grep -r '{}' docs", "cd sub && {}", "{} && git status",
        "git status; {}", "{} | cat", "{} || true", "{} &", "true\n{}", "bash -c '{}'", "{} 2>&1"]


def git_command(rng: random.Random) -> str:
    sub = rng.choice(["add", "add", "commit", "commit", "other"])
    if sub == "other":
        core = rng.choice(OTHER)
    else:
        pool = ADD_ARGS if sub == "add" else COMMIT_ARGS
        core = sub + "".join(" " + rng.choice(pool) for _ in range(rng.randint(0, 5)))
    cmd = f"{rng.choice(PREFIX)}{rng.choice(['git', 'git', 'git.exe', '/usr/bin/git'])} {rng.choice(GLOBAL)}{core}"
    if rng.random() < 0.05:
        cmd += " '"                                              # unbalanced quote: shlex fails, split() fallback
    return rng.choice(WRAP).format(cmd)


@pytest.fixture(scope="module")
def team_dirs():
    t = Path(tempfile.mkdtemp(prefix="rakpol-team-"))
    dirs = {}
    for name, team in (("plain", None), ("opt_out", {"shared_worktree": False}), ("opt_in", {"shared_worktree": True}),
                       ("bad", {"shared_worktree": False, "typo": 1})):
        d = t / name; d.mkdir(); git(d, "init", "-q")
        if team is not None:
            (d / ".rak").mkdir(); (d / ".rak/team.json").write_text(json.dumps(team))
        (d / "sub").mkdir()
        dirs[name] = d
    dirs["nogit"] = t / "nogit"; dirs["nogit"].mkdir()
    yield dirs
    shutil.rmtree(t, ignore_errors=True)


def test_team_matches_legacy(team_dirs):
    rng = random.Random(1031)
    payloads = []
    for _ in range(3000):
        tool = rng.choices(["Bash", "Edit", "Write", "Read"], [0.94, 0.02, 0.02, 0.02])[0]
        d = rng.choice(list(team_dirs.values()) + [None])
        cwd = None if d is None else str(d / "sub" if (d / "sub").exists() and rng.random() < 0.3 else d)
        ti = {"command": git_command(rng)} if rng.random() > 0.01 else rng.choice([{}, {"command": None}, None])
        payloads.append({"tool_name": tool, "tool_input": ti, "cwd": cwd})
    s = compare("team", payloads, {"CLAUDE_PROJECT_DIR": str(team_dirs["plain"])})
    assert s["blocked"] > 300 and s["n"] - s["blocked"] > 300 and s["errors"] > 10, s


# ---------------------------------------------------------------- rak-cloud trees

def test_trees_matches_legacy():
    rng = random.Random(7)
    root = PLUGINS / "rak-cloud"
    paths = [root / "trees/lifecycle.json", root / "trees/new.json", root / "trees", root / "trees/../trees/x.json",
             root / "README.md", root / "scripts/rak_cloud.py", root / "treesx/a.json", Path("trees/lifecycle.json"),
             Path("lifecycle.json"), Path("../rak-cloud/trees/a.json"), Path(str(root / "TREES/lifecycle.json"))]
    cmds = ["cat trees/lifecycle.json", "sed -i s/a/b/ trees/lifecycle.json", "head -5 plugins/rak-cloud/trees/lifecycle.json",
            "python scripts/rak_cloud.py wait rak-x", "git diff trees/lifecycle.json", "git checkout trees/lifecycle.json",
            "echo x > trees/lifecycle.json", "grep -i zone trees/lifecycle.json > out.txt", "ls trees", "rm -r trees",
            "cat lifecycle.json | python -c 'import sys'", "wc -l trees\\lifecycle.json", "cp a.json trees/b.json",
            "cat 'trees/lifecycle.json", "ls; cat trees/x.json && vim trees/x.json", ""]
    payloads = []
    for _ in range(1500):
        tool = rng.choice(["Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "Bash", "Read", "Glob"])
        cwd = rng.choice([str(root), str(PLUGINS), str(REPO), None])
        if tool == "Bash":
            ti = {"command": rng.choice(cmds)}
        else:
            key = "notebook_path" if tool == "NotebookEdit" else "file_path"
            ti = {key: str(rng.choice(paths))} if rng.random() > 0.05 else rng.choice([{}, {key: None}])
        payloads.append({"tool_name": tool, "tool_input": ti, "cwd": cwd})
    s = compare("trees", payloads, {"CLAUDE_PLUGIN_ROOT": str(root)})
    assert s["blocked"] > 200 and s["n"] - s["blocked"] > 200, s
    s2 = compare("trees", payloads[:300], {})                  # no CLAUDE_PLUGIN_ROOT: both fall back to the file's plugin
    assert s2["n"] == 300


# ---------------------------------------------------------------- rak-discipline

PREREG = """---
id: "demo-run"
title: "demo"
status: draft
verdict_script: "verdict.py"
created: "2026-01-01"
---

# demo
"""
RESULTS = "---\ntitle: r\n---\n\n# Results\n\nC1 PASS: 0.071 (n=5).\nThe treatment arm was faster.\n"


def discipline_repo(base: Path, state: str) -> Path:
    d = base / state
    d.mkdir()
    git(d, "init", "-q"); git(d, "config", "user.email", "t@example.invalid"); git(d, "config", "user.name", "t")
    git(d, "config", "core.autocrlf", "false")
    cfg = {"experiment_patterns": [r"python\s+train\.py", r"\bbash\s+run_\w+\.sh"], "results_globs": ["results/*.md"]}
    if state == "bad_config":
        cfg["typo"] = 1
    (d / ".rak").mkdir()
    (d / ".rak/discipline.json").write_text(json.dumps(cfg))
    (d / "prereg.md").write_text(PREREG, newline="\n")
    (d / "verdict.py").write_text("print('v')\n", newline="\n")
    (d / "results").mkdir(); (d / "results/r.md").write_text(RESULTS, newline="\n")
    (d / "results/draft.md").write_text(RESULTS, newline="\n")
    git(d, "add", "--", ".rak/discipline.json", "prereg.md", "verdict.py", "results/r.md"); git(d, "commit", "-q", "-m", "c")
    if state in ("frozen", "frozen_changed", "gate_pass", "gate_fail", "gate_stale"):
        cli = PLUGINS / "rak-discipline/scripts/rak_discipline.py"
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        r = subprocess.run([sys.executable, str(cli), "freeze", "prereg.md"], cwd=d, capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        rec = json.loads((d / ".rak/frozen/demo-run.json").read_text())
        if state.startswith("gate"):
            g = {"id": "demo-run", "status": "FAIL" if state == "gate_fail" else "PASS",
                 "prereg_sha256": rec["prereg_sha256"] if state != "gate_stale" else "0" * 64,
                 "verdict_sha256": rec["verdict_sha256"], "checks": {}}
            (d / ".rak/gates").mkdir(); (d / ".rak/gates/demo-run.json").write_text(json.dumps(g))
        if state == "frozen_changed":
            (d / "prereg.md").write_text(PREREG + "\nchanged\n", newline="\n")
    if state == "no_config":
        (d / ".rak/discipline.json").unlink()
    return d


STATES = ["no_config", "bad_config", "unfrozen", "frozen", "frozen_changed", "gate_pass", "gate_fail", "gate_stale"]
SHELL = ["python train.py --seed 1", "RAK_PREREG=demo-run python train.py", "RAK_PREREG=other python train.py",
         "RAK_PREREG= python train.py", "bash run_all.sh", "RAK_PREREG=demo-run bash run_all.sh",
         "python verdict.py judge", "RAK_PREREG=demo-run python verdict.py judge", "python verdict.py  judge x",
         "sed -i 's/PASS/FAIL/' results/r.md", "echo x > results/r.md", "echo x >> results/r.md", "rm results/r.md",
         "git rm results/r.md", "mv results/r.md results/old.md", "tee results/r.md < x", "tee -a results/r.md",
         "cp x.md results/r.md", "truncate -s 0 results/r.md", "rm results/draft.md", "sed -i s/a/b/ notes.md",
         "cat results/r.md", "perl -pi -e 's/a/b/' results/r.md", "dd if=/dev/zero of=results/r.md",
         "rm ./results/r.md", "rm results\\r.md", "ls -la", "git status", "python train.py; rm results/r.md"]


def edit_payloads(d: Path, rng: random.Random):
    target = rng.choice(["results/r.md", str(d / "results/r.md"), "results/draft.md", "notes.md", "../outside.md",
                         "results/new.md", "results/R.md"])
    keep = "C1 PASS: 0.071 (n=5)."
    tool = rng.choice(["Edit", "MultiEdit", "Write"])
    if tool == "Write":
        content = rng.choice([RESULTS + "\n## Erratum\nx\n", RESULTS.replace(keep, "C1 FAIL"), "", RESULTS.replace("title: r", "title: s")])
        return tool, {"file_path": target, "content": content}
    edits = [{"old_string": rng.choice([keep, "The treatment arm was faster.", "title: r", "\n", "", "nope"]),
              "new_string": rng.choice([keep + "\nmore", "x", "", keep]), "replace_all": rng.random() < 0.3}
             for _ in range(rng.randint(1, 3))]
    if tool == "Edit":
        return tool, {"file_path": target, **edits[0]}
    return tool, {"file_path": target, "edits": edits}


@pytest.fixture(scope="module")
def discipline_repos():
    t = Path(tempfile.mkdtemp(prefix="rakpol-disc-"))
    repos = {s: discipline_repo(t, s) for s in STATES}
    yield repos
    shutil.rmtree(t, ignore_errors=True)


def test_discipline_matches_legacy(discipline_repos):
    rng = random.Random(42)
    payloads = []
    for _ in range(1200):
        d = discipline_repos[rng.choice(STATES)]
        if rng.random() < 0.6:
            tool, ti = "Bash", {"command": rng.choice(SHELL)}
        else:
            tool, ti = edit_payloads(d, rng)
        if rng.random() < 0.02:
            ti = rng.choice([{}, {"file_path": None}, {"command": None}, None])
        payloads.append({"tool_name": tool, "tool_input": ti, "cwd": str(d)})
    s = compare("discipline", payloads)
    assert s["blocked"] > 200 and s["n"] - s["blocked"] > 200 and s["errors"] > 10, s


# ---------------------------------------------------------------- the differential test must see a difference

def test_a_changed_rule_is_caught(team_dirs, monkeypatch):
    import importlib
    sys.path.insert(0, str(PLUGINS / "rak-team/_vendor"))
    pol = importlib.import_module("rak_policy.checks_git")
    monkeypatch.setattr(pol, "WHOLE_TREE", pol.WHOLE_TREE - {":/"})          # a loosened rule
    with pytest.raises(AssertionError):
        compare("team", [{"tool_name": "Bash", "tool_input": {"command": "git add :/"}, "cwd": str(team_dirs["plain"])}])
