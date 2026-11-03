"""The MCP server (python/rak/mcp_server.py): stdio JSON-RPC, four tools, every call through the policy engine.

Most tests call Server.call() in-process; the protocol tests start the server as Claude Code would (a subprocess
speaking newline-delimited JSON-RPC on stdin/stdout). Nothing here needs a network or a model.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rak import mcp_server as M
from rak.policy import engine

REPO = Path(__file__).resolve().parents[2]
WIN = os.name == "nt"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid"); git(root, "config", "user.name", "t")
    (root / "notes.md").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("CANARY-OUTSIDE\n", encoding="utf-8")
    return root


def server(root, **kw):
    env = {"PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]),
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "SECRET_TOKEN": "s3cret", "ANTHROPIC_API_KEY": "k",
           "CLAUDE_PROJECT_DIR": "/elsewhere", "RAK_ROOT": "/elsewhere"}
    kw.setdefault("exec_allow", ["git", Path(sys.executable).stem])
    kw.setdefault("env", env)
    return M.Server(root, **kw)


def text(res):
    return "".join(c["text"] for c in res["content"])


def denied(res):
    return res["isError"] and text(res).startswith("rak policy denied")


# ---------------------------------------------------------------- start-up

def test_refuses_to_start_without_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    r = subprocess.run([sys.executable, "-m", "rak.mcp_server"], cwd=REPO / "python", capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode != 0 and "--root" in r.stderr and r.stdout == ""


@pytest.mark.parametrize("which", ["missing", "file"])
def test_refuses_a_root_that_is_not_a_directory(tmp_path, which):
    p = tmp_path / "x"
    if which == "file":
        p.write_text("")
    with pytest.raises(M.StartupError):
        M.Server(p)


def test_refuses_an_audit_log_inside_the_root(proj):
    with pytest.raises(M.StartupError):
        M.Server(proj, audit_log=proj / "audit.jsonl")


def test_root_comes_from_the_argument_not_the_environment(proj, tmp_path, monkeypatch):
    other = tmp_path / "other"; (other / ".rak").mkdir(parents=True)
    (other / ".rak/team.json").write_text('{"typo": 1}')                  # would make every git command an error
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
    s = server(proj)
    assert not s.call("exec", {"argv": ["git", "status"]})["isError"]
    # and a root without .git is not widened to the enclosing repository
    sub = proj / "sub"; sub.mkdir()
    assert server(sub).root == Path(os.path.realpath(sub))


def test_discipline_reads_the_root_not_an_enclosing_project(proj):
    (proj / ".rak").mkdir()
    (proj / ".rak/discipline.json").write_text(json.dumps({"experiment_patterns": ["run_exp"]}))
    sub = proj / "sub"; sub.mkdir()
    argv = [Path(sys.executable).stem, "-c", "print('run_exp')"]
    assert "D1-D2" in text(server(proj).call("exec", {"argv": argv}))           # the project's own rule applies
    assert not server(sub).call("exec", {"argv": argv})["isError"]               # but not above --root


def test_no_switch_turns_the_allowlist_off():
    import inspect
    assert "unknown" not in inspect.signature(M.Server).parameters
    assert not any("unknown" in a or "allow-unknown" in a for a in M.parser()._option_string_actions)


# ---------------------------------------------------------------- tool list and unknown tools

def test_exactly_four_tools():
    assert [t["name"] for t in M.TOOL_DEFS] == ["exec", "read", "edit", "write"]
    assert set(M.SERVER_TOOLS.values()) <= engine.TOOLS


def test_unknown_tool_is_denied_by_the_engine(proj):
    res = server(proj).call("delete", {"path": "notes.md"})
    assert denied(res) and "allowlist" in text(res)
    assert (proj / "notes.md").exists()


def test_bad_arguments_do_nothing(proj):
    s = server(proj)
    for name, args in [("read", {}), ("read", {"path": 3}), ("write", {"path": "a.txt"}),
                       ("write", {"path": "a.txt", "content": "x", "extra": 1}), ("exec", {"argv": "git status"}),
                       ("exec", {"argv": []}), ("exec", {"argv": ["git", 3]}), ("edit", {"path": "notes.md"})]:
        assert s.call(name, args)["isError"], (name, args)
    assert not (proj / "a.txt").exists()


# ---------------------------------------------------------------- paths

def test_read_inside(proj):
    res = server(proj).call("read", {"path": "notes.md"})
    assert not res["isError"] and "hello" in text(res)
    res = server(proj).call("read", {"path": str(proj / "notes.md")})
    assert not res["isError"]


@pytest.mark.parametrize("raw", ["../outside.txt", "sub/../../outside.txt", "OUTSIDE", "notes.md/../notes.md"])
def test_dotdot_and_outside_are_denied(proj, raw):
    raw = str(proj.parent / "outside.txt") if raw == "OUTSIDE" else raw
    for name, args in [("read", {}), ("write", {"content": "x"}), ("edit", {"old_string": "a", "new_string": "b"})]:
        res = server(proj).call(name, {"path": raw, **args})
        assert denied(res), (name, raw, text(res))
        assert "CANARY" not in text(res)
    assert (proj.parent / "outside.txt").read_text() == "CANARY-OUTSIDE\n"


@pytest.mark.parametrize("raw", [".git/config", ".git", ".git/hooks/pre-commit", "sub/.git/x",
                                 *([".GIT/config", ".git./config", ".git /config"] if WIN else [])])
def test_dot_git_is_denied(proj, raw):
    for name, args in [("read", {}), ("write", {"content": "x"})]:
        assert denied(server(proj).call(name, {"path": raw, **args})), (name, raw)


def _link(kind, link: Path, target: Path) -> bool:
    try:
        if kind == "symlink":
            link.symlink_to(target, target_is_directory=target.is_dir())
        else:
            if not WIN:
                return False
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            if r.returncode:
                return False
        return True
    except OSError:
        return False


@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_links_out_of_the_root_are_denied(proj, kind):
    outdir = proj.parent / "outdir"; outdir.mkdir()
    (outdir / "secret.txt").write_text("CANARY-LINK\n")
    if not _link(kind, proj / "lnk", outdir):
        pytest.skip(f"cannot create a {kind} here")
    s = server(proj)
    for name, args in [("read", {}), ("write", {"content": "x"})]:
        res = s.call(name, {"path": "lnk/secret.txt", **args})
        assert denied(res) and "CANARY" not in text(res), (name, text(res))
    assert denied(s.call("write", {"path": "lnk/new.txt", "content": "x"}))
    assert not (outdir / "new.txt").exists()
    if kind == "symlink" and _link("symlink", proj / "f.txt", proj.parent / "outside.txt"):
        assert denied(s.call("read", {"path": "f.txt"}))


def test_link_to_dot_git_is_denied(proj):
    if not _link("junction" if WIN else "symlink", proj / "g", proj / ".git"):
        pytest.skip("cannot create a link here")
    assert denied(server(proj).call("read", {"path": "g/config"}))


def test_short_names_resolve_before_the_check(proj):
    if not WIN:
        pytest.skip("8.3 names are Windows only")
    import ctypes
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.kernel32.GetShortPathNameW(str(proj / ".git" / "config"), buf, 512)
    short = buf.value
    if not short or Path(short).parent.name.lower() == ".git":
        pytest.skip("8.3 short names are off on this volume")
    assert denied(server(proj).call("read", {"path": short}))
    assert denied(server(proj).call("read", {"path": os.path.relpath(short, os.path.realpath(proj))}))


def test_hardlinked_file_is_denied(proj):
    try:
        os.link(proj.parent / "outside.txt", proj / "hl.txt")
    except OSError:
        pytest.skip("no hard links here")
    assert denied(server(proj).call("read", {"path": "hl.txt"}))


# ---------------------------------------------------------------- write / edit

def test_write_and_edit_inside(proj):
    s = server(proj)
    assert not s.call("write", {"path": "d/new.md", "content": "a\r\nb\n"})["isError"]
    assert (proj / "d/new.md").read_bytes() == b"a\r\nb\n"
    assert not s.call("edit", {"path": "notes.md", "old_string": "world", "new_string": "there"})["isError"]
    assert (proj / "notes.md").read_text() == "hello\nthere\n"


def test_edit_needs_a_unique_match(proj):
    s = server(proj)
    (proj / "r.md").write_text("x x\n")
    assert s.call("edit", {"path": "r.md", "old_string": "x", "new_string": "y"})["isError"]
    assert s.call("edit", {"path": "r.md", "old_string": "z", "new_string": "y"})["isError"]
    assert not s.call("edit", {"path": "r.md", "old_string": "x", "new_string": "y", "replace_all": True})["isError"]
    assert (proj / "r.md").read_text() == "y y\n"


@pytest.mark.parametrize("rel", [".rak/discipline.json", ".rak/frozen/a.json", ".mcp.json", ".claude/settings.json",
                                 "plugins/p/hooks/hooks.json", "x/_vendor/rak_policy/rules.json"])
def test_policy_files_cannot_be_written_but_can_be_read(proj, rel):
    s = server(proj)
    res = s.call("write", {"path": rel, "content": "{}"})
    assert denied(res) and "P1" in text(res)
    assert not (proj / rel).exists()
    (proj / rel).parent.mkdir(parents=True, exist_ok=True); (proj / rel).write_text("{}")
    assert denied(s.call("edit", {"path": rel, "old_string": "{}", "new_string": "[]"}))
    assert not s.call("read", {"path": rel})["isError"]


def test_append_only_results_doc_goes_through_the_engine(proj):
    (proj / ".rak").mkdir()
    (proj / ".rak/discipline.json").write_text(json.dumps({"results_globs": ["results/*.md"]}))
    (proj / "results").mkdir(); (proj / "results/r.md").write_bytes(b"line one\nline two\n")
    git(proj, "add", "--", ".rak/discipline.json", "results/r.md"); git(proj, "commit", "-qm", "c")
    s = server(proj)
    res = s.call("edit", {"path": "results/r.md", "old_string": "line one\n", "new_string": ""})
    assert denied(res) and "D6" in text(res)
    assert (proj / "results/r.md").read_bytes() == b"line one\nline two\n"
    assert not s.call("edit", {"path": "results/r.md", "old_string": "line two\n",
                               "new_string": "line two\nerratum\n"})["isError"]


# ---------------------------------------------------------------- exec

def test_exec_runs_argv_in_the_root(proj):
    s = server(proj)
    res = s.call("exec", {"argv": [Path(sys.executable).stem, "-c", "import os; print(os.getcwd())"]})
    assert not res["isError"], text(res)
    assert os.path.normcase(os.path.realpath(proj)) in os.path.normcase(text(res))
    assert "exit code: 0" in text(res)


def test_exec_does_not_use_a_shell(proj):
    res = server(proj).call("exec", {"argv": [Path(sys.executable).stem, "-c", "import sys; print(sys.argv[1:])",
                                              "a;b", "$HOME", "`x`", "|", "&&"]})
    assert "['a;b', '$HOME', '`x`', '|', '&&']" in text(res)


def test_exec_env_is_an_allowlist(proj):
    code = "import os, json; print(json.dumps(sorted(os.environ)))"
    res = server(proj).call("exec", {"argv": [Path(sys.executable).stem, "-c", code]})
    names = json.loads(text(res).split("\n", 1)[1].strip().splitlines()[0])
    for gone in ("SECRET_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_PROJECT_DIR", "RAK_ROOT"):
        assert gone not in names
    assert "PATH" in names or "Path" in names


def test_exec_env_allowlist_follows_run_digest_without_credentials():
    sys.path.insert(0, str(REPO / "plugins/rak-knowledge/skills/daily-digest/scripts"))
    import run_digest
    assert set(M.EXEC_ENV_ALLOW) == set(run_digest.ENV_ALLOW) - set(M.CREDENTIAL_ENV)
    assert set(M.CREDENTIAL_ENV) <= set(run_digest.ENV_ALLOW)
    assert not any(k.startswith(("CLAUDE", "RAK_", "ANTHROPIC")) for k in M.EXEC_ENV_ALLOW)


@pytest.mark.parametrize("argv", [["curl", "http://x"], ["cmd", "/c", "dir"], ["sh", "-c", "ls"],
                                  ["./git"], ["ABS_PYTHON", "-V"], ["/usr/bin/git", "status"], ["GIT/.."]])
def test_exec_outside_the_command_allowlist_is_denied(proj, argv):
    argv = [sys.executable if a == "ABS_PYTHON" else a for a in argv]            # a path, even to an allowed program
    res = server(proj).call("exec", {"argv": argv})
    assert denied(res), text(res)


def test_exec_of_a_program_inside_the_root_is_denied(proj):
    name = "tool"
    exe = proj / (name + (".bat" if WIN else ""))
    exe.write_text("@echo hi\n" if WIN else "#!/bin/sh\necho hi\n"); exe.chmod(0o755)
    s = server(proj, exec_allow=[name])
    s.env["PATH"] = str(proj) + os.pathsep + s.env["PATH"]
    assert denied(s.call("exec", {"argv": [name]}))


def test_exec_goes_through_the_engine(proj):
    res = server(proj).call("exec", {"argv": ["git", "add", "-A"]})
    assert denied(res) and "T1-T3" in text(res)


def test_engine_errors_deny(proj):
    (proj / ".rak").mkdir(); (proj / ".rak/team.json").write_text('{"typo": 1}')
    res = server(proj).call("exec", {"argv": ["git", "status"]})
    assert denied(res) and "policy error" in text(res)


def test_ask_is_denied_for_now(proj, monkeypatch):
    monkeypatch.setattr(M, "evaluate_closed", lambda *a, **k: engine.Decision("ask", "X1", "a person decides"))
    (proj / "x.md").write_text("a")
    res = server(proj).call("write", {"path": "x.md", "content": "b"})
    assert denied(res) and "a person decides" in text(res) and "approval" in text(res)
    assert (proj / "x.md").read_text() == "a"


def test_exec_timeout_kills_the_process(proj):
    s = server(proj)
    res = s.call("exec", {"argv": [Path(sys.executable).stem, "-c", "import time; time.sleep(30)"], "timeout": 1})
    assert res["isError"] and "timed out" in text(res)


def test_exec_output_is_capped(proj):
    s = server(proj, max_output=1000)
    res = s.call("exec", {"argv": [Path(sys.executable).stem, "-c", "print('x' * 100000)"]})
    t = text(res)
    assert len(t) < 1500 and "truncated" in t


def test_audit_log(proj, tmp_path):
    log = tmp_path / "audit.jsonl"
    s = server(proj, audit_log=log)
    s.call("read", {"path": "notes.md"}); s.call("read", {"path": ".git/config"})
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert [r["decision"] for r in rows] == ["allow", "deny"] and rows[1]["tool"] == "read"
    assert "hello" not in log.read_text()


# ---------------------------------------------------------------- protocol (subprocess, as Claude Code runs it)

def rpc(proc, msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode()); proc.stdin.flush()
    if "id" not in msg:
        return None
    return json.loads(proc.stdout.readline())


def test_stdio_protocol(proj):
    proc = subprocess.Popen([sys.executable, "-m", "rak.mcp_server", "--root", str(proj), "--exec-allow", "git"],
                            cwd=REPO / "python", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        r = rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "t", "version": "0"}}})
        assert r["result"]["protocolVersion"] == "2025-06-18" and "tools" in r["result"]["capabilities"]
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert [t["name"] for t in r["result"]["tools"]] == ["exec", "read", "edit", "write"]
        r = rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "read", "arguments": {"path": ".git/config"}}})
        assert r["id"] == 3 and r["result"]["isError"]
        r = rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "read", "arguments": {"path": "notes.md"}}})
        assert "hello" in r["result"]["content"][0]["text"]
        r = rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "nope"})
        assert r["error"]["code"] == -32601
        proc.stdin.write(b"{not json\n"); proc.stdin.flush()
        assert json.loads(proc.stdout.readline())["error"]["code"] == -32700
        r = rpc(proc, {"jsonrpc": "2.0", "id": 6, "method": "initialize",
                       "params": {"protocolVersion": "1999-01-01", "capabilities": {}}})
        assert r["result"]["protocolVersion"] in M.PROTOCOL_VERSIONS
        r = rpc(proc, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
        assert r["result"] == {}
    finally:
        proc.stdin.close(); proc.wait(timeout=30)
    assert proc.returncode == 0


# ---------------------------------------------------------------- the Claude Code example

def test_example_turns_the_native_tools_off():
    ex = REPO / "examples/claude-code-mcp"
    settings = json.loads((ex / "settings.json").read_text(encoding="utf-8"))
    deny = set(settings["permissions"]["deny"])
    # PowerShell: the haiku smoke (2026-11-01) found it in the tool list on Windows, a native shell around MCP
    assert {"Bash", "PowerShell", "Monitor", "Edit", "Write", "Read", "MultiEdit", "NotebookEdit", "Glob", "Grep",
            "WebFetch", "WebSearch"} <= deny
    allow = set(settings["permissions"].get("allow", []))
    assert allow == {f"mcp__rak__{t}" for t in ("exec", "read", "edit", "write")}
    mcp = json.loads((ex / "mcp.json").read_text(encoding="utf-8"))
    srv = mcp["mcpServers"]["rak"]
    assert srv["type"] == "stdio" and "--root" in srv["args"]
    assert "CLAUDE_PROJECT_DIR" not in json.dumps(srv)


def test_example_launches_with_no_built_in_tools():
    """--tools "" is the allowlist (only MCP tools remain; checked in a real run on 2026-11-01). The deny list in
    settings.json is the second layer."""
    readme = (REPO / "examples/claude-code-mcp/README.md").read_text(encoding="utf-8")
    launch = [ln for ln in readme.splitlines() if ln.strip().startswith("claude ")]
    assert launch, "README has no launch line"
    for ln in launch:
        for part in ('--tools ""', "--settings", "--mcp-config", "--strict-mcp-config"):
            assert part in ln, (part, ln)


# ---- cross-review of 94356a4 / 53f7221 ----

@pytest.mark.skipif(not WIN, reason=".cmd/.bat go through cmd.exe on Windows only")
@pytest.mark.parametrize("ext", [".cmd", ".bat", ".vbs", ".js", ".ps1"])
def test_batch_files_are_refused_on_windows(proj, tmp_path, ext):
    """the reviewer's reproduction: an allowlisted tool.cmd ran under cmd.exe, and '&' started a second command. The maintainer:
    anything PATHEXT resolves to that is not .exe or .com is refused."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    (bindir / f"tool{ext}").write_text("@echo tool ran with %*\n")
    s = server(proj, exec_allow=["tool"])
    s.env["PATH"] = str(bindir) + os.pathsep + s.env["PATH"]
    s.env["PATHEXT"] = ".COM;.EXE;.BAT;.CMD;.VBS;.JS;.PS1"
    res = s.call("exec", {"argv": ["tool", "harmless", "&", "echo", "INJECTED-second-command", ">", "injected.txt"]})
    assert denied(res) and ".exe" in text(res), text(res)
    assert not (proj / "injected.txt").exists()


def test_program_lookup_ignores_the_current_directory(proj, monkeypatch):
    """A git.exe the agent drops into the root must neither run nor hide the real git (cross-review: shutil.which on Windows
    searches the current directory first)."""
    (proj / ("git.exe" if WIN else "git")).write_bytes(b"not a program")
    monkeypatch.chdir(proj)
    s = server(proj)
    s.env["PATH"] = os.curdir + os.pathsep + s.env["PATH"]                       # a relative entry is skipped too
    res = s.call("exec", {"argv": ["git", "status", "--short"]})
    assert not res["isError"], text(res)


def test_discipline_module_itself_has_the_fixed_root(proj, tmp_path, monkeypatch):
    """Cross-review: patch the private module instance, so a function inside rak_discipline that calls project_root() gets
    --root too, not CLAUDE_PROJECT_DIR or a walk up."""
    other = tmp_path / "other"; (other / ".rak").mkdir(parents=True)
    (other / ".rak/discipline.json").write_text(json.dumps({"experiment_patterns": ["run_exp"]}))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
    s = server(proj)
    assert vars(s.discipline)["project_root"]() == s.root
    assert vars(s.discipline)["project_root"](str(other)) == s.root
    argv = [Path(sys.executable).stem, "-c", "print('run_exp')"]
    assert not s.call("exec", {"argv": argv})["isError"]


def test_audit_log_records_exec_argv(proj, tmp_path):
    log = tmp_path / "audit.jsonl"
    s = server(proj, audit_log=log)
    s.call("exec", {"argv": ["git", "status"]}); s.call("exec", {"argv": ["curl", "x" * 5000]})
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert rows[0]["argv"] == ["git", "status"]
    assert rows[1]["decision"] == "deny" and len(json.dumps(rows[1]["argv"])) < 1200


@pytest.mark.parametrize("rel", ["sub/.claude/settings.json", ".claude./settings.json", ".claude /settings.json",
                                 "sub/.github/workflows/x.yml", ".envrc"])
def test_policy_names_in_new_folders_cannot_be_created(proj, rel):
    """maintainer 2026-11-01: the folder does not exist yet, so realpath cannot fold the spelling back to the real name."""
    res = server(proj).call("write", {"path": rel, "content": "{}"})
    assert denied(res), (rel, text(res))
    assert sorted(p.name for p in proj.iterdir()) == [".git", "notes.md"]
