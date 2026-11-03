from __future__ import annotations

import pytest

from rak import config


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """一個空的知識庫，並把 rak 的目前專案切過去。測試結束後切回原本的設定。"""
    from rak.cli import init
    root = tmp_path / "kb"
    assert init(root) == 0
    monkeypatch.delenv("RAK_ROOT", raising=False)
    saved = config._current
    config.use(config.load(root))
    yield root
    if saved is not None:
        config.use(saved)
    else:
        config._current = None
