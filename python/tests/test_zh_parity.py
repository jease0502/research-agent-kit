"""A zh-TW knowledge base must get byte-identical `rak check` output to the original Chinese tooling.

fixtures/zh_parity/kb is a small knowledge base with locale = "zh-TW": two good notes and seven broken
ones that exercise most of the validation messages. fixtures/zh_parity/expected/ holds what the ORIGINAL
tool (the scripts rak was extracted from) printed for it, in four modes, with its exit code. It was produced
by running that original code, not by rak, so this compares rak against the original and not against itself.

Line endings are normalized before comparing (the golden files were recorded on Windows; CI runs on Linux).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures" / "zh_parity"
PY = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,args", [("check.txt", []), ("check_stats.txt", ["--stats"]),
                                       ("check_quiet.txt", ["--quiet"]), ("check_strict.txt", ["--strict"])])
def test_rak_check_matches_the_original_byte_for_byte(name, args):
    import os
    env = {**os.environ, "PYTHONPATH": str(PY)}
    env.pop("RAK_ROOT", None)
    p = subprocess.run([sys.executable, "-m", "rak", "--root", str(FIX / "kb"), "check", *args],
                       capture_output=True, env=env)
    got = p.stdout + p.stderr + f"\nexit {p.returncode}\n".encode()
    want = (FIX / "expected" / name).read_bytes()
    assert got.replace(b"\r\n", b"\n") == want.replace(b"\r\n", b"\n")


def test_the_fixture_exercises_errors_warnings_and_notes():
    out = (FIX / "expected" / "check_stats.txt").read_text(encoding="utf-8")   # notes are listed only with --stats
    assert "✗ error (" in out and "! warning (" in out and "· note (" in out
