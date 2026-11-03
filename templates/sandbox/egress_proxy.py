"""Egress allowlist for the sandbox (L1). The agent container sits on an internal Docker network with no route out;
this proxy is its only way to the internet, and it only opens HTTPS tunnels to allowlisted hosts.

Standard library only, so it can be read in one sitting. For each CONNECT host:443 it:
1. checks the host against the allowlist (exact, or a subdomain of an entry that starts with ".");
2. resolves it itself, refuses private, loopback, link-local and other non-public addresses, and connects to the
   address it checked (no second lookup);
3. reads the client's first TLS ClientHello before forwarding anything, and requires its SNI to be the CONNECT
   host. No SNI, or an Encrypted Client Hello extension, is refused. Without this, a tunnel to an allowed host on a
   shared CDN can carry a TLS session to any other site on that CDN (domain fronting; review of 6555c3c: DNS over
   HTTPS through a tunnel to api.anthropic.com). The proxy does not decrypt anything; inside TLS, the HTTP Host
   header can still differ, which only the CDN can stop. Keep the allowlist short (README.md).

    RAK_EGRESS_ALLOW="api.anthropic.com arxiv.org export.arxiv.org" python3 egress_proxy.py [--port 3128]

Plain-HTTP requests and CONNECT to other ports get 403. One line per decision goes to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import re
import socket
import sys
import time

HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}$")
IDLE_S = 300
MAX_CONNECTIONS = 64
MAX_HELLO = 64 * 1024
EXT_SNI, EXT_ECH = 0x0000, 0xFE0D


def load_allow(text: str) -> tuple[set[str], tuple[str, ...]]:
    exact, suffixes = set(), []
    for item in text.replace(",", " ").split():
        item = item.strip().lower()
        if not item:
            continue
        if item.startswith("."):
            suffixes.append(item)
        else:
            exact.add(item)
    return exact, tuple(suffixes)


def normalize(host: str) -> str:
    return host.lower().rstrip(".")


def allowed(host: str, port: int, allow: tuple[set[str], tuple[str, ...]]) -> bool:
    host = normalize(host)
    if port != 443 or not HOST_RE.match(host) or ".." in host or host.startswith("."):
        return False
    exact, suffixes = allow
    return host in exact or any(host.endswith(s) for s in suffixes)


def parse_connect(line: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"CONNECT ([^\s:]+):(\d{1,5}) HTTP/1\.[01]", line.strip())
    return (m.group(1), int(m.group(2))) if m else None


def public_address(infos) -> str | None:
    """The first resolved address, if every resolved address is public. One private answer refuses the host."""
    addrs = [i[4][0] for i in infos]
    if not addrs:
        return None
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return None
    return addrs[0]


def client_hello_sni(data: bytes) -> tuple[str | None, bool, int]:
    """Parse TLS records holding a ClientHello. Returns (sni, has_ech, bytes_needed): bytes_needed > 0 means read
    more; sni None with bytes_needed 0 means it is not a ClientHello or has no SNI."""
    body, pos = b"", 0
    while True:
        if len(data) < pos + 5:
            return None, False, pos + 5 - len(data)
        ctype, length = data[pos], int.from_bytes(data[pos + 3:pos + 5], "big")
        if ctype != 0x16 or data[pos + 1] != 0x03 or length == 0 or length > 18432:
            return None, False, 0
        if len(data) < pos + 5 + length:
            return None, False, pos + 5 + length - len(data)
        body += data[pos + 5:pos + 5 + length]
        pos += 5 + length
        if len(body) >= 4:
            if body[0] != 0x01:
                return None, False, 0
            need = 4 + int.from_bytes(body[1:4], "big")
            if need > MAX_HELLO:
                return None, False, 0
            if len(body) >= need:
                break
    h, p = body[4:4 + int.from_bytes(body[1:4], "big")], 0
    try:
        p += 2 + 32                                         # client_version, random
        p += 1 + h[p]                                       # session_id
        p += 2 + int.from_bytes(h[p:p + 2], "big")          # cipher_suites
        p += 1 + h[p]                                       # compression_methods
        end = p + 2 + int.from_bytes(h[p:p + 2], "big")
        p += 2
        sni, ech, seen = None, False, set()
        while p + 4 <= end:
            et, el = int.from_bytes(h[p:p + 2], "big"), int.from_bytes(h[p + 2:p + 4], "big")
            ext = h[p + 4:p + 4 + el]
            if et in seen:                          # a repeated extension: TLS forbids it; do not guess which wins
                return None, False, 0
            seen.add(et)
            if et == EXT_ECH:
                ech = True
            elif et == EXT_SNI:
                # server_name_list with exactly one host_name entry; anything else is not ours to interpret
                if len(ext) < 5 or ext[2] != 0 or int.from_bytes(ext[0:2], "big") != 3 + int.from_bytes(ext[3:5], "big"):
                    return None, False, 0
                sni = ext[5:5 + int.from_bytes(ext[3:5], "big")].decode("ascii")
            p += 4 + el
        return sni, ech, 0
    except (IndexError, UnicodeDecodeError):
        return None, False, 0


def log(decision: str, peer, what: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {decision} {peer[0] if peer else '?'} {what}", flush=True)


async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await asyncio.wait_for(r.read(65536), IDLE_S)
            if not data:
                break
            w.write(data)
            await w.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def refuse(writer, code: bytes) -> None:
    writer.write(b"HTTP/1.1 " + code + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle(reader, writer, allow, slots: asyncio.Semaphore) -> None:
    peer = writer.get_extra_info("peername")
    if slots.locked():
        log("BUSY", peer, "too many connections")
        writer.close()
        return
    async with slots:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
        except Exception:
            writer.close()
            return
        first = head.split(b"\r\n", 1)[0].decode("latin-1")
        target = parse_connect(first)
        if not target or not allowed(*target, allow):
            log("DENY", peer, first[:200])
            await refuse(writer, b"403 Forbidden")
            return
        host, port = normalize(target[0]), target[1]
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            log("FAIL", peer, f"{host}:{port} resolve {type(e).__name__}")
            await refuse(writer, b"502 Bad Gateway")
            return
        addr = public_address(infos)
        if addr is None:
            log("DENY", peer, f"{host}:{port} resolves to a non-public address")
            await refuse(writer, b"403 Forbidden")
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        hello = b""
        try:
            while True:
                sni, ech, need = client_hello_sni(hello)
                if not need:
                    break
                chunk = await asyncio.wait_for(reader.read(max(need, 1)), 30)
                if not chunk or len(hello) + len(chunk) > MAX_HELLO:
                    break
                hello += chunk
        except asyncio.TimeoutError:
            sni, ech = None, False
        if ech or sni is None or normalize(sni) != host:
            log("DENY", peer, f"{host}:{port} TLS SNI {sni!r}{' with ECH' if ech else ''} does not match the tunnel")
            writer.close()
            return
        try:
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(addr, port), 30)
        except Exception as e:
            log("FAIL", peer, f"{host}:{port} ({addr}) {type(e).__name__}")
            writer.close()
            return
        log("ALLOW", peer, f"{host}:{port} ({addr})")
        up_w.write(hello)
        await up_w.drain()
        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))


async def main_async(port: int, allow) -> None:
    slots = asyncio.Semaphore(MAX_CONNECTIONS)
    server = await asyncio.start_server(lambda r, w: handle(r, w, allow, slots), "0.0.0.0", port)
    print(f"egress proxy on :{port}, allow exact={sorted(allow[0])} suffix={list(allow[1])}", flush=True)
    async with server:
        await server.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3128)
    a = ap.parse_args()
    allow = load_allow(os.environ.get("RAK_EGRESS_ALLOW", ""))
    if not allow[0] and not allow[1]:
        print("RAK_EGRESS_ALLOW is empty; refusing to start (an empty list must not mean 'allow nothing silently')",
              file=sys.stderr)
        return 2
    asyncio.run(main_async(a.port, allow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
