"""Scanner fixes from the 2026-10-31 cross-review (H6, H7, H8). Each test failed before its fix.

H6  a private name in a file or folder name must not be printed (CI logs are public)
H7  a malformed deny-list entry must not crash the scan or print the entry; BOM, kana and Hangul entries load
H8  --history must also see renamed-away paths, author/committer names and emails, annotated tag messages,
    files over 5 MB, and UTF-16 files
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scan_private as S  # noqa: E402

J = "".join
LIST = "# test\nzorblax\nacme-corp\n"


@pytest.fixture
def terms():
    return S.Terms.from_lines(LIST.splitlines())


# ── H6 ──

def test_private_name_in_a_path_is_masked(tmp_path, terms):
    root = tmp_path / "repo"
    (root / "Zorblax_project").mkdir(parents=True)
    f = root / "Zorblax_project" / "notes.txt"
    f.write_text(J(["gs:", "//lab-results-7f3a/x\n"]), encoding="utf-8")
    hits = list(S.scan_files([f], root, terms, []))
    names = " ".join(h[0] for h in hits).lower()
    assert hits, "the bucket and the private folder name must still be reported"
    assert "zorblax" not in names
    assert "line 2" in names or "第 2 行" in names            # referred to by its line in the list


def test_main_output_has_no_private_name(tmp_path, monkeypatch, capsys):
    deny = tmp_path / "deny.txt"
    deny.write_text(LIST, encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(deny))
    root = tmp_path / "repo"
    (root / "acme-corp-data").mkdir(parents=True)
    (root / "acme-corp-data" / "a.txt").write_text("clean\n", encoding="utf-8")
    assert S.main(["--root", str(root), str(root)]) == 1
    out = capsys.readouterr()
    assert "acme" not in (out.out + out.err).lower()


# ── H7 ──

@pytest.mark.parametrize("bad", ["mixed宇宙鴨abc", "one two three four five", ""])
def test_bad_entry_reports_line_only(bad):
    if not bad:
        pytest.skip("blank lines are allowed")
    with pytest.raises(S.TermsError) as e:
        S.Terms.from_lines(["ok-term", bad])
    msg = str(e.value)
    assert "line 2" in msg and bad not in msg and "abc" not in msg and "five" not in msg


def test_bad_list_exits_2_without_echo(tmp_path, monkeypatch, capsys):
    deny = tmp_path / "deny.txt"
    deny.write_text("fine\nsecretname 宇宙鴨\n", encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(deny))
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    assert S.main(["--root", str(tmp_path), str(tmp_path / "a.txt")]) == 2
    out = capsys.readouterr()
    assert "secretname" not in out.out + out.err and "line 2" in out.out + out.err


def test_bom_kana_and_hangul_entries(tmp_path):
    deny = tmp_path / "deny.txt"
    deny.write_bytes("﻿宇宙鴨\nゾルブラ\n조르블락\n".encode("utf-8"))
    t = S.Terms.load(deny)
    assert list(t.find("專案宇宙鴨的資料"))                    # first line despite the BOM
    assert list(t.find("これはゾルブラです"))
    assert list(t.find("이것은 조르블락 입니다"))


# ── H8 ──

def git(cwd, *args, env=None):
    import os
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **(env or {})})


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "h"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "t")
    (r / "zorblax_dir").mkdir()
    (r / "zorblax_dir" / "x.txt").write_text("clean\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-qm", "first")
    git(r, "mv", "zorblax_dir", "clean_dir")
    git(r, "commit", "-qm", "rename")
    who = {"GIT_AUTHOR_NAME": "Zorblax Person", "GIT_AUTHOR_EMAIL": J(["z", "@", "corp-mail.com"]),
           "GIT_COMMITTER_NAME": "Acme Corp Bot", "GIT_COMMITTER_EMAIL": "bot@example.invalid"}
    (r / "big.txt").write_text("x" * (6 * 1024 * 1024) + "\nzorblax at the end\n", encoding="utf-8")
    (r / "wide.txt").write_bytes("hello from acme corp\n".encode("utf-16"))
    git(r, "add", ".")
    git(r, "commit", "-qm", "files", env=who)
    git(r, "tag", "-a", "v1", "-m", "release notes mention zorblax")
    return r


def labels(hits):
    return [h[0] for h in hits]


def test_history_sees_renamed_paths_authors_tags_big_and_utf16(repo, terms):
    hits = list(S.scan_history(repo, terms, []))
    text = " | ".join(f"{h[0]} {h[3]}" for h in hits).lower()
    assert any("path" in h[0] and h[3] == "private-term" for h in hits), text          # old path zorblax_dir
    assert any("author" in h[0] for h in hits), text                                   # name and email
    assert any("committer" in h[0] for h in hits), text
    assert any("tag" in h[0] for h in hits), text
    assert any(h[0].startswith("big.txt") for h in hits), text                          # > 5 MB
    assert any(h[0].startswith("wide.txt") for h in hits), text                         # UTF-16
    assert "zorblax" not in text and "acme" not in text                                # and nothing is echoed


def test_utf16_working_tree_file(tmp_path, terms):
    f = tmp_path / "w.txt"
    f.write_bytes("acme corp\n".encode("utf-16"))
    assert [h[3] for h in S.scan_files([f], tmp_path, terms, [])] == ["private-term"]
