"""i18n: the message catalog, the locale switch, configurable section headings, and templates."""
from __future__ import annotations

import string

import pytest

from rak import config, i18n, schema
from rak.i18n_catalog import CATALOG


def fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_both_locales_use_the_same_fields(key):
    e = CATALOG[key]
    assert set(e) == {"en", "zh-TW"}
    assert fields(e["en"]) == fields(e["zh-TW"]), key


def test_english_has_no_cjk():
    import re
    cjk = re.compile(r"[㐀-鿿]")
    assert not [k for k, e in CATALOG.items() if cjk.search(e["en"])]


def test_every_key_used_in_code_exists():
    import re
    from pathlib import Path
    pkg = Path(config.PACKAGE_DIR)
    used = set()
    for f in pkg.glob("*.py"):
        used |= set(re.findall(r"""\btr\(["']([a-z_]+\.\d{3})["']""", f.read_text(encoding="utf-8")))
    used |= {"cli.001", "cli.002", "cli.003", "cli.004"}            # looked up through COMMANDS
    for f in (pkg / "web").rglob("*"):                              # web text is used through __T_web_NNN__ tokens
        if f.suffix in (".html", ".js", ".css"):
            used |= {f"web.{n}" for n in re.findall(r"__T_web_(\d{3})__", f.read_text(encoding="utf-8"))}
    assert used <= set(CATALOG), used - set(CATALOG)
    assert set(CATALOG) - used == set(), set(CATALOG) - used         # no dead entries


def test_locale_switch():
    try:
        i18n.set_locale("zh-TW")
        assert i18n.tr("schema.027", a0="X") == "缺少章節 `## X`"
        i18n.set_locale("en")
        assert i18n.tr("schema.027", a0="X") == "missing section `## X`"
    finally:
        i18n.set_locale("en")
    with pytest.raises(ValueError):
        i18n.set_locale("fr")


def test_section_presets_and_overrides():
    try:
        schema.use_sections("zh-TW")
        assert schema.SECTIONS["paper"]["required"][1] == "問題與動機"
        assert schema.abstract_section() == "原文摘要" and schema.NO_INDEX_SECTIONS == {"原文摘要"}
        schema.use_sections("en", {"paper": {"required": ["TL;DR", "Notes", "Abstract"]}})
        assert schema.SECTIONS["paper"]["required"] == ["TL;DR", "Notes", "Abstract"]
        assert schema.SECTIONS["concept"]["required"][0] == "Definition"
        with pytest.raises(ValueError, match="abstract"):
            schema.use_sections("en", {"paper": {"required": ["TL;DR"]}, "abstract": "Summary"})
        with pytest.raises(ValueError, match="unknown key"):
            schema.use_sections("en", {"papers": {}})
    finally:
        schema.use_sections("en")


def test_check_sections_follows_the_preset():
    try:
        schema.use_sections("en")
        errs, _ = schema.check_sections("concept", ["Definition", "Intuition", "Why it matters"])
        assert errs == ["missing section `## Common misconceptions`"]
        schema.use_sections("zh-TW")
        errs, _ = schema.check_sections("concept", ["一句話定義", "直覺", "為什麼重要", "常見誤解"])
        assert errs == []
    finally:
        schema.use_sections("en")


def test_config_locale_and_sections(tmp_path):
    (tmp_path / "rak.toml").write_text('locale = "zh-TW"\n', encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.locale == "zh-TW" and cfg.sections == ""
    (tmp_path / "rak.toml").write_text('locale = "zh-TW"\nsections = "en"\n', encoding="utf-8")
    assert config.load(tmp_path).sections == "en"           # Chinese messages, English headings
    (tmp_path / "rak.toml").write_text('[sections]\npreset = "en"\npaper = { required = ["TL;DR", "Abstract"] }\n',
                                       encoding="utf-8")
    cfg = config.load(tmp_path)
    assert cfg.sections == "en" and cfg.section_overrides == {"paper": {"required": ["TL;DR", "Abstract"]}}
    for bad in ('locale = "fr"\n', 'sections = "de"\n'):
        (tmp_path / "rak.toml").write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            config.load(tmp_path)


def test_add_paper_template_follows_sections(kb):
    from rak import add_paper
    assert "## Abstract\n\n$abstract" in add_paper.paper_template()
    body = add_paper.render_body("An abstract.")
    errs, _ = schema.check_sections("paper", [h for h in schema.SECTIONS["paper"]["required"]])
    assert errs == [] and "An abstract." in body and "## Problem and motivation" in body


def test_add_paper_template_zh(tmp_path, monkeypatch):
    from rak import add_paper
    from rak.cli import init
    saved = config._current
    try:
        assert init(tmp_path / "kb", "zh-TW") == 0
        config.use(config.load(tmp_path / "kb"))
        tpl = add_paper.paper_template()
        assert "## 問題與動機" in tpl and tpl.rstrip().endswith("## 原文摘要\n\n$abstract")
        assert "受控 tag 詞彙表" in (tmp_path / "kb" / "docs" / "vocabulary.md").read_text(encoding="utf-8")
    finally:
        i18n.set_locale("en")
        schema.use_sections("en")
        config._current = saved


def test_add_paper_template_generated_for_overrides(tmp_path):
    from rak import add_paper
    saved = config._current
    try:
        (tmp_path / "rak.toml").write_text('[sections]\npreset = "en"\npaper = { required = ["TL;DR", "Notes", "Abstract"] }\n',
                                           encoding="utf-8")
        config.use(config.load(tmp_path))
        assert add_paper.paper_template() == "## TL;DR\n\n> TODO\n\n## Notes\n\n> TODO\n\n## Abstract\n\n$abstract\n"
    finally:
        schema.use_sections("en")
        config._current = saved


def test_handoff_points_to_the_skill_not_claude_md():
    for loc in i18n.LOCALES:
        assert "CLAUDE.md" not in CATALOG["add_paper.008"][loc]
        assert "add-paper skill" in CATALOG["add_paper.008"][loc]
