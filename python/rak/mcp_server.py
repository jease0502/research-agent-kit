"""rak's MCP server (L2 in docs/harness-landscape.md §4): exec, read, edit and write, each call through the policy
engine before anything runs. Standard library only; stdio transport (newline-delimited JSON-RPC 2.0), no port.

    python -m rak.mcp_server --root /abs/project [--exec-allow git --exec-allow python] [--audit-log FILE]

What it holds, in this order, for every call (docs/mcp-server.md):
1. The project root is the --root argument, resolved once at start. Nothing reads CLAUDE_PROJECT_DIR, and the root
   is not widened to an enclosing repository. Without --root, or with one that is not a directory, it does not start.
2. read / edit / write: the path is resolved (symlinks, junctions, 8.3 names) and must land inside the root; a `..`
   component, anything under .git, and a hard-linked file are refused before the engine sees the call.
3. exec: an argv array, never a shell. argv[0] is a bare command name on --exec-allow, found on PATH and not inside
   the root (our own PATH lookup, never the current directory); on Windows only .exe and .com, since a .cmd/.bat
   runs through cmd.exe. cwd is the root; the environment is EXEC_ENV_ALLOW; there is a timeout and an output cap.
4. The policy engine with every rule (plugin=None) and unknown="deny": the tool list is an allowlist, and no flag
   or variable turns that off. Any engine error is a deny (evaluate_closed). "ask" is a deny for now: there is no
   approval path over MCP yet.
Every decision goes to stderr and, with --audit-log, to a JSONL file outside the root (tool, decision, rule, reason;
no file contents).

This process has real access, so it fails closed and has no bypass. It is not the wall: an allowed command's own
arguments can reach outside the root (git -C, python -c), and the agent's context files are read without a tool.
The wall is L1, and the server's code and rules belong where the agent cannot write (docs/mcp-server.md §threat).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path

from .policy import Event, evaluate_closed

NAME, VERSION = "rak", "0.1.0"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")    # newest first
SERVER_TOOLS = {"exec": "shell", "read": "file.read", "edit": "file.edit", "write": "file.write"}
WIN = os.name == "nt"
# run_digest's ENV_ALLOW (the agent process's environment) without what logs Claude in: a command the agent runs
# has no business with the API key. A test keeps the two lists in step.
CREDENTIAL_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                  "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH")
EXEC_ENV_ALLOW = (
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "COMSPEC", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER",
    "USERNAME", "LOGNAME", "SHELL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
)
TIMEOUT_DEFAULT, TIMEOUT_MAX = 120, 600
MAX_OUTPUT, MAX_READ, MAX_FILE = 100_000, 256_000, 20_000_000

_STR = {"type": "string"}
TOOL_DEFS = [
    {"name": "exec", "description": "Run one command in the project root, without a shell: argv is the program and "
     "its arguments. Only allowlisted programs run; pipes, redirects and && are plain arguments here.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["argv"], "properties": {
         "argv": {"type": "array", "items": _STR, "minItems": 1},
         "timeout": {"type": "integer", "minimum": 1, "maximum": TIMEOUT_MAX}}}},
    {"name": "read", "description": "Read a text file inside the project root. offset (1-based line) and limit "
     "(lines) are optional.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["path"], "properties": {
         "path": _STR, "offset": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}}}},
    {"name": "edit", "description": "Replace old_string with new_string in a file inside the project root. "
     "old_string must occur exactly once unless replace_all is true.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["path", "old_string", "new_string"], "properties": {
                         "path": _STR, "old_string": _STR, "new_string": _STR, "replace_all": {"type": "boolean"}}}},
    {"name": "write", "description": "Write a whole file inside the project root (parent folders are created).",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["path", "content"],
                     "properties": {"path": _STR, "content": _STR}}},
]
_SCHEMAS = {t["name"]: t["inputSchema"] for t in TOOL_DEFS}


class StartupError(Exception):
    pass


class Refused(Exception):
    """The server's own confinement said no (before the engine)."""


class BadArgs(Exception):
    pass


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


def _inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip("\\/") + os.sep)


def _check_args(name: str, args) -> dict:
    schema = _SCHEMAS.get(name)
    if schema is None:
        return args if isinstance(args, dict) else {}
    if not isinstance(args, dict):
        raise BadArgs("arguments must be an object")
    props = schema["properties"]
    extra = set(args) - set(props)
    if extra:
        raise BadArgs(f"unknown arguments {sorted(extra)}")
    for k in schema["required"]:
        if k not in args:
            raise BadArgs(f"missing argument {k!r}")
    for k, v in args.items():
        t = props[k]["type"]
        ok = {"string": isinstance(v, str), "boolean": isinstance(v, bool),
              "integer": isinstance(v, int) and not isinstance(v, bool),
              "array": isinstance(v, list) and len(v) >= 1 and all(isinstance(x, str) for x in v)}[t]
        if not ok:
            raise BadArgs(f"argument {k!r} must be a {t}" + (" of strings, not empty" if t == "array" else ""))
        if t == "integer" and not (props[k].get("minimum", v) <= v <= props[k].get("maximum", v)):
            raise BadArgs(f"argument {k!r} out of range")
        if isinstance(v, str) and "\x00" in v or t == "array" and any("\x00" in x for x in v):
            raise BadArgs(f"argument {k!r} contains a NUL byte")
    return args


class Server:
    def __init__(self, root, exec_allow=(), plugins_dir=None, env=None, audit_log=None,
                 max_output=MAX_OUTPUT, max_read=MAX_READ):
        root = Path(root)
        if not root.is_absolute():
            root = Path.cwd() / root
        if not root.is_dir():
            raise StartupError(f"--root {root} is not a directory")
        self.root = Path(os.path.realpath(root))
        self._root_n = os.path.normcase(str(self.root))
        plugins = Path(plugins_dir) if plugins_dir else Path(__file__).resolve().parents[2] / "plugins"
        disc = plugins / "rak-discipline" / "scripts" / "rak_discipline.py"
        cloud = plugins / "rak-cloud"
        if not disc.is_file() or not (cloud / "trees").is_dir():
            raise StartupError(f"plugins not found under {plugins} (need rak-discipline/scripts/rak_discipline.py "
                               "and rak-cloud/trees); pass --plugins-dir")
        spec = importlib.util.spec_from_file_location("rak_discipline_for_mcp", disc)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # a private instance of rak_discipline whose project_root() is --root. The hook walks up from cwd and reads
        # CLAUDE_PROJECT_DIR; the server has one root. Patched on the module itself (not wrapped), so a function in
        # the module that calls project_root() internally gets --root too (cross-review of 94356a4).
        root_ = self.root
        mod.project_root = lambda start=None: root_
        self.discipline = mod
        self.plugin_root = str(cloud.resolve())
        self.exec_allow = {self._cmd_key(c) for c in exec_allow}
        src = os.environ if env is None else env
        self.env = {k: v for k, v in src.items() if k.upper() in EXEC_ENV_ALLOW}
        self.audit_log = None
        if audit_log:
            a = Path(os.path.realpath(Path(audit_log).absolute()))
            if _inside(os.path.normcase(str(a)), self._root_n):
                raise StartupError("--audit-log must be outside --root (the agent can write inside it)")
            self.audit_log = a
        self.max_output, self.max_read = max_output, max_read

    # ------------------------------------------------------------ confinement

    @staticmethod
    def _cmd_key(name: str) -> str:
        name = name.lower() if WIN else name
        if WIN:
            for ext in (".exe", ".com", ".bat", ".cmd"):
                if name.endswith(ext):
                    return name[: -len(ext)]
        return name

    def _path(self, raw: str) -> Path:
        if not raw:
            raise BadArgs("path is empty")
        if ".." in Path(raw).parts or ".." in raw.replace("\\", "/").split("/"):
            raise Refused(f"{raw}: '..' is not allowed")
        full = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(self.root, raw))
        n = os.path.normcase(full)
        if not _inside(n, self._root_n):
            raise Refused(f"{raw} resolves outside the project root")
        rel = os.path.relpath(n, self._root_n)
        for part in rel.replace("\\", "/").split("/"):
            if part.rstrip(". ").lower() == ".git":
                raise Refused(f"{raw} is under .git")
            if WIN and ":" in part:
                raise Refused(f"{raw}: alternate data streams are not allowed")
        if os.path.isfile(full) and os.stat(full).st_nlink > 1:
            raise Refused(f"{raw} has other hard links, which may point outside the root")
        return Path(full)

    def _program(self, argv: list[str]) -> str:
        name = argv[0]
        if not name or "/" in name or "\\" in name or (WIN and ":" in name):
            raise Refused(f"{name!r}: argv[0] must be a bare command name, not a path")
        if self._cmd_key(name) not in self.exec_allow:
            raise Refused(f"{name!r} is not on the server's --exec-allow list ({sorted(self.exec_allow) or 'empty'})")
        exe = _which(name, self.env.get("PATH") or self.env.get("Path") or "",
                     self.env.get("PATHEXT") or os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD")
        if not exe:
            raise Refused(f"{name!r} is not on PATH")
        exe = os.path.realpath(exe)
        if _inside(os.path.normcase(exe), self._root_n):
            raise Refused(f"{name!r} resolves to {exe}, inside the project root")
        if WIN and os.path.splitext(exe)[1].lower() not in (".exe", ".com"):
            # anything else runs through an interpreter: a .bat/.cmd through cmd.exe, where list2cmdline does not
            # escape & | > ^, so one argument becomes a second command, unseen by the shell rules (cross-review of
            # 94356a4); .vbs/.js/.ps1 through their hosts. Only real executables, whatever PATHEXT says (maintainer).
            raise Refused(f"{name!r} resolves to {exe}, not an .exe or .com, so Windows would run it through an "
                          "interpreter (cmd.exe for .cmd/.bat); allowlist the real program instead, e.g. the node.exe "
                          "or claude.exe a .cmd wrapper calls")
        return exe

    # ------------------------------------------------------------ calls

    def call(self, name: str, args) -> dict:
        tool = SERVER_TOOLS.get(name, f"other:{name}")
        rule, reason = "", ""
        try:
            args = _check_args(name, args)
            if tool == "shell":
                exe = self._program(args["argv"])
                eargs = {"command": shlex.join(args["argv"])}
            elif tool.startswith("file."):
                path = self._path(args["path"])
                eargs = {"path": str(path)}
                if tool == "file.write":
                    eargs["content"] = args["content"]
                elif tool == "file.edit":
                    eargs["edits"] = [{"old_string": args["old_string"], "new_string": args["new_string"],
                                       "replace_all": bool(args.get("replace_all"))}]
            else:
                eargs = dict(args)
            event = Event(tool, eargs, cwd=str(self.root), env={"PLUGIN_ROOT": self.plugin_root},
                          native_tool=f"mcp:{name}", backends={"discipline": self.discipline})
            d = evaluate_closed(event, unknown="deny")
            if d.decision != "allow":
                rule, reason = d.rule, d.reason
                if d.decision == "ask":
                    reason += " (this needs a person's approval, and the MCP server has no approval path yet)"
                raise Refused(reason)
        except Refused as e:
            self._audit(name, "deny", rule or "server", str(e), args)
            return _result(f"rak policy denied{f' ({rule})' if rule else ''}: {e}", error=True)
        except BadArgs as e:
            self._audit(name, "bad-args", "", str(e), args)
            return _result(f"bad arguments: {e}", error=True)
        self._audit(name, "allow", "", "", args)
        try:
            if tool == "shell":
                return self._exec(exe, args)
            if tool == "file.read":
                return self._read(path, args)
            if tool == "file.write":
                return self._write(path, args)
            return self._edit(path, args)
        except Exception as e:     # the call was allowed but failed: report it, never retry differently
            return _result(f"{name} failed: {type(e).__name__}: {e}", error=True)

    def _read(self, path: Path, args) -> dict:
        if not path.is_file():
            return _result(f"{args['path']}: not a file", error=True)
        if path.stat().st_size > MAX_FILE:
            return _result(f"{args['path']}: larger than {MAX_FILE} bytes", error=True)
        text = path.read_bytes().decode("utf-8", errors="replace")
        if "offset" in args or "limit" in args:
            lines = text.splitlines(keepends=True)
            start = args.get("offset", 1) - 1
            text = "".join(lines[start: start + args["limit"]] if "limit" in args else lines[start:])
        if len(text) > self.max_read:
            text = text[: self.max_read] + f"\n[truncated at {self.max_read} characters; use offset/limit]"
        return _result(text)

    def _write(self, path: Path, args) -> dict:
        if path.exists() and not path.is_file():
            return _result(f"{args['path']}: exists and is not a file", error=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(args["content"].encode("utf-8"))
        return _result(f"wrote {len(args['content'])} characters to {args['path']}")

    def _edit(self, path: Path, args) -> dict:
        if not path.is_file():
            return _result(f"{args['path']}: not a file", error=True)
        text = path.read_bytes().decode("utf-8")
        old, new = args["old_string"], args["new_string"]
        n = text.count(old) if old else 0
        if n == 0:
            return _result("old_string not found (or empty)", error=True)
        if n > 1 and not args.get("replace_all"):
            return _result(f"old_string occurs {n} times; make it unique or set replace_all", error=True)
        text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        path.write_bytes(text.encode("utf-8"))
        return _result(f"replaced {n if args.get('replace_all') else 1} occurrence(s) in {args['path']}")

    def _exec(self, exe: str, args) -> dict:
        timeout = args.get("timeout", TIMEOUT_DEFAULT)
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WIN else {"start_new_session": True}
        proc = subprocess.Popen([exe, *args["argv"][1:]], cwd=self.root, env=self.env, shell=False,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        kept, dropped = bytearray(), [0]

        def pump():
            while chunk := proc.stdout.read(65536):
                room = self.max_output - len(kept)
                kept.extend(chunk[:max(room, 0)])
                dropped[0] += max(len(chunk) - max(room, 0), 0)

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            proc.wait()
        t.join(timeout=5)
        out = kept.decode("utf-8", errors="replace")
        if dropped[0]:
            out += f"\n[truncated: {dropped[0]} more bytes]"
        if timed_out:
            return _result(f"timed out after {timeout} s; killed\n{out}", error=True)
        return _result(f"exit code: {proc.returncode}\n{out}", error=proc.returncode != 0)

    def _audit(self, name: str, decision: str, rule: str, reason: str, args=None) -> None:
        row = {"time": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "tool": name,
               "decision": decision, "rule": rule, "reason": reason[:300]}
        argv = args.get("argv") if isinstance(args, dict) else None
        if isinstance(argv, list):          # exec's command line (not file contents), cut to a sane size
            row["argv"] = [str(a)[:200] for a in argv[:20]] + (["..."] if len(argv) > 20 else [])
        line = json.dumps(row, ensure_ascii=False)
        print(f"rak-mcp: {line}", file=sys.stderr, flush=True)
        if self.audit_log:
            with open(self.audit_log, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ------------------------------------------------------------ JSON-RPC

    def handle(self, msg) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method, mid = msg.get("method"), msg.get("id")
        if method is None:                       # a response from the client: nothing to do
            return None
        params = msg.get("params") or {}
        if method == "initialize":
            want = params.get("protocolVersion") if isinstance(params, dict) else None
            res = {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": NAME, "version": VERSION},
                   "instructions": "Shell and file access go through these tools only. exec takes an argv array "
                                   "(no shell); paths are relative to the project root. A denied call says why."}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": TOOL_DEFS}
        elif method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return _error(mid, -32602, "tools/call needs a name")
            res = self.call(params["name"], params.get("arguments") or {})
        elif "id" not in msg:                    # notifications/initialized and other notifications
            return None
        else:
            return _error(mid, -32601, f"method not found: {method}")
        return None if "id" not in msg else {"jsonrpc": "2.0", "id": mid, "result": res}


def _which(name: str, path: str, pathext: str) -> str | None:
    """shutil.which without the current directory: before Python 3.12 it searched cwd first on Windows, so a
    program dropped into the root (the server's cwd may be the root) would shadow the real one. Relative PATH
    entries are skipped for the same reason."""
    exts = [""]
    if WIN:
        exts = [e.lower() for e in pathext.split(";") if e]
        if os.path.splitext(name)[1].lower() in exts:
            exts = [""]
    for d in path.split(os.pathsep):
        if not d or not os.path.isabs(d):
            continue
        for e in exts:
            f = os.path.join(d, name + e)
            if os.path.isfile(f) and (WIN or os.access(f, os.X_OK)):
                return f
    return None


def _result(text: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m rak.mcp_server", description=__doc__.split("\n\n")[0])
    p.add_argument("--root", required=True, help="the project root (absolute); the only folder the tools touch")
    p.add_argument("--exec-allow", action="append", default=[], metavar="NAME",
                   help="a command exec may run (repeat); none given: exec runs nothing")
    p.add_argument("--plugins-dir", help="where rak-discipline and rak-cloud live (default: this checkout's)")
    p.add_argument("--audit-log", help="append one JSON line per call here (must be outside --root)")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        srv = Server(args.root, exec_allow=args.exec_allow, plugins_dir=args.plugins_dir, audit_log=args.audit_log)
    except StartupError as e:
        print(f"rak-mcp: not starting: {e}", file=sys.stderr)
        return 2
    out = sys.stdout.buffer
    sys.stdout = sys.stderr                      # nothing but protocol messages may reach stdout
    for raw in sys.stdin.buffer:
        if not raw.strip():
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            reply = _error(None, -32700, "parse error")
        else:
            try:
                reply = srv.handle(msg)
            except Exception as e:               # never die on one bad message; never act on it either
                reply = _error(msg.get("id") if isinstance(msg, dict) else None, -32603,
                               f"internal error: {type(e).__name__}")
        if reply is not None:
            out.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
