"""Reverse cross-review of the scanner fixes (2026-10-31). Each failed before its fix.

A3 a path is masked in every form the matcher recognizes (camelCase, a name split across two folders,
   percent-encoded, full-width), and when a private name is found in the path but no single folder can be
   pointed at, the whole path is replaced by a hash, so the original never reaches a public CI log.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scan_private as S  # noqa: E402


@pytest.fixture
def terms():
    return S.Terms.from_lines(["zorblax", "acme-corp"])


@pytest.mark.parametrize("path", [
    "MyZorblaxNotes/x.md",
    "AcmeCorpFiles/y.md",
    "docs/acme/corp/z.md",
    "zorbl%61x/a.md",
    "ｚｏｒｂｌａｘ/a.md",
    "a/zorblax2/b.md",
])
def test_private_names_in_paths_never_print(path, terms):
    shown = S.display_path(path, terms).lower()
    assert "zorbl" not in shown and "acme" not in shown and "%61" not in shown, shown
    assert "ｚｏｒ" not in shown, shown


def test_clean_paths_are_unchanged(terms):
    assert S.display_path("docs/notes/a.md", terms) == "docs/notes/a.md"


def test_other_hits_in_a_privately_named_file_do_not_leak_the_path(tmp_path, terms):
    (tmp_path / "MyZorblaxNotes").mkdir()
    f = tmp_path / "MyZorblaxNotes" / "a.md"
    email = "someone" + "@" + "corp-mail.org"
    f.write_text(f"contact {email}\n", encoding="utf-8")
    hits = list(S.scan_files([f], tmp_path, terms, []))
    assert hits and all("zorblax" not in h[0].lower() for h in hits), hits
