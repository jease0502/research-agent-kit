"""Medium / low findings of the 2026-10-31 cross-review in python/rak (M6-M13, L4, lows). Each failed before its fix."""
from __future__ import annotations

import contextlib
import io
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rak import add_paper as A
from rak import build as B
from rak import config, mdio, schema
from rak.cli import main as cli


NOTE = """---
title: "A"
authors:
  - A. Author
year: 2024
url: {url}
tags: [example]
status: queued
summary: s
added: "2026-01-01"
updated: "2026-01-01"
{extra}---

## TL;DR

> TODO
"""


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return fn(*a, **k)
        except SystemExit as e:
            return e.code


# ── M6: build refuses content that rak check rejects ──

def test_build_refuses_schema_errors(kb):
    (kb / "papers" / "a.md").write_text(NOTE.format(url="https://example.com", extra="arxiv: 2307.15810\n"),
                                        encoding="utf-8")
    rc = quiet(B.build, kb / "dist", "abc1234", with_fulltext=False)
    assert rc not in (0, None)
    assert not (kb / "dist" / "data" / "items" / "a.json").exists()


def test_build_does_not_crash_on_mixed_year_types(kb):
    (kb / "papers" / "a.md").write_text(NOTE.format(url="https://example.com", extra=""), encoding="utf-8")
    (kb / "papers" / "b.md").write_text(NOTE.format(url="https://example.com", extra="").replace("year: 2024", 'year: "2024"'),
                                        encoding="utf-8")
    rc = quiet(B.build, kb / "dist", "abc1234", with_fulltext=False)
    assert rc == 1                                  # refused with a message, no TypeError


# ── M7 ──

@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "vbscript:x"])
def test_non_http_url_is_an_error(url):
    meta = {"title": "T", "authors": ["A"], "year": 2024, "url": url, "tags": ["example"], "status": "queued",
            "summary": "s", "added": "2026-01-01", "updated": "2026-01-01"}
    errs, _, _ = schema.validate("paper", meta)
    assert any("url" in e for e in errs), errs


# ── M8 ──

def test_refresh_keeps_a_hand_set_venue_over_the_fallback():
    meta = A.build_meta({"title": "T", "venue": "arXiv preprint"}, {"title": "T", "venue": "ICLR 2018"})
    assert meta["venue"] == "ICLR 2018"
    meta = A.build_meta({"title": "T", "venue": "NeurIPS 2019"}, {"title": "T", "venue": "ICLR 2018"})
    assert meta["venue"] == "NeurIPS 2019"         # a real venue from the API still updates it


# ── M9 ──

def roundtrip(meta):
    text = mdio.compose(meta, "## TL;DR\n\nx\n", "paper")
    got, _, err = mdio.parse(text)
    assert err is None, err
    return got


def test_yaml_keywords_and_numbers_in_lists_stay_strings():
    got = roundtrip({"title": "T", "tags": ["null", "true", "on", "1.5", "2024", "yes", "~"]})
    assert got["tags"] == ["null", "true", "on", "1.5", "2024", "yes", "~"]


def test_nested_values_round_trip():
    got = roundtrip({"title": "T", "ratings": {"alice": 4, "bob": 5}})
    assert got["ratings"] == {"alice": 4, "bob": 5}


def test_control_characters_are_stripped():
    got = roundtrip({"title": "Bad\x07title\x1b here"})
    assert got["title"] == "Badtitle here"


# ── M10 ──

def test_old_style_ids_keep_their_archive():
    xml = ('<entry xmlns="http://www.w3.org/2005/Atom"><id>http://arxiv.org/abs/hep-th/9901001v1</id>'
           '<title>Old paper</title><published>1999-01-01T00:00:00Z</published>'
           '<author><name>A. Author</name></author><summary>s</summary></entry>')
    info = A.parse_entry(ET.fromstring(xml))
    assert info["arxiv"] == "hep-th/9901001" and info["url"].endswith("/abs/hep-th/9901001")


# ── M11 ──

def test_duplicates_are_found_by_doi_too():
    existing = {"old": {"meta": {"doi": "10.1038/Nature14236"}}}
    assert A.find_duplicate(existing, {"doi": "10.1038/nature14236"}) == "old"
    assert A.find_duplicate(existing, {"doi": "https://doi.org/10.1038/NATURE14236"}) == "old"
    assert A.find_duplicate(existing, {"arxiv": "1707.06347"}) is None


# ── M13 ──

def test_batch_dedupes_versions_and_validates_slugs_first(kb, tmp_path, monkeypatch):
    calls = []

    def fake_many(ids, chunk=10):
        calls.append(list(ids))
        return {i: {"title": f"Paper {i}", "authors": ["A"], "year": 2017, "arxiv": i, "url": "https://x",
                    "abstract": "a"} for i in ids}

    monkeypatch.setattr(A, "fetch_arxiv_many", fake_many)
    f = tmp_path / "ids.txt"
    f.write_text("1707.06347\n1707.06347v2\n", encoding="utf-8")
    quiet(A.run_batch, str(f), False)
    assert calls == [["1707.06347"]] and len(list((kb / "papers").glob("*.md"))) == 1

    g = tmp_path / "bad.txt"
    g.write_text("2307.15818 good-slug\n2307.15819 Bad_Slug\n", encoding="utf-8")
    calls.clear()
    rc = quiet(A.run_batch, str(g), False)
    assert rc not in (0, None) and calls == []          # refused before any request or write
    assert len(list((kb / "papers").glob("*.md"))) == 1


# ── lows ──

def test_extract_arxiv_id_does_not_truncate_longer_numbers():
    assert A.extract_arxiv_id("2307.158189") is None
    assert A.extract_arxiv_id("2307.15818") == "2307.15818"
    assert A.extract_arxiv_id("see arXiv:2307.15818v2.") == "2307.15818v2"


def test_backlink_snippet_works_for_alias_links():
    text = "We compare against [[PPO]] in all runs."
    s = B.snippet(text, "Proximal Policy Optimization", "proximal-policy-optimization",
                  resolve=lambda x: "proximal-policy-optimization" if x.lower() == "ppo" else None)
    assert "<mark>PPO</mark>" in s


def test_refresh_dry_run_does_not_claim_an_update():
    assert "would" in A.refresh_message("x", ["venue"], dry_run=True).lower()
    assert "would" not in A.refresh_message("x", ["venue"], dry_run=False).lower()


# ── M12 ──

def render(src):
    ctx = {"resolve": lambda t: None, "sink": [], "broken": [], "media": False, "videos": []}
    return B.make_renderer(ctx)(src)


def test_dollar_amounts_are_not_math():
    out = render("It costs US$100 and US$50 per run.")
    assert "US$100 and US$50" in out and 'class="math' not in out


def test_math_inside_code_spans_is_left_alone():
    out = render("Write `$x$` for inline math, and $y$ renders.")
    assert "<code>$x$</code>" in out and out.count('class="math') == 1


# ── L4 ──

def test_explicit_missing_root_is_an_error(tmp_path, capsys):
    assert cli(["--root", str(tmp_path / "no-such-kb"), "check"]) == 2


def test_init_honours_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli(["--root", str(tmp_path / "kbroot"), "init"]) == 0
    assert (tmp_path / "kbroot" / "rak.toml").exists() and not (tmp_path / "rak.toml").exists()


@pytest.mark.parametrize("src,n", [
    (r"ratio $3.52 \times 6.86$ here", 1), (r"up to $18\%$ faster", 1), ("down to $1/k$ calls", 1),
    ("為$x$的值", 1), ("$100 and $50 per run", 0), ("costs US$100 and US$50", 0), ("$ x $ is not math", 0),
    ("a 16$X$ speedup", 1), ("CA$^3$C and P$^{3}$-WAM", 2), ("SmolVLA and $Y$0.5", 1),
    ("NT$100／VM 小時約 NT$496", 0), ("from $2.62-$82.30", 0), ("$256 = $ num", 1),
])
def test_math_detection_follows_pandoc(src, n):
    assert render(src).count('class="math') == n, render(src)
