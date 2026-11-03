"""Messages in English (default) or Traditional Chinese.

    from .i18n import tr
    print(tr("check.012", a0=n))

Every user-facing message lives in `i18n_catalog.CATALOG` as {"en": template, "zh-TW": template}. The zh-TW
templates were generated mechanically from the original Chinese f-strings, so a zh-TW knowledge base gets
byte-identical output (tests compare against the original tool's output). The locale comes from `locale`
in rak.toml; `use()` in config.py sets it. Templates use str.format fields named a0, a1, ... in the order
the original f-string used them.
"""
from __future__ import annotations

LOCALES = ("en", "zh-TW")
_locale = "en"


def set_locale(loc: str) -> None:
    global _locale
    if loc not in LOCALES:
        raise ValueError(f"unknown locale {loc!r} (available: {', '.join(LOCALES)})")
    _locale = loc


def get_locale() -> str:
    return _locale


def text(key: str) -> str:
    """The raw text of a key in the current locale, without str.format (web interface strings)."""
    from .i18n_catalog import CATALOG
    entry = CATALOG[key]
    return entry.get(_locale, entry["en"])


def tr(key: str, **kw) -> str:
    from .i18n_catalog import CATALOG
    entry = CATALOG[key]
    return entry.get(_locale, entry["en"]).format(**kw)
