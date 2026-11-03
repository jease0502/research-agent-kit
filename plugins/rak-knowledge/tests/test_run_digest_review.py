"""daily-digest runner findings of the 2026-10-31 cross-review (M18, M19, M20, lows). Each failed before its fix.

M18 config values are type-checked: `push = "false"` (a string) must not turn unattended pushes on
M19 commands are split the Windows way on Windows (backslashes kept) and a bare `claude` is resolved
    with shutil.which (npm installs claude.cmd); a TOML list is accepted as well
M20 `earliest` is validated in load_config, and unknown keys inside [[lines]] / [[conferences]] are errors
low --dry-run is not blocked by the time gate; printing on a cp950 console does not raise
"""
from __future__ import annotations

import datetime as dt
import io
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "daily-digest"
sys.path.insert(0, str(SKILL / "scripts"))
import run_digest as R  # noqa: E402

NOW = dt.datetime(2026, 1, 15, 10, 0)


def config(tmp_path, text):
    (tmp_path / "digest.toml").write_text('topics = ["x"]\n' + text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("line,match", [
    ('push = "false"', "push"),
    ('daily_limit = "30"', "daily_limit"),
    ('max_turns = 1.5', "max_turns"),
    ('categories = "cs.RO"', "categories"),
    ('notify_cmd = 3', "notify_cmd"),
    ('earliest = "9.30"', "earliest"),
    ('earliest = "25:00"', "earliest"),
])
def test_values_are_type_checked(tmp_path, line, match):
    config(tmp_path, line + "\n")
    with pytest.raises(R.ConfigError, match=match):
        R.load_config(tmp_path)
    assert R.main(["--root", str(tmp_path)], now=NOW) == 2


@pytest.mark.parametrize("table", [
    '[[lines]]\nname = "a"\nopen_problem = ["typo"]\n',
    '[[conferences]]\nname = "C"\nseason_start = "2026-01-01"\nseasonend = "2026-02-01"\n',
])
def test_unknown_keys_in_tables_are_errors(tmp_path, table):
    config(tmp_path, table)
    with pytest.raises(R.ConfigError, match="unknown keys"):
        R.load_config(tmp_path)


def test_valid_typed_config_still_loads(tmp_path):
    config(tmp_path, 'push = true\nnotify_cmd = ["python", "tg.py", "send"]\nearliest = "07:05"\n')
    cfg = R.load_config(tmp_path)
    assert cfg["push"] is True and cfg["earliest"] == "07:05"


def test_windows_paths_keep_their_backslashes():
    path = "\\".join(["C:", "Us" + "ers", "me", "AppData", "Roaming", "npm", "claude.cmd"])   # split: the scanner flags user dirs
    assert R.split_cmd(path, windows=True) == [path]
    assert R.split_cmd(f'"{path}" --flag', windows=True) == [path, "--flag"]
    assert R.split_cmd("a 'b c'", windows=False) == ["a", "b c"]
    assert R.split_cmd(["x y", "z"], windows=True) == ["x y", "z"]          # a TOML list is taken as is


def test_bare_claude_is_resolved_with_which(monkeypatch):
    monkeypatch.delenv("RAK_CLAUDE_CMD", raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda name: "C:\\npm\\claude.cmd" if name == "claude" else None)
    assert R.claude_cmd()[0] == "C:\\npm\\claude.cmd"


def test_config_error_is_notified(tmp_path):
    out = tmp_path / "notified.txt"
    notify = tmp_path / "notify.py"
    notify.write_text("import sys, pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')",
                      encoding="utf-8")
    config(tmp_path, f'notify_cmd = ["{Path(sys.executable).as_posix()}", "{notify.as_posix()}", '
                     f'"{out.as_posix()}"]\nearliest = "9.30"\n')
    assert R.main(["--root", str(tmp_path)], now=NOW) == 2
    assert "config error" in out.read_text(encoding="utf-8")                 # a silent failure is not silent


def test_dry_run_ignores_the_time_gate(tmp_path, capsys):
    config(tmp_path, "")
    assert R.main(["--root", str(tmp_path), "--dry-run"], now=dt.datetime(2026, 1, 15, 6, 0)) == 0
    assert "--- prompt (stdin) ---" in capsys.readouterr().out


def test_printing_on_a_cp950_console_does_not_raise(tmp_path, monkeypatch):
    config(tmp_path, "").joinpath("digest.toml").write_text('topics = ["鴨子 🦆 ⚠ locomotion"]\n', encoding="utf-8")
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp950", errors="strict"))
    assert R.main(["--root", str(tmp_path), "--dry-run"], now=NOW) == 0
    sys.stdout.flush()
    assert b"locomotion" in raw.getvalue()
