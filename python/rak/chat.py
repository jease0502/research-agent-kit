#!/usr/bin/env python3
"""Bridge questions from the web page to the local Claude Code CLI.

Architecture:

    web/chat.html ──POST /api/ask──> build.py --serve ──subprocess──> claude -p
                  <──── SSE ────────                  <──── stdout ──

**Why the CLI and not the API**: the CLI runs at the knowledge-base root, so it loads the base's own instructions
(CLAUDE.md) and can search papers/ and concepts/; its answers therefore cite their sources. Calling the API
directly would lose all of that and add a key to look after.

**Security properties** (read before changing this file):

- This **starts a local process from user input**. The server therefore **binds only to loopback**
  (127.0.0.1 and ::1) and checks Host, Origin and Content-Type, and `chat.html` **is not in dist/ by default**
  (only with `--chat` or `--serve`), so GitHub Pages and other deployments have no such page.
- The question goes to the CLI **on stdin, without a shell** (`shell=False`), never into argv.
- The CLI runs **with your own permissions**, limited by `--allowedTools` to read-only tools. A CLI too old for
  that flag gets an error, not a retry without the restriction.
"""

from __future__ import annotations

import json
import os
import pathlib
import queue
import shutil
import subprocess
import threading

from . import mdio
from . import schema
from .i18n import tr

# Read-only tools: it may look things up, not change them.
# Read-only tools only. No Bash at all: sed can write (-i) and run commands (e), rg can run a
# preprocessor (--pre); Read, Glob and Grep cover what the answers need.
READONLY_TOOLS = "Read,Glob,Grep"

SYSTEM_PROMPTS = {"zh-TW": """你正在回答一個從知識庫網頁介面來的問題。

請嚴格照 CLAUDE.md §6「工作流程 C：回答關鍵字查詢」的搜尋順序與固定回答格式作答：
### 直接回答 / ### 依據 / ### 相關概念 / ### 缺口

額外要求（因為這是網頁介面）：
- 引用 repo 內的節點時**一律用 `[[slug]]` 的形式**，網頁會把它變成可點的連結。
- 不要修改任何檔案，這是唯讀的查詢。
- 用了 repo 以外的知識，必須標「（repo 外知識，未經驗證）」。
- 簡潔。網頁上沒有人要讀十頁。
""", "en": """You are answering a question that came from the knowledge base's web page.

Follow the kb-query skill (or the knowledge base's own instructions, if it has a CLAUDE.md): its search
order and its fixed answer format:
### Direct answer / ### Sources / ### Related concepts / ### Gaps

Also, because this is a web page:
- Refer to nodes in the repository **always as `[[slug]]`**; the page turns them into links.
- Do not modify any file; this is a read-only query.
- Label anything from outside the repository: "(outside the knowledge base, unverified)".
- Be brief. Nobody reads ten pages on a web page.
"""}
ANSWER_MARKERS = {"zh-TW": "### 直接回答", "en": "### Direct answer"}


def system_prompt() -> str:
    from .i18n import get_locale
    return SYSTEM_PROMPTS[get_locale()]


def cli_command() -> list[str] | None:
    """Find the claude CLI. None if there is none.

    **On Windows, bypass npm's `.cmd` shim.** A global npm install creates a `claude.CMD` batch wrapper, and
    cmd.exe **cuts batch arguments at the first newline**: our system prompt has several lines, and through the
    shim only the first one arrives. npm's package.json actually points at `bin/claude.exe`; calling that
    directly keeps cmd.exe out of it, and the problem with it.
    """
    override = os.environ.get("RAK_CLAUDE_CMD")
    if override:
        return override.split()

    shim = shutil.which("claude") or shutil.which("claude.cmd")
    if shim:
        # work back from the shim to the real executable
        for cand in (
            pathlib.Path(shim).with_suffix(".exe"),
            pathlib.Path(shim).parent / "node_modules" / "@anthropic-ai"
            / "claude-code" / "bin" / "claude.exe",
        ):
            if cand.exists():
                return [str(cand)]
        return [shim]

    exe = shutil.which("claude.exe")
    return [exe] if exe else None


def status() -> dict:
    cmd = cli_command()
    return {
        "ok": cmd is not None,
        "cmd": cmd[0] if cmd else None,
        "hint": None if cmd else tr("chat.001"),
    }


def _spawn(question: str) -> subprocess.Popen:
    cmd = cli_command()
    # The question goes to stdin, never into argv: a question that starts with "-" would otherwise be
    # parsed as a CLI option. Instructions go through --append-system-prompt. The tool restriction is
    # always present; there is no code path that runs without it.
    args = cmd + [
        "-p",
        "--append-system-prompt", system_prompt(),
        "--output-format", "stream-json", "--verbose",
        "--allowedTools", READONLY_TOOLS,
    ]
    proc = subprocess.Popen(
        args,
        cwd=str(mdio.ROOT),          # run in the knowledge-base root, so its own instructions apply
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    proc.stdin.write(question)
    proc.stdin.close()
    return proc


def _text_from_event(ev: dict) -> str:
    """The text to show from one stream-json event.

    The CLI's event structure changes between versions, so this takes what it can and skips what it cannot,
    rather than breaking on a field it has not seen before.
    """
    if ev.get("type") == "assistant":
        content = (ev.get("message") or {}).get("content") or []
        return "".join(c.get("text", "") for c in content if c.get("type") == "text")
    if ev.get("type") == "result" and isinstance(ev.get("result"), str):
        return ""  # the final result is handled separately, so it is not printed twice
    return ""


def ask(question: str):
    """Run one query and yield SSE event dicts.

    Event types:
        {"type": "delta", "text": ...}   incremental output
        {"type": "tool",  "name": ...}   which tool it is using (progress for the user)
        {"type": "done",  "html": ...}   finished, with the rendered HTML
        {"type": "error", "message": ...}
    """
    if cli_command() is None:
        yield {"type": "error", "message": status()["hint"]}
        return

    proc = _spawn(question)
    q: queue.Queue = queue.Queue()

    def pump(stream, kind):
        for line in stream:
            q.put((kind, line))
        q.put((kind, None))

    threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()

    parts: list[str] = []
    errs: list[str] = []
    closed = 0
    while closed < 2:
        kind, line = q.get()
        if line is None:
            closed += 1
            continue
        if kind == "err":
            errs.append(line)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            # not JSON: plain text (an old CLI, or --output-format not supported)
            parts.append(line + "\n")
            yield {"type": "delta", "text": line + "\n"}
            continue

        if ev.get("type") == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    yield {"type": "tool", "name": c.get("name", "?")}
        text = _text_from_event(ev)
        if text:
            parts.append(text)
            yield {"type": "delta", "text": text}

    proc.wait()
    answer = "".join(parts).strip()

    if not answer:
        msg = "".join(errs).strip() or tr("chat.002", a0=proc.returncode)
        # No retry without --allowedTools: an old CLI that rejects the flag gets an error, not an
        # unrestricted run (user input could otherwise trigger the fallback).
        yield {"type": "error", "message": msg[:2000]}
        return

    yield {"type": "done", "html": render(trim_preamble(answer))}


def trim_preamble(answer: str) -> str:
    """Cut the narration before the actual answer.

    The CLI often starts with "first I'll grep the concept cards, then read that section...". That is useful
    progress while streaming, but noise in the final answer. Answers start with the direct-answer heading
    (ANSWER_MARKERS), so cut there. If it is not found, keep everything: better to show too much than to cut
    content.
    """
    from .i18n import get_locale
    marker = ANSWER_MARKERS[get_locale()]
    idx = answer.find(marker)
    return answer[idx:] if idx > 0 else answer


def render(md_text: str) -> str:
    """Render the answer to HTML, with [[slug]] as clickable links.

    Reuses build.py's WikiLink handling on purpose, so links in answers behave like links on the site.
    """
    from . import build  # lazy: the markdown package is only needed when an answer is rendered

    rep = build.check.Report()
    items = build.check.load_all(rep)
    amap = build.check.build_alias_map(items, rep)

    def resolve(target):
        hit = build.check.resolve(target, items, amap)
        if hit is None:
            return None
        return {"slug": hit, "kind": items[hit]["kind"],
                "title": items[hit]["meta"].get("title", hit)}

    ctx = {"resolve": resolve, "sink": [], "broken": []}
    return build.make_renderer(ctx)(md_text)
