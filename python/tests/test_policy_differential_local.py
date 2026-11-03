"""The differential test over real commands: the Bash commands in this machine's Claude Code transcripts
(~/.claude/projects/**/*.jsonl), each through the old and the new hook of all three plugins.

Local only, and off unless RAK_LOCAL_TRANSCRIPTS=1. The commands are read at test time and never written anywhere:
they can hold private paths, names and tokens. Each one is scanned with scripts/scan_private.py first and skipped on
any hit; without the deny list the whole run is skipped. Only counts are printed (and copied into
docs/policy-engine.md by hand).
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

import test_policy_differential as td

pytestmark = pytest.mark.skipif(os.environ.get("RAK_LOCAL_TRANSCRIPTS") != "1", reason="set RAK_LOCAL_TRANSCRIPTS=1")
CAP = int(os.environ.get("RAK_LOCAL_CAP", "20000"))


def bash_commands() -> list[str]:
    seen = set()
    for f in (Path.home() / ".claude" / "projects").rglob("*.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            if '"Bash"' not in ln:
                continue
            try:
                msg = json.loads(ln).get("message") or {}
            except ValueError:
                continue
            for c in msg.get("content") or [] if isinstance(msg, dict) else []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmd = (c.get("input") or {}).get("command")
                    if isinstance(cmd, str):
                        seen.add(cmd)
    return sorted(seen)


def test_real_commands_match_legacy(capsys):
    sys.path.insert(0, str(td.REPO / "scripts"))
    import scan_private as sp
    terms, why = sp.load_terms()
    if terms is None:
        pytest.skip(f"no deny list, so commands cannot be screened: {why}")
    cmds = bash_commands()
    clean = [c for c in cmds if not any(True for _ in sp.scan_text("cmd", c, terms))]
    rng = random.Random(1031)
    sample = rng.sample(clean, min(CAP, len(clean)))
    t = Path(tempfile.mkdtemp(prefix="rakpol-local-"))
    try:
        team = t / "team"; team.mkdir(); td.git(team, "init", "-q")
        repos = [td.discipline_repo(t, s) for s in ("unfrozen", "frozen", "gate_pass")]
        out = {"transcript_commands": len(cmds), "skipped_by_scan": len(cmds) - len(clean), "compared": len(sample)}
        out["team"] = td.compare("team", [{"tool_name": "Bash", "tool_input": {"command": c}, "cwd": str(team)}
                                          for c in sample])
        out["trees"] = td.compare("trees", [{"tool_name": "Bash", "tool_input": {"command": c},
                                             "cwd": str(td.PLUGINS / "rak-cloud")} for c in sample],
                                  {"CLAUDE_PLUGIN_ROOT": str(td.PLUGINS / "rak-cloud")})
        out["discipline"] = td.compare("discipline", [{"tool_name": "Bash", "tool_input": {"command": c},
                                                       "cwd": str(rng.choice(repos))} for c in sample])
    finally:
        shutil.rmtree(t, ignore_errors=True)
    with capsys.disabled():
        print("\nlocal differential (counts only):", json.dumps(out))
