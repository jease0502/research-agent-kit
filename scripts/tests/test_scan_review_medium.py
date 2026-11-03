"""Scanner medium / low findings of the 2026-10-31 cross-review (M14, M15, lows). Each failed before its fix.

M14 private-name variants: glued to other words (camelCase, letters+digits), percent-encoded, split across
    a line break, full-width. Simplified vs traditional CJK is NOT converted automatically (the standard
    library has no reliable table): the list must carry both forms, and both must be found.
M15 the e-mail allow-list must match whole domains (myexample.com is not example.com)
low the home-path rule must catch upper-case names and paths without a trailing slash; image names like
    icon@2x.png and ssh://git@host URLs are not e-mail addresses
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scan_private as S  # noqa: E402

J = "".join


@pytest.fixture
def terms():
    return S.Terms.from_lines(["zorblax", "acme-corp", "宇宙鴨", "宇宙鸭"])


def kinds(text, terms):
    return [h[3] for h in S.scan_text("t", text, terms)]


@pytest.mark.parametrize("text", [
    "the ZorblaxBot runs nightly",          # camelCase glued
    "see acmeCorpLab results",              # camelCase across a multi-word name
    "zorblax2 and Zorblax_v3",              # letters + digits, underscore
    "url /p/zorbl%61x/index",               # percent-encoded
    "ｚｏｒｂｌａｘ in full width",           # full-width Latin
    "專案宇宙鸭與宇宙鴨",                     # both CJK forms listed, both found
])
def test_variants_are_found(text, terms):
    assert "private-term" in kinds(text, terms), text


def test_name_split_across_a_line_break(terms):
    hits = list(S.scan_text("t", "we thank the acme\ncorp team\n", terms))
    assert [h[3] for h in hits] == ["private-term"] and hits[0][1] == 1


def test_hyphenated_line_wrap(terms):
    assert "private-term" in kinds("the zor-\nblax pipeline", terms)


@pytest.mark.parametrize("text", ["zorblaxian", "pre-zorbla", "acme", "宇宙"])
def test_still_no_partial_matches(text, terms):
    assert "private-term" not in kinds(text, terms)


@pytest.mark.parametrize("addr,flagged", [
    (J(["a", "@", "myexample.com"]), True),
    (J(["a", "@", "acmeanthropic.com"]), True),
    (J(["a", "@", "example.com"]), False),
    (J(["a", "@", "mail.example.com"]), False),
    (J(["noreply", "@", "anthropic.com"]), False),
])
def test_email_allow_list_matches_whole_domains(addr, flagged):
    assert ("email" in kinds(addr, S.Terms.empty())) is flagged


@pytest.mark.parametrize("text,flagged", [
    (J(["/ho", "me/Alice/.ssh"]), True),
    (J(["cd /ho", "me/alice"]), True),
    (J(["/ho", "me/user/x"]), False),
])
def test_home_path(text, flagged):
    assert ("home-path" in kinds(text, S.Terms.empty())) is flagged


@pytest.mark.parametrize("text", ["![logo](icon@2x.png)", "photo@3x.jpg", J(["ssh://", "git", "@", "gitlab.example.org/x.git"])])
def test_not_emails(text):
    assert "email" not in kinds(text, S.Terms.empty())
