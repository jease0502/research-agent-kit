"""The `rak` command.

    rak init [DIR] [--locale en|zh-TW]   create an empty knowledge base (rak.toml, four content folders, vocabulary)
    rak check [--stats|--strict]
    rak build [--serve] [--out dist] [--no-fulltext]
    rak add-paper <arxiv-id> | --doi … | --manual … | --batch FILE
    rak cite-check FILE|DIR ... [--json OUT]

Any subcommand can be preceded by `--root DIR`; without it, rak.toml is looked for from the current directory upwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import __version__, config
from .i18n import tr

# command -> (module, catalog key of its one-line help); the help is looked up when printed, after the locale is set
COMMANDS = {
    "check": ("check", "cli.001"),
    "build": ("build", "cli.002"),
    "add-paper": ("add_paper", "cli.003"),
    "cite-check": ("citation", "cli.004"),
}

VOCAB_SEED = {
    "zh-TW": """# 受控 tag 詞彙表

`rak check` 讀這個檔，用不在清單裡的 tag 會產生警告。格式：``- `tag` — 說明``。

- `example` — 示範用的 tag，換成你自己的
""",
    "en": """# Tag vocabulary

`rak check` reads this file and warns about tags that are not listed. Format: ``- `tag` — description``.

- `example` — a sample tag; replace it with your own
""",
}


def init(target: Path, locale: str = "en") -> int:
    from . import i18n
    i18n.set_locale(locale)
    target.mkdir(parents=True, exist_ok=True)
    cfg = target / config.CONFIG_NAME
    if cfg.exists():
        print(tr("cli.005", a0=cfg), file=sys.stderr)
        return 1
    cfg.write_text(f'site_name = "research kb"\nlocale = "{locale}"\n# source_url = "https://github.com/<you>/<repo>"\n'
                   '# contact = "<email for arXiv/Crossref API etiquette>"\n',
                   encoding="utf-8", newline="\n")
    for d in ("papers", "concepts", "topics", "lessons", "docs"):
        (target / d).mkdir(exist_ok=True)
    voc = target / "docs" / "vocabulary.md"
    if not voc.exists():
        voc.write_text(VOCAB_SEED[locale], encoding="utf-8", newline="\n")
    print(tr("cli.006", a0=target))
    return 0


def usage() -> str:
    lines = [f"rak {__version__}", "", tr("cli.007"), "",
             tr("cli.008")]
    lines += [f"  {k:<14} {tr(v[1])}" for k, v in COMMANDS.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    from . import mdio
    mdio.enable_utf8_output()
    root = None
    if args[:1] == ["--root"]:
        if len(args) < 2:
            print(tr("cli.009"), file=sys.stderr)
            return 2
        root = Path(args[1])
        args = args[2:]
    if not args or args[0] in ("-h", "--help"):
        print(usage())
        return 0 if args else 2
    if args[0] == "--version":
        print(__version__)
        return 0
    cmd, rest = args[0], args[1:]
    if root is not None and cmd != "init" and not root.is_dir():
        print(f"✗ --root {root} is not a directory", file=sys.stderr)
        return 2
    if cmd == "init":
        loc = "en"
        if "--locale" in rest:
            i = rest.index("--locale")
            if i + 1 >= len(rest):
                print("--locale needs en or zh-TW", file=sys.stderr)
                return 2
            loc = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        from . import i18n
        if loc not in i18n.LOCALES:
            print(f"unknown locale {loc!r} (available: {', '.join(i18n.LOCALES)})", file=sys.stderr)
            return 2
        return init(Path(rest[0]) if rest else (root or Path.cwd()), loc)
    if cmd not in COMMANDS:
        print(tr("cli.010", a0=cmd, a1=usage()), file=sys.stderr)
        return 2
    try:
        config.use(config.load(root))
    except (ValueError, OSError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    import importlib
    mod = importlib.import_module(f".{COMMANDS[cmd][0]}", __package__)
    sys.argv = [f"rak {cmd}", *rest]
    return mod.main() or 0


if __name__ == "__main__":
    sys.exit(main())
