"""The policy's own files are not written through a file tool (P1 in docs/policy-engine.md; cross-review of the
step-2 plan). Reads stay allowed. A second layer only: a shell command can still write these files, and the rule
does nothing when the files sit where no tool reaches them, which is where they belong (an L1 read-only mount).

Protected, at any depth: the engine (rak/policy/, _vendor/rak_policy/, rak/mcp_server.py), project state and config
(.rak/), git (.git/, .gitmodules, .gitattributes), Claude Code config (.claude/, .mcp.json, .claude-plugin/), the
hooks and their backends (plugins/*/hooks/, plugins/*/scripts/, any hooks.json), the lifecycle trees
(plugins/*/trees/), git hooks (scripts/hooks/, .husky/, .githooks/, pre-commit and lefthook configs), CI (.github/,
GitLab, CircleCI, Azure, Jenkins), other agents' and editors' config (.gemini/, .codex/, .vscode/, .idea/,
.devcontainer/), .envrc, and the scanner with its allow file. Plus this package's own folder wherever it lives.

protected_name() is the one judgement of "is this name one of those", shared with the sandbox
(templates/sandbox/host.py). It compares path components, not strings, in every spelling a host filesystem may
resolve to the real name: each component is put in NFC and stripped of invisible (default-ignorable) characters
(macOS, HFS+), case is ignored, trailing dots and spaces are dropped (Windows does), and a component that looks
like an 8.3 short name (GIT~1) counts, since on a volume with short names it may be one.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

# folders, as component sequences ("*" is any one component), protected wherever they occur
PROTECTED_DIRS = (
    ("rak", "policy"), ("_vendor", "rak_policy"), (".rak",), (".git",), (".claude",), (".claude-plugin",),
    ("plugins", "*", "hooks"), ("plugins", "*", "scripts"), ("plugins", "*", "trees"), ("scripts", "hooks"),
    (".github",), (".husky",), (".githooks",), (".circleci",), (".gemini",), (".codex",), (".vscode",), (".idea",),
    (".devcontainer",),
)
# files, as the trailing components of a path, protected wherever they occur
PROTECTED_FILES = (
    ("rak", "mcp_server.py"), (".mcp.json",), ("hooks.json",), ("scan_private.py",), (".rak-scan-allow",),
    (".pre-commit-config.yaml",), ("lefthook.yml",), (".lefthook.yml",), (".gitlab-ci.yml",),
    ("azure-pipelines.yml",), ("jenkinsfile",), (".envrc",), (".gitmodules",), (".gitattributes",),
)
# the same lists as glob patterns ("*" crosses "/"), for readers that compare lists (python/tests/test_sandbox.py)
PROTECTED = tuple("*/" + "/".join(d) + "/*" for d in PROTECTED_DIRS) + tuple("*/" + "/".join(f)
                                                                            for f in PROTECTED_FILES)
SHORT_NAME = re.compile(r"^[^~]{1,8}~\d+(\.[^.]{0,3})?$")       # an 8.3 alias such as GIT~1 or CLAUDE~1.JSO
HERE = os.path.normcase(os.path.realpath(Path(__file__).resolve().parent))


def _invisible(ch: str) -> bool:
    """Default-ignorable code points: HFS+ ignores some of them in names, so '.g‌it' can be '.git' there."""
    o = ord(ch)
    return (unicodedata.category(ch) == "Cf" or 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF
            or o in (0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0) or 0x180B <= o <= 0x180F)


def _clean(part: str) -> str:
    """macOS normalizes Unicode and HFS+ drops invisible characters: NFC, then without them (cross-review of 149894e)."""
    return "".join(ch for ch in unicodedata.normalize("NFC", part) if not _invisible(ch))


def _canon(part: str) -> str:
    return part.rstrip(". ").casefold()


def _seq_at(canon: list[str], seq: tuple[str, ...], i: int) -> bool:
    return all(s == "*" or canon[i + k] == s for k, s in enumerate(seq))


def protected_name(rel: str) -> str | None:
    """The protected entry a path falls under (as "x/y/" for a folder, "x" for a file), or None."""
    parts = [_clean(p) for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(SHORT_NAME.match(p) for p in parts):
        return "an 8.3 short name"
    canon = [_canon(p) for p in parts]
    for d in PROTECTED_DIRS:                     # a folder: the sequence anywhere, also as the last name (a gitlink
        for i in range(len(canon) - len(d) + 1):  # ".git" file is a file; re-review of 36894b9)
            if _seq_at(canon, d, i):
                return "/".join(d) + "/"
    for f in PROTECTED_FILES:                    # a file: the sequence at the end
        if len(canon) >= len(f) and _seq_at(canon, f, len(canon) - len(f)):
            return "/".join(f)
    return None


def protected_file(event) -> str | None:
    raw = event.args.get("path") or ""
    base = os.path.realpath(event.cwd or os.getcwd())
    p = os.path.realpath(os.path.join(base, raw))
    if os.path.normcase(p) == HERE or os.path.normcase(p).startswith(HERE + os.sep):
        return f"{raw} is the policy engine itself"
    rel = os.path.relpath(p, base) if os.path.normcase(p).startswith(os.path.normcase(base) + os.sep) else p
    # judge the name as given too: realpath folds a spelling back to the real name only when that name exists
    why = protected_name(rel) or protected_name(raw)
    if why:
        return (f"{raw} is a policy, hook, project-state or agent/editor config file ({why}); it is read-only to "
                "the agent. A person changes it.")
    return None
