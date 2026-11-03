#!/usr/bin/env python3
"""Summarize a Claude Code session transcript (.jsonl) so a new session can pick up where it stopped.

    python session_digest.py <transcript.jsonl> [N]     # N = how many final assistant messages (default 6)

Prints the first and last user messages and the last N assistant text messages, each with its timestamp.
Use it when sessions die without a handoff (a reboot, a crash): it recovers what the session was asked
to do and what it last said, which is usually enough to write the missing progress entry.

Transcripts are under ~/.claude/projects/<project>/. They can contain anything the session saw;
read the digest before pasting it anywhere.
"""
from __future__ import annotations

import json
import sys


def texts(path: str):
    out = []  # (role, timestamp, text)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = o.get("message") or {}
            role = m.get("role") or o.get("type")
            ts = o.get("timestamp", "")
            c = m.get("content")
            if isinstance(c, str):
                out.append((role, ts, c))
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        out.append((role, ts, b["text"]))
    return out


def digest(path: str, ntail: int = 6) -> str:
    t = texts(path)
    # skip tool results and system reminders, which arrive as user turns starting with "<"
    users = [x for x in t if x[0] == "user" and not x[2].lstrip().startswith("<") and len(x[2]) < 3000]
    assistant = [x for x in t if x[0] == "assistant"]
    lines = ["== FIRST USER MESSAGES =="]
    lines += [f"{ts} {txt[:600]}" for _, ts, txt in users[:2]]
    lines.append("== LAST USER MESSAGES ==")
    lines += [f"{ts} {txt[:600]}" for _, ts, txt in users[-4:]]
    lines.append(f"== LAST {ntail} ASSISTANT MESSAGES ==")
    for _, ts, txt in assistant[-ntail:]:
        lines += [f"--- {ts}", txt[:2500]]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(digest(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 6))
