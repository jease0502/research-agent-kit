"""Cross-review of 6d87ef3: git subcommands are not a safe allow list. `git fetch --upload-pack='cmd' .` runs a
command, and `git log --output=.git/hooks/pre-commit` writes a hook that the allowed `git commit` then runs. Claude
Code's documentation says the same about argument patterns in general. Each test failed before its fix.

- the agent gets no git at all; the runner commits after the agent ends, a fixed set of steps
- the runner commits only what changed during the run under papers/ and the digest folder (and INDEX.md, which
  the allowed `rak build` writes); any other change made during the run is an error and nothing is committed
- Bash only exact rak commands (no wildcard: arguments are where the danger is); --tools limits the toolset;
  --disallowedTools denies reading credentials and editing .git
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "daily-digest"
sys.path.insert(0, str(SKILL / "scripts"))
import run_digest as R  # noqa: E402

TODAY = dt.date(2026, 1, 15)


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "digest.toml").write_text('topics = ["x"]\n', encoding="utf-8")
    return R.load_config(tmp_path)


def test_no_git_for_the_agent(cfg):
    for push in (False, True):
        tools = R.allowed_tools({**cfg, "push": push}).split(",")
        assert not any("git" in t for t in tools), tools


def test_bash_rules_are_exact_rak_commands(cfg):
    for t in R.allowed_tools(cfg).split(","):
        if t.startswith("Bash"):
            assert "*" not in t and t.startswith("Bash(rak "), t


def test_toolset_and_deny_list(cfg):
    assert set(R.TOOLSET.split(",")) <= {"Read", "Glob", "Grep", "Write", "Edit", "Bash", "WebFetch"}
    deny = R.DENY_TOOLS.split(",")
    for d in ("Read(~/.ssh/**)", "Read(~/.config/**)", "Read(~/.aws/**)", "Read(~/.claude/**)", "Read(**/*.env)",
              "Edit(/.git/**)"):
        assert d in deny
    cmd = R.agent_cmd(cfg)
    assert cmd[cmd.index("--tools") + 1] == R.TOOLSET and cmd[cmd.index("--disallowedTools") + 1].startswith(R.DENY_TOOLS)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "kb"
    (root / "papers").mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("kb\n", encoding="utf-8")
    (root / "papers" / "old.md").write_text("old\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    (root / "notes-of-another-session.md").write_text("wip\n", encoding="utf-8")   # dirty before the run
    return root


def test_runner_commits_only_the_run_s_papers_and_digest(repo, cfg):
    before = R.snapshot(repo)
    (repo / "papers" / "new.md").write_text("new\n", encoding="utf-8")
    (repo / "docs" / "digest").mkdir(parents=True)
    (repo / "docs" / "digest" / "2026-01-15.md").write_text("digest\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert ok, msg
    files = git(repo, "show", "--name-only", "--format=%s", "HEAD").split()
    assert "papers/new.md" in files and "docs/digest/2026-01-15.md" in files
    assert "notes-of-another-session.md" not in files                         # someone else's change
    assert git(repo, "log", "-1", "--format=%s").startswith("paper: daily collection 2026-01-15")


@pytest.mark.parametrize("path", ["README.md", ".gitignore", "scripts/evil.py", "rak.toml"])
def test_a_change_outside_the_allowed_paths_stops_the_commit(repo, cfg, path):
    before = R.snapshot(repo)
    (repo / "papers" / "new.md").write_text("new\n", encoding="utf-8")
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("changed\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert not ok and path in msg
    assert git(repo, "log", "-1", "--format=%s").strip() == "base"                     # nothing committed


def test_a_changed_hook_stops_the_commit(repo, cfg):
    before = R.snapshot(repo)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntouch pwned\n", encoding="utf-8")
    (repo / "papers" / "new.md").write_text("new\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert not ok and "hook" in msg.lower()
    assert not (repo / "pwned").exists()


# ── cross-review of 7cb0405: read-only commands run without a rule; pathspec magic; .git* files ──

def test_reads_outside_the_working_directory_are_blocked_and_no_bare_read_is_allowed(cfg):
    import json
    cmd = R.agent_cmd(cfg)
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert settings["permissions"]["blockReadsOutsideWorkingDirectories"] is True
    allow = R.allowed_tools(cfg).split(",")
    assert not {"Read", "Grep", "Glob"} & set(allow)
    assert all(t.startswith(("WebFetch(domain:", "Bash(rak ", "Edit(/")) for t in allow), allow


def test_deny_list_covers_credentials_and_read_only_commands():
    deny = R.DENY_TOOLS.split(",")
    for d in ("Read(~/.git-credentials)", "Read(~/.docker/**)", "Read(~/.kube/**)", "Read(~/.pypirc)",
              "Read(~/.npmrc)", "Read(~/.cache/huggingface/**)", "Read(**/.env.*)", "Edit(/.git/**)",
              "Bash(cat *)", "Bash(grep *)", "Bash(find *)", "Bash(cd *)", "Bash(git *)"):
        assert d in deny, d
    assert "Read(~/**)" not in deny          # a knowledge base under home must stay readable (deny wins over allow)


def test_bash_keeps_the_project_working_directory(cfg):
    assert R.agent_env()["CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"] == "1"


def test_pathspec_magic_does_not_pull_in_another_file(repo, cfg):
    (repo / "papers" / "old.md").write_text("someone else's edit\n", encoding="utf-8")   # dirty before the run
    before = R.snapshot(repo)
    (repo / "papers" / "[o]ld.md").write_text("run\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert ok, msg
    files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["papers/[o]ld.md"], files


@pytest.mark.parametrize("path", ["papers/.gitattributes", "papers/.gitignore", "papers/notes.py", "papers/x.sh"])
def test_only_markdown_is_committed(repo, cfg, path):
    before = R.snapshot(repo)
    (repo / path).write_text("x\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert not ok and path in msg


def test_git_info_changes_stop_the_commit(repo, cfg):
    before = R.snapshot(repo)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.md filter=evil\n", encoding="utf-8")
    (repo / "papers" / "new.md").write_text("new\n", encoding="utf-8")
    ok, msg = R.commit_results(repo, cfg, before, TODAY)
    assert not ok and "info" in msg


# ── cross-review of 8769c58: the environment, secrets inside the base, a second home-folder layer ──

def test_agent_env_is_an_allow_list(monkeypatch):
    for k, v in (("RAK_CANARY", "c4n4ry"), ("GH_TOKEN", "x"), ("HF_TOKEN", "x"), ("TG_BOT_TOKEN", "x"),
                 ("ANTHROPIC_API_KEY", "sk-test"), ("PATH", "/usr/bin")):
        monkeypatch.setenv(k, v)
    env = R.agent_env()
    assert "RAK_CANARY" not in env and "GH_TOKEN" not in env and "HF_TOKEN" not in env and "TG_BOT_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == "sk-test" and env["PATH"] == "/usr/bin"   # the CLI's own login still works
    assert env["CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"] == "1"


def test_secrets_inside_the_base_are_denied():
    deny = R.DENY_TOOLS.split(",")
    assert "Read(/.git/**)" in deny and "Read(/digest.toml)" in deny     # notify_cmd may carry a token
    for c in ("sort", "ps", "printenv", "env"):
        assert f"Bash({c} *)" in deny and f"Bash({c})" in deny


def test_second_home_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    deny, warn = R.deny_tools(tmp_path / "work" / "kb")
    for d in ("Read(~/.*)", "Read(~/.*/**)", "Read(~/AppData/**)"):
        assert d in deny.split(",")
    assert warn == ""
    deny, warn = R.deny_tools(tmp_path / ".local" / "kb")             # the base itself is under a dot folder
    assert "Read(~/.*)" not in deny.split(",") and "Read(~/.*/**)" not in deny.split(",") and warn
    deny, warn = R.deny_tools(tmp_path / "AppData" / "kb")
    assert "Read(~/AppData/**)" not in deny.split(",") and warn


def test_appdata_siblings_stay_denied(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    deny, warn = R.deny_tools(tmp_path / "AppData" / "Local" / "Temp" / "kb")
    rules = deny.split(",")
    assert "Read(~/AppData/Roaming/**)" in rules and "Read(~/AppData/LocalLow/**)" in rules
    assert "Read(~/AppData/**)" not in rules and "Read(~/AppData/Local/**)" not in rules and warn
