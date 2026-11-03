"""A zh-TW `rak build` must produce the original tool's site, byte for byte (web interface and data).

fixtures/zh_parity/kb_build is a small clean zh-TW knowledge base; expected_build/ is the dist/ that the
ORIGINAL build script and web assets produced for it (vendored KaTeX left out: it is copied verbatim). The
only rewrites applied to that golden output are the four P0 parameterizations listed in the generator's
docstring (build-id variable name, site name, source link, core.js's conditional source link). Everything
else is the original's bytes, so this catches any interface text, data or markup the i18n work changed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "zh_parity"
PY = Path(__file__).resolve().parents[1]


def build(tmp_path: Path, locale: str | None = None) -> Path:
    kb = tmp_path / "kb"
    shutil.copytree(FIX / "kb_build", kb)
    if locale:
        # the fixture's notes use the zh-TW headings, so keep that section preset with another locale
        toml = (kb / "rak.toml").read_text(encoding="utf-8").replace(
            'locale = "zh-TW"', f'locale = "{locale}"\nsections = "zh-TW"')
        (kb / "rak.toml").write_text(toml, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(PY)}
    env.pop("RAK_ROOT", None)
    p = subprocess.run([sys.executable, "-m", "rak", "--root", str(kb), "build", "--no-fulltext", "--commit", "abc1234"],
                       capture_output=True, env=env)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    return kb / "dist"


def files(root: Path) -> dict[str, bytes]:
    return {f.relative_to(root).as_posix(): f.read_bytes().replace(b"\r\n", b"\n")
            for f in root.rglob("*") if f.is_file() and "vendor" not in f.parts and f.name not in (".nojekyll", ".rak-build")}


def test_zh_build_matches_the_original(tmp_path):
    got, want = files(build(tmp_path)), files(FIX / "expected_build")
    assert sorted(got) == sorted(want)
    differ = [k for k in want if got[k] != want[k]]
    assert differ == []


def test_en_build_has_no_tokens_and_english_chrome(tmp_path):
    dist = build(tmp_path, "en")
    for f in dist.rglob("*"):
        if f.is_file() and f.suffix in (".html", ".js", ".css"):
            t = f.read_text(encoding="utf-8")
            assert "__T_web_" not in t and "__HTML_LANG__" not in t and "__ABSTRACT_SECTION__" not in t, f
    assert '<html lang="en">' in (dist / "index.html").read_text(encoding="utf-8")
    assert "<title>Learn — kb</title>" in (dist / "learn.html").read_text(encoding="utf-8")
    # the anchor follows the section preset (zh-TW here, see build()), not the interface locale
    assert 'h2[id="原文摘要"]' in (dist / "assets" / "style.css").read_text(encoding="utf-8")


def test_en_build_javascript_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    dist = build(tmp_path, "en")
    for f in (dist / "assets").glob("*.js"):
        p = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert p.returncode == 0, (f.name, p.stderr)


def test_web_catalog_english_is_safe_in_every_context():
    from rak.i18n_catalog import CATALOG
    bad = set("'\"`\\${}<>")
    for k, e in CATALOG.items():
        if k.startswith("web."):
            assert not (set(e["en"]) & bad), (k, e["en"])
