"""Audit collector for the sandbox (review of 6555c3c, M2): the agent can add lines to the MCP audit log, but cannot
read, change or delete what is already there.

It runs in its own container as uid 10002. It creates a FIFO the agent's group may only write (mode 0620), in a
volume the agent mounts read-only (Linux lets a process open a FIFO for writing on a read-only mount; it cannot
create, remove or replace one there). The MCP server's --audit-log points at the FIFO. Each line read is appended,
with the time it arrived, to a file on the host the agent container does not mount at all.

What it does not stop: the agent writing forged lines into the FIFO (they arrive like real ones; a forged line cannot
remove a real one), and lines longer than PIPE_BUF (4096 bytes) interleaving with a forged write at the same moment.

    python3 audit_collector.py /pipe/rak-mcp-audit /audit/rak-mcp-audit.jsonl
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time


def ensure_fifo(path: str) -> None:
    if os.path.lexists(path) and not stat.S_ISFIFO(os.lstat(path).st_mode):
        os.remove(path)                       # only this container can write the volume, so this is our own leftover
    if not os.path.exists(path):
        os.mkfifo(path)
    os.chmod(path, 0o620)                     # owner (collector) read-write, group (the agent) write only


def record(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").rstrip("\n")
    try:
        line = json.loads(text)
    except ValueError:
        line = {"unparseable": text[:2000]}
    return json.dumps({"received": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "line": line},
                      ensure_ascii=False)


def main(argv: list[str]) -> int:
    fifo, out = argv[0], argv[1]
    ensure_fifo(fifo)
    print(f"audit collector: {fifo} -> {out}", flush=True)
    fd = os.open(fifo, os.O_RDWR)             # read-write, so the FIFO never reaches EOF between writers
    buf = b""
    with open(out, "a", encoding="utf-8") as f:
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                time.sleep(0.05)
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if raw.strip():
                    f.write(record(raw) + "\n")
                    f.flush()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
