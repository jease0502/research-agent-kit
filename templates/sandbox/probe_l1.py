"""Checks that only L1 can make, run inside the agent container (verify.py starts it; no model involved).

Each check tries the thing an agent must not be able to do, the way an allowed command could (the MCP server allows
`python3 -c ...`, docs/mcp-server.md §3 point 1), and passes only if the operating system refuses it. One JSON
object per check on stdout.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"check": name, "pass": bool(ok), "detail": str(detail)[:300]})


def refused(fn):
    try:
        fn()
    except OSError as e:
        return True, f"{type(e).__name__}: {e}"
    return False, "succeeded"


# 1. the host's home and drives are not there
import glob  # noqa: E402

host_view = sorted(set(glob.glob("/mnt/*") + glob.glob("/c/*") + glob.glob("/host*") + glob.glob("/Users/*")
                       + glob.glob("/run/desktop/mnt/*") + glob.glob("/root/*")))
check("no host drives or home", not host_view, host_view or "none present")
home = os.path.expanduser("~")
check("home starts without host files", not os.path.exists(os.path.join(home, ".claude", ".credentials.json"))
      and not os.path.exists(os.path.join(home, ".ssh")) and not os.path.exists(os.path.join(home, ".gitconfig")),
      sorted(os.listdir(home)))
MOUNTINFO = [line.split() for line in open("/proc/self/mountinfo")]
# Every mount the container has, minus the kernel and runtime ones every container gets (review of 6555c3c, M5b:
# a prefix list would miss e.g. /var/run/docker.sock).
SYSTEM = ("/", "/proc", "/sys", "/dev", "/etc/hosts", "/etc/hostname", "/etc/resolv.conf", "/tmp")
mounts = sorted({f[4] for f in MOUNTINFO if f[4] not in SYSTEM and not f[4].startswith(("/proc/", "/sys/", "/dev/"))})
WORK_RO = {"/work/" + d for d in (".git", ".claude", ".claude-plugin", ".github", ".husky", ".githooks", ".circleci",
                                  ".gemini", ".codex", ".rak", ".vscode", ".idea", ".devcontainer", "scripts/hooks")}
expected = {"/work", "/opt/rak", "/opt/rak-config", "/pipe", "/home/runner"}
extra = [m for m in mounts if m not in expected and m not in WORK_RO and not m.startswith("/work/")]
check("only the expected mounts", not extra, extra or mounts)
check("no Docker socket", not any(os.path.exists(p) for p in ("/var/run/docker.sock", "/run/docker.sock")),
      "absent")
home_fs = next((f[f.index("-") + 1] for f in MOUNTINFO if f[4] == home), "?")
check("home is a fresh tmpfs (nothing survives a run)", home_fs == "tmpfs", home_fs)

# 1b. what the host would run later. The spellings are the ones that reached the host's .git through NTFS in the
# review of 1a90306: other case, an 8.3 short name, a trailing dot.
MODE = os.environ.get("RAK_MODE", "")
PLANTS = ("/work/.git/hooks/pre-commit", "/work/.GIT/hooks/pre-commit", "/work/GIT~1/hooks/post-checkout",
          "/work/.git./hooks/pre-push", "/work/.Claude/settings.json", "/work/.vscode/tasks.json", "/work/.ENVRC")


def plant(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("#!/bin/sh\necho planted by probe_l1\n")


check("mode is set by run.sh", MODE in ("copy", "mount"), MODE or "unset")
if MODE == "copy":
    # The project is a copy in a volume: the writes succeed here, and must make the whole patch be refused
    # (verify.py checks that, and that the host project is unchanged).
    check("copy mode: no .git in the copy", not os.path.exists("/work/.git"), os.listdir("/work"))
    for path in PLANTS:
        ok, why = refused(lambda p=path: plant(p))
        check(f"copy mode: planted in the copy only: {path}", not ok, why)
else:
    for path in ("/work/.git/config", "/work/.git/hooks/pre-commit", "/work/.claude/settings.json",
                 "/work/.vscode/tasks.json", "/work/.github/workflows/x.yml", "/work/.husky/pre-commit"):
        ok, why = refused(lambda p=path: open(p, "a").close())
        check(f"read-only overlay: {path}", ok, why)

# 2. the policy, plugins, MCP server and config cannot be written
for path in ("/opt/rak/python/rak/policy/rules.json", "/opt/rak/python/rak/mcp_server.py",
             "/opt/rak/plugins/rak-discipline/hooks/guard.py", "/opt/rak-config/settings.json"):
    ok, why = refused(lambda p=path: open(p, "a").close())
    check(f"read-only: {path}", ok, why)
ok, why = refused(lambda: open("/opt/rak/new_file", "w").close())
check("read-only: new file in the kit", ok, why)
ok, why = refused(lambda: open("/usr/local/bin/claude-shim", "w").close())
check("read-only: image filesystem", ok, why)
ok, why = refused(lambda: open("/work/.l1_probe_write_ok", "w").close())
check("project is writable", not ok, why)
if not ok:
    os.remove("/work/.l1_probe_write_ok")

# 2b. the audit FIFO: the agent can add lines, but cannot read, remove or replace it (review of 6555c3c, M2)
FIFO = "/pipe/rak-mcp-audit"
ok, why = refused(lambda: os.close(os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK)))
check("audit FIFO: agent cannot read it", ok, why)
ok, why = refused(lambda: os.remove(FIFO))
check("audit FIFO: agent cannot remove it", ok, why)
ok, why = refused(lambda: open("/pipe/other", "w").close())
check("audit FIFO: agent cannot create files next to it", ok, why)
ok, why = refused(lambda: os.close(os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)))
check("audit FIFO: agent (and its MCP server) can write it", not ok, why)

# 3. privileges
cap = next((line.split()[1] for line in open("/proc/self/status") if line.startswith("CapEff")), "?")
check("no capabilities", cap.strip("0") == "", f"CapEff={cap}")
check("not root", os.getuid() != 0, f"uid={os.getuid()}")

# 4. network: only through the proxy, only to the allowlist
def fetch(url):
    return urllib.request.urlopen(url, timeout=20).status


for url, should in (("https://example.com/", False), ("https://pypi.org/simple/", False),
                    ("https://arxiv.org/", True), ("https://api.anthropic.com/", True)):
    try:
        status, got = fetch(url), True
    except urllib.error.HTTPError as e:        # an HTTP answer from the real server still means we got through
        status, got = e.code, True
    except (urllib.error.URLError, OSError) as e:
        status, got = f"{type(e).__name__}: {getattr(e, 'reason', e)}", False
    check(f"egress {'allowed' if should else 'blocked'}: {url}", got == should, status)


def direct(host, port):
    socket.create_connection((host, port), timeout=8).close()


for target in (("1.1.1.1", 443), ("8.8.8.8", 53), ("example.com", 80)):
    ok, why = refused(lambda t=target: direct(*t))
    check(f"no direct connection: {target[0]}:{target[1]}", ok, why)
ok, why = refused(lambda: socket.getaddrinfo("example.com", 443))
check("no outside DNS", ok, why)

# 5. the same three through the MCP server, which allows them (exec python3), so only L1 stands in the way
def mcp(calls):
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
    msgs += [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call", "params": c} for i, c in enumerate(calls)]
    p = subprocess.run([sys.executable, "-m", "rak.mcp_server", "--root", "/work", "--exec-allow", "python3",
                        "--audit-log", "/pipe/rak-mcp-audit"],
                       input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True, timeout=120)
    out = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    return [o.get("result", {}).get("content", [{}])[0].get("text", "") for o in out[1:]]


texts = mcp([
    {"name": "exec", "arguments": {"argv": ["python3", "-c", "open('/opt/rak/python/rak/policy/rules.json','a')"]}},
    {"name": "exec", "arguments": {"argv": ["python3", "-c",
                                            "import urllib.request;print(urllib.request.urlopen('https://example.com',timeout=15).status)"]}},
    {"name": "exec", "arguments": {"argv": ["python3", "-c", "import glob;print('HOSTVIEW', glob.glob('/mnt/*') + "
                                            "glob.glob('/c/*') + glob.glob('/Users/*') + glob.glob('/run/desktop/mnt/*'))"]}},
    {"name": "exec", "arguments": {"argv": ["python3", "-c", "open('/work/.git/hooks/pre-commit','w')"]}},
])


def by_l1(text: str, marker: str) -> bool:
    """Stopped by the OS: the server allowed the call (it ran, so it has an exit code) and the OS refused it.
    A refusal by the policy engine (L2) would say so and must not count here (review of 6555c3c, M5a)."""
    return text.startswith("exit code:") and "rak policy denied" not in text and marker in text


check("MCP allowed, L1 refused: write the rules", by_l1(texts[0], "Read-only file system"), texts[0][:200])
check("MCP allowed, L1 refused: reach example.com", by_l1(texts[1], "Tunnel connection failed: 403"), texts[1][:200])
check("MCP allowed, L1 hides: host drives", by_l1(texts[2], "HOSTVIEW []"), texts[2][:200])
if MODE == "mount":
    check("MCP allowed, L1 refused: plant a git hook", by_l1(texts[3], "Read-only file system"), texts[3][:200])
else:   # copy mode: it lands in the copy (the plants above made .git there); verify.py checks the run is refused
    check("MCP allowed, copy mode: lands in the copy only", texts[3].startswith("exit code: 0") and
          "rak policy denied" not in texts[3], texts[3][:200])

for r in RESULTS:
    print(json.dumps(r, ensure_ascii=False))
sys.exit(0 if all(r["pass"] for r in RESULTS) else 1)
