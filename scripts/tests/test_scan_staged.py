"""--staged and the pre-commit hook (maintainer request after 3172481 was committed without a scan).

The staged blob is what the commit will contain, and it can differ from the working tree: a file cleaned in the
working tree after `git add` still commits the dirty version. The hook blocks on a staged hit and only warns
on a hit elsewhere in the working tree, which several sessions may share.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
import scan_private as S  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text("frobnitzlab\n", encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(deny))
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    return root


def test_staged_blob_is_scanned_even_if_the_working_tree_is_clean(repo):
    (repo / "a.md").write_text("the frobnitzlab lab\n", encoding="utf-8")
    _git(repo, "add", "a.md")
    (repo / "a.md").write_text("the lab\n", encoding="utf-8")          # cleaned after `git add`
    assert S.main(["--root", str(repo), str(repo / "a.md")]) == 0          # working tree: clean
    assert S.main(["--root", str(repo), "--staged"]) == 1                   # what would be committed: not


def test_staged_clean_passes_and_deleted_files_are_skipped(repo):
    (repo / "a.md").write_text("fine\n", encoding="utf-8")
    (repo / "b.md").write_text("fine\n", encoding="utf-8")
    _git(repo, "add", "a.md", "b.md")
    _git(repo, "commit", "-qm", "x")
    _git(repo, "rm", "-q", "b.md")
    assert S.main(["--root", str(repo), "--staged"]) == 0


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh (Git Bash on Windows)")
def test_hook_blocks_a_commit_with_a_private_name(repo):
    hooks = repo / ".githooks"
    hooks.mkdir()
    shutil.copy(REPO / "scripts" / "hooks" / "pre-commit", hooks / "pre-commit")
    (repo / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "scan_private.py", repo / "scripts" / "scan_private.py")
    _git(repo, "config", "core.hooksPath", ".githooks")
    _git(repo, "add", "scripts/scan_private.py")
    env = {**os.environ, "RAK_PYTHON": sys.executable}
    ok = subprocess.run(["git", "commit", "-qm", "clean"], cwd=repo, env=env, capture_output=True)
    assert ok.returncode == 0, ok.stderr
    (repo / "a.md").write_text("the frobnitzlab lab\n", encoding="utf-8")
    _git(repo, "add", "a.md")
    bad = subprocess.run(["git", "commit", "-qm", "dirty"], cwd=repo, env=env, capture_output=True)
    assert bad.returncode != 0
    assert "frobnitzlab" not in (bad.stdout + bad.stderr).decode("utf-8", "replace").lower()   # masked


# ── maintainer 2026-11-01: a shared working tree. Only what the commit contains blocks; the rest of the tree warns. ──

def _hooked(repo):
    hooks = repo / ".githooks"
    hooks.mkdir()
    shutil.copy(REPO / "scripts" / "hooks" / "pre-commit", hooks / "pre-commit")
    (repo / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "scan_private.py", repo / "scripts" / "scan_private.py")
    _git(repo, "config", "core.hooksPath", ".githooks")
    _git(repo, "add", "scripts/scan_private.py")
    _git(repo, "commit", "-qm", "base", "--no-verify")
    return {**os.environ, "RAK_PYTHON": sys.executable}


def _commit(repo, env, msg):
    r = subprocess.run(["git", "commit", "-qm", msg], cwd=repo, env=env, capture_output=True)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh (Git Bash on Windows)")
def test_hook_warns_but_does_not_block_on_other_peoples_files(repo):
    env = _hooked(repo)
    (repo / "tracked.md").write_text("fine\n", encoding="utf-8")
    _git(repo, "add", "tracked.md"); _git(repo, "commit", "-qm", "t", "--no-verify")
    (repo / "theirs-untracked.md").write_text("the frobnitzlab lab\n", encoding="utf-8")   # another session's
    (repo / "tracked.md").write_text("frobnitzlab again\n", encoding="utf-8")              # modified, not staged
    (repo / "mine.md").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "mine.md")
    code, out = _commit(repo, env, "mine")
    assert code == 0, out
    assert "2 finding(s)" in out and "not in this commit" in out
    assert "frobnitzlab" not in out.lower()


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh (Git Bash on Windows)")
def test_hook_still_blocks_my_staged_dirty_file_next_to_others(repo):
    env = _hooked(repo)
    (repo / "theirs-untracked.md").write_text("the frobnitzlab lab\n", encoding="utf-8")
    (repo / "mine.md").write_text("my frobnitzlab note\n", encoding="utf-8")
    _git(repo, "add", "mine.md")
    code, out = _commit(repo, env, "mine")
    assert code != 0 and "staged content has a finding" in out
