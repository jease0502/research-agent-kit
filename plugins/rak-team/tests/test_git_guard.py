"""git_guard hook: whole-tree staging/committing is blocked, named paths are allowed. Called like Claude Code does."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "hooks" / "git_guard.py"

BLOCK = [
    "git add -A", "git add --all", "git add .", "git add ./", "git add -- .", "git add :/", "git add -u",
    "git add --update", "git add -Av", "git add *",
    "git commit -a -m 'x'", "git commit -am 'x'", "git commit --all -m x", "git commit -avm x",
    "git -C /some/repo add -A", "git -c core.autocrlf=false commit -am x", "GIT_DIR=.git git add .",
    "cd sub && git add . && git commit -m x", "git status; git add -A", "(git add .)", "sudo git add -A",
    "git add src/a.py && git commit -am 'msg'",
]
ALLOW = [
    "git add -- src/a.py docs/b.md", "git add src/a.py", "git commit -m 'add -A is banned' -- src/a.py",
    "git commit -m '-a in a message'", "git commit -F msg.txt -- a.py", "git commit --amend --no-edit -- a.py",
    "git add -A src/", "git add -u src/a.py", "git status", "git diff --cached --stat", "git log -1",
    "echo 'git add -A'", "grep -r 'git add .' docs", "git commit -m x --author='A <a@example.com>' -- f",
    "git commit -ma", "ls -la",
]


def run(command, cwd=None, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd) if cwd else None})
    return subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True)


@pytest.mark.parametrize("cmd", BLOCK)
def test_blocked(cmd, tmp_path):
    r = run(cmd, tmp_path)
    assert r.returncode == 2, f"{cmd!r} should be blocked: {r.stderr}"
    assert "git add --" in r.stderr   # tells you what to do instead


@pytest.mark.parametrize("cmd", ALLOW)
def test_allowed(cmd, tmp_path):
    r = run(cmd, tmp_path)
    assert r.returncode == 0, f"{cmd!r} should pass: {r.stderr}"


def test_other_tools_ignored(tmp_path):
    assert run("git add -A", tmp_path, tool="Write").returncode == 0


def test_opt_out_for_single_session_repo(tmp_path):
    (tmp_path / ".rak").mkdir(); (tmp_path / ".rak" / "team.json").write_text('{"shared_worktree": false}')
    assert run("git add -A", tmp_path).returncode == 0
    (tmp_path / ".rak" / "team.json").write_text('{"shared_worktree": true}')
    assert run("git add -A", tmp_path).returncode == 2


def test_bad_config_fails_closed(tmp_path):
    (tmp_path / ".rak").mkdir(); (tmp_path / ".rak" / "team.json").write_text('{"shared_worktre": false}')
    r = run("git status", tmp_path)
    assert r.returncode == 2 and "unknown keys" in r.stderr


def test_known_gap_alias_or_script_is_not_seen(tmp_path):
    # documented limit: the hook reads command text, not what a script or alias runs
    assert run("./commit_everything.sh", tmp_path).returncode == 0
