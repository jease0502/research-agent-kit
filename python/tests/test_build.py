"""建置：尺寸守衛、網站名稱與原始碼連結的代換、影片語法、不在 git 裡也能 build。

尺寸守衛移植自原本知識庫：index.json 曾超過 800 KB，拆出 list.json 後兩個都要有「真的會回 1」的證明，
不然哪天被改成只印警告也沒人發現。
"""
from __future__ import annotations

import contextlib
import io
import re

from rak import build as B
from rak import schema


def run_check(i: int, l: int) -> tuple[int, str]:
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = B.check_budgets(i, l)
    return rc, err.getvalue()


def test_budget_values_not_loosened():
    assert (schema.INDEX_BUDGET_BYTES, schema.LIST_BUDGET_BYTES) == (800 * 1024, 1024 * 1024)


def test_budget_guard():
    IB, LB = schema.INDEX_BUDGET_BYTES, schema.LIST_BUDGET_BYTES
    assert run_check(IB, LB) == (0, "")
    rc, e = run_check(IB + 1, LB)
    assert rc == 1 and "index.json" in e
    rc, e = run_check(IB, LB + 1)
    assert rc == 1 and "list.json" in e and "index.json" not in e
    assert "authors_short" in e and "Do not raise" in e   # 錯誤訊息寫了下一步（預設英文）
    rc, e = run_check(IB + 1, LB + 1)
    assert rc == 1 and "index.json" in e and "list.json" in e


PAPER = """---
title: "A Demo Paper"
authors:
  - A. Author
year: 2024
url: https://example.com/demo
tags: [example]
status: queued
summary: 示範
added: "2026-01-01"
updated: "2026-01-01"
---

## TL;DR

> TODO

## Problem and motivation

> TODO

## Method

> TODO

## Experiments and results

> TODO

## Critique

> TODO

## Key concepts

> TODO

## Further reading

> TODO

## Abstract

> TODO
"""


def _quiet_build(out, **kw):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = B.build(out, kw.pop("commit", "abc1234"), with_fulltext=False, **kw)
    return rc, err.getvalue()


def test_full_build_and_list_budget(kb, monkeypatch):
    (kb / "papers" / "demo-paper.md").write_text(PAPER, encoding="utf-8")
    rc, _ = _quiet_build(kb / "dist")
    assert rc == 0
    assert (kb / "INDEX.md").is_file()
    monkeypatch.setattr(schema, "LIST_BUDGET_BYTES", 16)
    rc, err = _quiet_build(kb / "dist2")
    assert rc == 1 and "✗ list.json" in err


def test_site_name_and_source_url(kb):
    (kb / "papers" / "demo-paper.md").write_text(PAPER, encoding="utf-8")
    _quiet_build(kb / "d1")
    core = (kb / "d1" / "assets" / "core.js").read_text(encoding="utf-8")
    assert "__SITE_NAME__" not in core and "__SOURCE_URL__" not in core
    assert "'' ? '<a href=\"\">Source</a>' : ''" in core          # 沒給 source_url → 不畫連結（預設英文）
    assert "<title>research kb" in (kb / "d1" / "index.html").read_text(encoding="utf-8")

    from rak import config
    (kb / "rak.toml").write_text('site_name = "Lab KB"\nsource_url = "https://example.org/kb"\n', encoding="utf-8")
    config.use(config.load(kb))
    _quiet_build(kb / "d2")
    assert "<title>Lab KB" in (kb / "d2" / "index.html").read_text(encoding="utf-8")
    assert 'href="https://example.org/kb"' in (kb / "d2" / "assets" / "core.js").read_text(encoding="utf-8")


def test_no_hardcoded_owner_in_shipped_assets():
    """套件內附的網頁與模板不能帶任何人的 repo 或帳號。"""
    from rak.config import PACKAGE_DIR
    for f in (PACKAGE_DIR / "web").rglob("*"):
        if f.suffix in (".html", ".js", ".css"):
            t = f.read_text(encoding="utf-8")
            assert "github.com/" not in t, f


def test_build_outside_git_does_not_trip_build_id_guard(kb):
    """不在 git 裡時的 build id 曾是 "dev"，會撞到 web 檔裡的 device 之類的字而讓 build 中止。"""
    (kb / "papers" / "demo-paper.md").write_text(PAPER, encoding="utf-8")
    sha = B.git_sha()
    assert sha != "dev" and re.fullmatch(r"[0-9a-z]+", sha)
    rc, _ = _quiet_build(kb / "dist", commit=sha)
    assert rc == 0


def render(src: str, media: bool):
    ctx = {"resolve": lambda t: None, "sink": [], "broken": [], "media": media, "videos": []}
    return B.make_renderer(ctx)(src), ctx


VID = "handson/01-demo/videos/demo.mp4"


def test_video_internal_site():
    html, ctx = render(f'![video]({VID} "示範影片")', media=True)
    assert "<video" in html and f'src="/media/{VID}"' in html
    assert "controls" in html and 'preload="none"' in html
    assert "示範影片" in html and ctx["videos"] == [VID]
    assert "<figure" not in html


def test_video_pages_site():
    html, _ = render(f'![video]({VID} "示範影片")', media=False)
    assert "<video" not in html and "only available on the internal site" in html and "示範影片" in html


def test_video_in_code_span_untouched():
    html, _ = render(f"示範：`![video]({VID})` 這樣寫。", media=True)
    assert "<video" not in html and "<code>" in html


def test_video_bad_paths():
    for bad in ("handson/../etc/passwd.mp4", "handson/15/videos/x.exe", "/etc/passwd.mp4",
                "https://evil.example/x.mp4", "handson/15/logs/x.mp4"):
        out, c = render(f"![video]({bad})", media=True)
        assert "<video" not in out and c["videos"] == [], bad


# Markdown 3.10 把 `A*` 當成斜體的開頭，會一路吃到下一個 `*`（原本知識庫的 11 頁因此跑版）；
# 3.11 保留字面。pyproject 釘在 3.11.x，這幾個案例固定那個行為。
STAR_CASES = [
    ("OWL-ViT + A* 導航），**10 個真實家庭**", ["A* 導航", "<strong>10 個真實家庭</strong>"]),
    ("| 7 / 3 / 2 / 8* / 2* |", ["8* / 2*"]),
    ("規劃 A*，路徑簡化；**每 4 s 重規劃**", ["A*，", "<strong>每 4 s 重規劃</strong>"]),
]


def test_markdown_version_is_pinned():
    import markdown
    assert markdown.__version__.startswith("3.11."), markdown.__version__


def test_literal_star_is_not_emphasis():
    for src, wants in STAR_CASES:
        html, _ = render(src, media=False)
        assert "<em>" not in html, (src, html)
        for w in wants:
            assert w in html, (src, w, html)
