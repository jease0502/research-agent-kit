"""Security fixes from the 2026-10-31 cross-review (docs/review-2026-10-31.md). Each test failed before its fix.

H1  the local server must refuse requests whose Host / Origin is not this loopback server, and /api/ask
    must require a JSON body (CSRF from any web page; DNS rebinding reading the site or the answers)
M1  the question must not reach the CLI's argument list, and a failed run must not be retried without
    the tool restriction
M2  the "read-only" tool list must not contain tools that can write or run commands
H4  raw HTML in notes must not reach the page (stored XSS through innerHTML), except a small allowlist
H5  `rak build --out` must not delete a folder it did not create
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from rak import build as B
from rak import chat


# ── H1 ──────────────────────────────────────────────────────────────────────

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<p>private notes</p>", encoding="utf-8")
    calls = []

    def fake_ask(q, restrict=True):
        calls.append(q)
        yield {"type": "done", "html": "<p>ok</p>"}

    monkeypatch.setattr(chat, "ask", fake_ask)
    monkeypatch.setattr(chat, "status", lambda: {"ok": True, "cmd": "fake", "hint": None})
    port = free_port()
    threading.Thread(target=B.serve, args=(tmp_path, port), daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    return port, calls


def request(port, method, path, headers, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True)
    for k, v in headers.items():
        c.putheader(k, v)
    data = body.encode() if body is not None else None
    if data is not None:
        c.putheader("Content-Length", str(len(data)))
    c.endheaders(data)
    r = c.getresponse()
    out = r.status, r.read()
    c.close()
    return out


def ok_headers(port, **extra):
    return {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **extra}


def test_ask_works_from_the_page_itself(server):
    port, calls = server
    st, body = request(port, "POST", "/api/ask", ok_headers(port, Origin=f"http://127.0.0.1:{port}"), '{"q": "hi"}')
    assert st == 200 and b'"done"' in body and calls == ["hi"]
    st, _ = request(port, "POST", "/api/ask", {"Host": f"localhost:{port}", "Content-Type": "application/json"},
                    '{"q": "hi"}')
    assert st == 200


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example:{port}", "Content-Type": "application/json"},                       # DNS rebinding
    {"Host": "127.0.0.1:{port}", "Content-Type": "application/json", "Origin": "http://evil.example"},  # CSRF
    {"Host": "127.0.0.1:{port}", "Content-Type": "text/plain"},                                    # simple request
    {"Host": "127.0.0.1:{port}", "Content-Type": "application/json", "Origin": "http://127.0.0.1:1"},  # other port
    {"Content-Type": "application/json"},                                                          # no Host
])
def test_ask_refuses_foreign_requests(server, headers):
    port, calls = server
    h = {k: v.format(port=port) for k, v in headers.items()}
    st, _ = request(port, "POST", "/api/ask", h, '{"q": "hi"}')
    assert st in (400, 403, 415) and calls == []


def test_static_files_refuse_a_foreign_host(server):
    port, _ = server
    st, body = request(port, "GET", "/index.html", {"Host": f"attacker.example:{port}"})
    assert st == 403 and b"private notes" not in body
    st, body = request(port, "GET", "/index.html", {"Host": f"127.0.0.1:{port}"})
    assert st == 200 and b"private notes" in body


# ── M1 / M2 ─────────────────────────────────────────────────────────────────

FAKE_CLI = """
import json, sys, pathlib, os
log = pathlib.Path(os.environ["FAKE_CLI_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
calls.append({"argv": sys.argv[1:], "stdin": sys.stdin.read()})
log.write_text(json.dumps(calls))
if os.environ.get("FAKE_CLI_FAIL"):
    sys.stderr.write("error: unknown option '--bogus-flag'\\n")
    sys.exit(1)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "### Direct answer\\nok"}]}}))
"""


@pytest.fixture
def fake_cli(tmp_path, monkeypatch, kb):
    script = tmp_path / "fake_cli.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    log = tmp_path / "calls.json"
    monkeypatch.setenv("RAK_CLAUDE_CMD", f"{Path(sys.executable).as_posix()} {script.as_posix()}")
    monkeypatch.setenv("FAKE_CLI_LOG", str(log))
    return lambda: json.loads(log.read_text())


def test_question_never_reaches_argv(fake_cli):
    events = list(chat.ask("--bogus-flag what is PPO"))
    [call] = fake_cli()
    assert not any("--bogus-flag" in a for a in call["argv"])
    assert "--bogus-flag what is PPO" in call["stdin"]
    assert "--allowedTools" in call["argv"]
    assert events[-1]["type"] == "done"


def test_no_retry_without_the_tool_restriction(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_FAIL", "1")
    events = list(chat.ask("anything"))
    calls = fake_cli()
    assert len(calls) == 1 and "--allowedTools" in calls[0]["argv"]
    assert events[-1]["type"] == "error"


def test_readonly_tools_cannot_write_or_execute():
    tools = chat.READONLY_TOOLS.split(",")
    assert not [t for t in tools if t.startswith("Bash(")], tools   # sed -i / sed e, rg --pre, ...
    assert set(tools) <= {"Read", "Glob", "Grep"}


# ── H4 ──────────────────────────────────────────────────────────────────────

def render(src):
    ctx = {"resolve": lambda t: None, "sink": [], "broken": [], "media": False, "videos": []}
    return B.make_renderer(ctx)(src)


@pytest.mark.parametrize("src,bad", [
    ('hi <img src=x onerror="alert(1)">', "<img"),
    ("<script>alert(2)</script>", "<script"),
    ('see <a href="javascript:alert(3)">here</a>', "<a "),
    ("[here](javascript:alert(5))", 'href="javascript'),                      # markdown link syntax
    ("![x](javascript:alert(6))", 'src="javascript'),
    ("[here](JaVaScRiPt:alert(7))", 'href="JaVaScRiPt'),
    ("[here](data:text/html,<script>alert(8)</script>)", 'href="data:'),
    ('<div onclick="x()">block</div>', "<div"),
    ('<iframe src="https://evil.example"></iframe>', "<iframe"),
    ("<svg onload=alert(4)>", "<svg"),
])
def test_raw_html_is_escaped(src, bad):
    out = render(src)
    assert bad not in out, out


def test_allowlisted_formatting_tags_survive():
    out = render("H<sub>2</sub>O and E=mc<sup>2</sup><br>next")
    assert "<sub>2</sub>" in out and "<sup>2</sup>" in out and "<br" in out


def test_allowlisted_tags_lose_their_attributes():
    out = render('<sub onclick="x()">2</sub>')
    assert "onclick" not in out or "&lt;sub onclick" in out


def test_ordinary_links_keep_their_href():
    out = render("[a](https://example.org/x) [b](other.html#s) [c](mailto:x@example.org) [d](#top)")
    for h in ('href="https://example.org/x"', 'href="other.html#s"', 'href="mailto:x@example.org"', 'href="#top"'):
        assert h in out, out


def test_code_blocks_and_videos_still_render():
    out = render("```\n<script>x</script>\n```\n\n`<b>`")
    assert "&lt;script&gt;" in out and "<pre>" in out and "&lt;b&gt;" in out


# ── H5 ──────────────────────────────────────────────────────────────────────

NOTE = """---
title: "A"
authors:
  - A
year: 2024
url: https://example.com
tags: [example]
status: queued
summary: s
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


def run_build(kb, out):
    import contextlib
    import io
    import sys as _sys
    argv = _sys.argv
    _sys.argv = ["rak build", "--no-fulltext", "--out", str(out), "--commit", "abc1234"]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                return B.main()
            except SystemExit as e:
                return e.code
    finally:
        _sys.argv = argv


@pytest.mark.parametrize("target", ["papers", ".", "..", "docs"])
def test_build_out_refuses_to_delete_folders_it_did_not_create(kb, target):
    (kb / "papers" / "a.md").write_text(NOTE, encoding="utf-8")
    before = sorted(p.relative_to(kb.parent).as_posix() for p in kb.parent.rglob("*"))
    rc = run_build(kb, target)
    assert rc not in (0, None)
    assert (kb / "papers" / "a.md").exists() and (kb / "rak.toml").exists()
    assert all((kb.parent / p).exists() for p in before)


def test_build_out_refuses_an_unmarked_existing_folder(kb):
    (kb / "papers" / "a.md").write_text(NOTE, encoding="utf-8")
    other = kb / "site"
    other.mkdir()
    (other / "keep.txt").write_text("mine", encoding="utf-8")
    assert run_build(kb, "site") not in (0, None)
    assert (other / "keep.txt").exists()


def test_build_out_rebuilds_its_own_folder(kb):
    (kb / "papers" / "a.md").write_text(NOTE, encoding="utf-8")
    assert run_build(kb, "dist") == 0
    (kb / "dist" / "stale.txt").write_text("old", encoding="utf-8")
    assert run_build(kb, "dist") == 0                       # marked as ours: replaced
    assert not (kb / "dist" / "stale.txt").exists() and (kb / "dist" / "index.html").exists()
