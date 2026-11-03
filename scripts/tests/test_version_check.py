"""The SessionStart version check (plugins/*/hooks/version_check.py): below Claude Code 2.1.295, or when the version
cannot be read, the user is warned that a failing guard hook lets calls through. An unreadable version is a warning,
never a pass (maintainer, after 8e0c5ee)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COPIES = sorted(REPO.glob("plugins/*/hooks/version_check.py"))
PLUGINS_WITH_HOOKS = sorted(p.parent.parent for p in REPO.glob("plugins/*/hooks/hooks.json"))


def test_every_plugin_with_hooks_has_the_check_and_registers_it():
    assert {p.parent.parent for p in COPIES} == set(PLUGINS_WITH_HOOKS)
    texts = {p.read_bytes().replace(b"\r\n", b"\n") for p in COPIES}
    assert len(texts) == 1, "the copies of version_check.py differ"
    for plugin in PLUGINS_WITH_HOOKS:
        hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        cmds = [h["command"] for e in hooks.get("SessionStart", []) for h in e["hooks"]]
        assert any("version_check.py" in c for c in cmds), plugin.name


def fake_claude(folder: Path, output: str, code: int = 0) -> None:
    """A `claude` on PATH that prints `output`."""
    py = folder / "fake_claude.py"
    py.write_text(f"import sys\nprint({output!r})\nsys.exit({code})\n")
    if os.name == "nt":
        (folder / "claude.cmd").write_text(f'@"{sys.executable}" "{py}" %*\r\n')
    else:
        sh = folder / "claude"
        sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n'); sh.chmod(0o755)


def run(path_dirs: list[Path], session: str | None = None) -> dict | None:
    env = dict(os.environ, PATH=os.pathsep.join(str(d) for d in path_dirs))
    r = subprocess.run([sys.executable, str(COPIES[0])], input=json.dumps({"session_id": session or uuid.uuid4().hex}),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


@pytest.fixture
def bindir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_current_version_is_quiet(bindir):
    fake_claude(bindir, "2.1.316 (Claude Code)")
    assert run([bindir]) is None


def test_exactly_the_minimum_is_quiet(bindir):
    fake_claude(bindir, "2.1.295 (Claude Code)")
    assert run([bindir]) is None


@pytest.mark.parametrize("out", ["2.1.294 (Claude Code)", "2.0.999 (Claude Code)", "1.9.0"])
def test_old_version_warns(bindir, out):
    fake_claude(bindir, out)
    r = run([bindir])
    assert "LETS THE CALL THROUGH" in r["systemMessage"] and "older than 2.1.295" in r["systemMessage"]
    assert r["hookSpecificOutput"]["additionalContext"] == r["systemMessage"]


@pytest.mark.parametrize("out,code", [("no version here", 0), ("2.1.316", 1), ("", 0)])
def test_unreadable_version_warns(bindir, out, code):
    fake_claude(bindir, out, code)
    r = run([bindir])
    assert "could not read the Claude Code version" in r["systemMessage"]


def test_claude_not_on_path_warns(bindir):
    r = run([bindir])                           # an empty folder as the whole PATH
    assert "not on PATH" in r["systemMessage"]


def test_one_warning_per_session(bindir):
    fake_claude(bindir, "2.1.200")
    s = uuid.uuid4().hex
    assert run([bindir], s) is not None
    assert run([bindir], s) is None             # the second plugin's copy in the same session stays quiet
