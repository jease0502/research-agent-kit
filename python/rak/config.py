"""Project settings: the knowledge-base root and `rak.toml`.

The root is the first folder, from the current directory upwards, that contains `rak.toml`; if there is none, the
current directory. `RAK_ROOT` or the CLI's `--root` set it directly.

`rak.toml` fields (all optional):

    site_name  = "My research KB"           # site title and tab name
    source_url = "https://github.com/you/kb" # the "source" link in the site footer; none if not given
    contact    = "you@example.com"          # put in the User-Agent of arXiv / Crossref requests (API etiquette)
    vocabulary = "docs/vocabulary.md"       # the tag allow-list
    locale     = "en"                       # message language: en (default) or zh-TW
    sections   = "en"                       # section-heading preset: en or zh-TW; follows locale if not given
    # or override per note kind:
    # [sections]
    # preset = "en"
    # paper = { required = ["TL;DR", "..."], optional = [] }
    # search = ["TL;DR"]; no_index = ["Abstract"]; abstract = "Abstract"

**No default points at a real person or repository.** Without source_url no link is drawn; without contact only
the package name and version are sent.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from .i18n import tr

CONFIG_NAME = "rak.toml"
PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass
class Config:
    root: Path
    site_name: str = "research kb"
    source_url: str = ""
    contact: str = ""
    vocabulary: str = "docs/vocabulary.md"
    locale: str = "en"
    sections: str = ""                       # preset name; empty = same as locale
    section_overrides: dict = field(default_factory=dict)

    @property
    def vocabulary_path(self) -> Path:
        return self.root / self.vocabulary

    def asset_dir(self, name: str) -> Path:
        """`web` or `templates`: the project's own copy if it has one, otherwise the one shipped with the package."""
        own = self.root / name
        return own if own.is_dir() else PACKAGE_DIR / name


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("RAK_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    return here


def load(root: Path | None = None) -> Config:
    root = (root or find_root()).resolve()
    data: dict = {}
    p = root / CONFIG_NAME
    if p.is_file():
        with open(p, "rb") as f:
            data = tomllib.load(f)
    known = {"site_name", "source_url", "contact", "vocabulary", "locale", "sections"}
    unknown = sorted(set(data) - known)
    if unknown:
        # a misspelled key that is silently ignored is the most common "I set it and nothing happened"
        raise ValueError(tr("config.001", a0=p, a1=unknown, a2=sorted(known)))
    sections = data.pop("sections", "")
    overrides: dict = {}
    if isinstance(sections, dict):
        overrides = dict(sections)
        sections = str(overrides.pop("preset", ""))
    vals = {k: str(v) for k, v in data.items()}
    for k in ("site_name", "source_url"):
        # both values are substituted into HTML and JS strings (template literals too); html.escape does not
        # cover backticks, $ or backslashes
        bad = [c for c in "`$\\'\"<>" if c in vals.get(k, "")]
        if bad:
            raise ValueError(tr("config.002", a0=p, a1=k, a2=bad))
    if vals.get("source_url") and not vals["source_url"].startswith(("https://", "http://")):
        raise ValueError(tr("config.003", a0=p))
    from . import i18n, schema
    if vals.get("locale", "en") not in i18n.LOCALES:
        raise ValueError(f"{p}: locale {vals['locale']!r} is not one of {', '.join(i18n.LOCALES)}")
    preset = sections or vals.get("locale", "en")
    if preset not in schema.SECTION_PRESETS:
        raise ValueError(f"{p}: sections preset {preset!r} is not one of {', '.join(schema.SECTION_PRESETS)}")
    return Config(root=root, sections=str(sections), section_overrides=overrides, **vals)


_current: Config | None = None


def current() -> Config:
    global _current
    if _current is None:
        use(load())
    return _current


def use(cfg: Config) -> Config:
    """Switch the current project (for the CLI's --root and for tests). Also applies the locale, the section
    headings and mdio.ROOT."""
    global _current
    from . import i18n, mdio, schema
    i18n.set_locale(cfg.locale)
    schema.use_sections(cfg.sections or cfg.locale, cfg.section_overrides)   # raises on a bad override
    _current = cfg
    mdio.ROOT = cfg.root
    return cfg
