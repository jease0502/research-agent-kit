"""daily-digest runner: config, prompt, time gate, and success judged by the digest file, not the exit code.

A fake `claude` (a small Python script) stands in for the real CLI: it reads the prompt from stdin,
records it, and either writes today's digest or not, with whatever exit code the test asks for.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "daily-digest"
sys.path.insert(0, str(SKILL / "scripts"))
import run_digest as R  # noqa: E402

NOW = dt.datetime(2026, 1, 15, 10, 0)

FAKE = """
import os, sys, pathlib
prompt = sys.stdin.buffer.read().decode("utf-8")
pathlib.Path(os.environ["FAKE_PROMPT_OUT"]).write_text(prompt, encoding="utf-8")
pathlib.Path(os.environ["FAKE_ARGS_OUT"]).write_text("\\n".join(sys.argv[1:]), encoding="utf-8")
if os.environ.get("FAKE_WRITE") == "1":
    d = pathlib.Path("docs/digest"); d.mkdir(parents=True, exist_ok=True)
    (d / "2026-01-15.md").write_text("# digest", encoding="utf-8")
print("summary: 3 papers added")
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""

CONFIG = """
topics = ["legged locomotion", "sim-to-real"]
notify_cmd = "{notify}"
log_dir = "{logs}"

[[lines]]
name = "quadruped from scratch"
open_problems = ["reward gives no gradient early", "entropy runs away"]
"""


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    root.mkdir()
    fake = tmp_path / "fake_claude.py"
    fake.write_text(FAKE, encoding="utf-8")
    notify = tmp_path / "notify.py"
    notify.write_text("import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')",
                      encoding="utf-8")
    note_out = tmp_path / "notified.txt"
    (root / "digest.toml").write_text(CONFIG.format(
        notify=f"{Path(sys.executable).as_posix()} {notify.as_posix()} {note_out.as_posix()}",
        logs=(tmp_path / "logs").as_posix()), encoding="utf-8")
    monkeypatch.setenv("RAK_CLAUDE_CMD", f"{Path(sys.executable).as_posix()} {fake.as_posix()}")
    monkeypatch.setenv("FAKE_PROMPT_OUT", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("FAKE_ARGS_OUT", str(tmp_path / "args.txt"))
    monkeypatch.delenv("FAKE_WRITE", raising=False)
    monkeypatch.delenv("FAKE_EXIT", raising=False)
    # the agent's environment is an allow list (cross-review of 8769c58); the fake CLI reads its orders from these
    monkeypatch.setattr(R, "ENV_ALLOW", R.ENV_ALLOW + ("FAKE_PROMPT_OUT", "FAKE_ARGS_OUT", "FAKE_WRITE", "FAKE_EXIT"))
    # the runner fetches the candidates itself (cross-review of 3172481); tests never touch the network
    monkeypatch.setattr(R, "fetch_candidates", lambda *a, **k: [
        {"id": "2601.00001", "title": "Legged locomotion from scratch", "published": "2026-01-14", "abstract": "a"}])
    return root, tmp_path, note_out


def run(root, *extra, now=NOW):
    return R.main(["--root", str(root), *extra], now=now)


def test_prompt_is_fully_filled(kb):
    root, _, _ = kb
    cfg = R.load_config(root)
    p = R.render_prompt(cfg, NOW.date())
    assert "{{" not in p and "2026-01-15" in p
    assert "quadruped from scratch" in p and "entropy runs away" in p
    assert "- legged locomotion" in p
    assert "Do not commit." in p                     # the runner commits (and pushes, if enabled), never the agent
    assert "Conference season" not in p              # none configured


def test_success_is_the_digest_file_not_the_exit_code(kb, monkeypatch):
    root, tmp, note = kb
    monkeypatch.setenv("FAKE_WRITE", "1")
    monkeypatch.setenv("FAKE_EXIT", "3")             # crashed after writing: the job was done
    assert run(root) == 0
    assert "3 papers added" in note.read_text(encoding="utf-8")


def test_exit_zero_without_digest_is_failure(kb):
    root, tmp, note = kb
    assert run(root) == 1
    msg = note.read_text(encoding="utf-8")
    assert "failed" in msg and "exit 0 but no digest" in msg


def test_prompt_goes_through_stdin_not_argv(kb, monkeypatch):
    root, tmp, _ = kb
    monkeypatch.setenv("FAKE_WRITE", "1")
    run(root)
    args = (tmp / "args.txt").read_text(encoding="utf-8").splitlines()
    assert args[0] == "-p" and "--allowedTools" in args
    assert not any("Research lines" in a for a in args)
    assert "Research lines" in (tmp / "prompt.txt").read_text(encoding="utf-8")


def test_allowed_tools(kb):
    root, _, _ = kb
    cfg = R.load_config(root)
    tools = R.allowed_tools(cfg).split(",")
    assert not any("python" in t for t in tools)     # no script execution at all (cross-review of 3172481)
    assert "Edit(/.rak/tmp/**)" in tools and "Edit(/papers/**)" in tools
    assert not any(t.startswith("Bash(git push") for t in tools)
    assert not any("notify.py" in t for t in tools)   # the runner notifies; the agent does not need it
    cfg["push"] = True
    assert not any("git" in t for t in R.allowed_tools(cfg).split(","))   # push is the runner's (cross-review of 6d87ef3)


def test_time_gate_and_existing_digest(kb, monkeypatch):
    root, tmp, _ = kb
    assert run(root, now=dt.datetime(2026, 1, 15, 8, 0)) == 0
    assert not (tmp / "prompt.txt").exists()        # before `earliest`: claude never ran
    (root / "docs" / "digest").mkdir(parents=True)
    (root / "docs" / "digest" / "2026-01-15.md").write_text("x", encoding="utf-8")
    assert run(root) == 0 and not (tmp / "prompt.txt").exists()
    monkeypatch.setenv("FAKE_WRITE", "1")
    assert run(root, "--force") == 0 and (tmp / "prompt.txt").exists()


def test_log_is_utf8(kb, monkeypatch):
    root, tmp, _ = kb
    monkeypatch.setenv("FAKE_WRITE", "1")
    run(root)
    log = (tmp / "logs" / "digest-2026-01-15.log").read_text(encoding="utf-8")
    assert "summary: 3 papers added" in log and "exit 0" in log


@pytest.mark.parametrize("bad,match", [('topcs = ["x"]\ntopics = ["y"]', "unknown keys"),
                                      ('topics = []', "topics"),
                                      ('topics = ["x"]\n[[lines]]\nopen_problems = ["p"]', "needs a name")])
def test_config_errors(tmp_path, bad, match):
    (tmp_path / "digest.toml").write_text(bad, encoding="utf-8")
    with pytest.raises(R.ConfigError, match=match):
        R.load_config(tmp_path)
    assert R.main(["--root", str(tmp_path)], now=NOW) == 2


def test_conference_section_only_in_season(kb):
    root, _, _ = kb
    cfg = R.load_config(root)
    cfg["conferences"] = [{"name": "CONF 2026", "season_start": "2026-01-01", "season_end": "2026-01-31"}]
    assert "Conference season: CONF 2026" in R.render_prompt(cfg, NOW.date())
    assert "Conference season" not in R.render_prompt(cfg, dt.date(2026, 3, 1))


def test_dry_run_runs_nothing(kb, capsys):
    root, tmp, _ = kb
    assert run(root, "--dry-run") == 0
    assert not (tmp / "prompt.txt").exists()
    assert "--allowedTools" in capsys.readouterr().out


def test_example_config_is_valid(tmp_path):
    (tmp_path / "digest.toml").write_bytes((SKILL / "scripts" / "digest.example.toml").read_bytes())
    cfg = R.load_config(tmp_path)
    assert "{{" not in R.render_prompt(cfg, dt.date(2026, 7, 1))
