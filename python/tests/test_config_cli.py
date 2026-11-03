"""rak.toml 與 CLI：找根目錄、拒絕打錯的欄位與危險字元、init／check 端到端。"""
from __future__ import annotations

import pytest

from rak import config
from rak.cli import main


def test_find_root_walks_up(tmp_path, monkeypatch):
    monkeypatch.delenv("RAK_ROOT", raising=False)
    (tmp_path / "rak.toml").write_text("", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert config.find_root(sub) == tmp_path.resolve()


def test_env_root_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RAK_ROOT", str(tmp_path))
    assert config.find_root(tmp_path / "elsewhere") == tmp_path.resolve()


def test_unknown_field_rejected(tmp_path):
    # 打錯字的欄位安靜被忽略，是「設了卻沒生效」最常見的來源
    (tmp_path / "rak.toml").write_text('sitename = "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="sitename"):
        config.load(tmp_path)


@pytest.mark.parametrize("bad", ['site_name = "a`b"', 'site_name = "${x}"', "source_url = \"javascript:alert(1)\"",
                                 'source_url = "https://x/\\"onload"'])
def test_dangerous_values_rejected(tmp_path, bad):
    (tmp_path / "rak.toml").write_text(bad + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.load(tmp_path)


def test_defaults_point_at_nobody(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.source_url == "" and cfg.contact == ""


def test_user_agent_only_has_contact_when_given(kb):
    from rak import add_paper
    assert "mailto" not in add_paper._user_agent()
    (kb / "rak.toml").write_text('contact = "lab@example.org"\n', encoding="utf-8")
    config.use(config.load(kb))
    assert add_paper._user_agent().endswith("(mailto:lab@example.org)")


def test_cli_init_refuses_overwrite(tmp_path, capsys):
    assert main(["init", str(tmp_path / "kb")]) == 0
    assert main(["init", str(tmp_path / "kb")]) == 1


def test_cli_check_on_empty_kb(tmp_path, capsys):
    main(["init", str(tmp_path / "kb")])
    rc = main(["--root", str(tmp_path / "kb"), "check"])
    out = capsys.readouterr().out
    assert rc == 0 and "0 error" in out


def test_cli_bad_config_is_reported_not_raised(tmp_path, capsys):
    (tmp_path / "rak.toml").write_text('nope = 1\n', encoding="utf-8")
    assert main(["--root", str(tmp_path), "check"]) == 2
    assert "nope" in capsys.readouterr().err


def test_cli_unknown_command(capsys):
    assert main(["frobnicate"]) == 2
