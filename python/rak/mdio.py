"""Reading and writing markdown files: frontmatter split / parse / output, section split, vocabulary loading.

`add_paper.py`, `build.py` and `check.py` share this layer, so how YAML is parsed and written back has exactly
one implementation.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

import yaml

from . import config, schema
from .i18n import tr

FM_DELIM = "---"

# section headings: `## ` at the start of a line; not inside a code fence (the fence state is tracked line by line)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

_VOCAB_RE = re.compile(r"^\s*-\s+`([a-z0-9][a-z0-9-]*)`")


# --------------------------------------------------------------------------
# reading and writing
# --------------------------------------------------------------------------


def enable_utf8_output() -> None:
    """A Windows console defaults to a legacy code page (cp950 and the like), which garbles non-ASCII output.
    Call once at the start of each script."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def read_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path, text: str) -> None:
    """Always UTF-8 and LF, so CRLF from Windows does not pollute diffs."""
    if not text.endswith("\n"):
        text += "\n"
    Path(path).write_text(text, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[str, str]:
    """(raw frontmatter, body). Without frontmatter, the first is an empty string."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != FM_DELIM:
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_DELIM:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]).lstrip("\n")
    return "", text  # no closing ---: treated as no frontmatter


def coerce(value):
    """Normalize a value parsed from YAML.

    Above all: an unquoted `2026-08-13` is parsed by PyYAML as a datetime.date, which json.dumps cannot
    serialize. It is turned into an ISO string once, at load time, instead of in every caller.
    """
    if isinstance(value, (_dt.datetime,)):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, list):
        return [coerce(v) for v in value]
    if isinstance(value, dict):
        return {k: coerce(v) for k, v in value.items()}
    if isinstance(value, str):
        return value.strip()
    return value


def parse(text: str) -> tuple[dict, str, str | None]:
    """text -> (meta, body, error). An error other than None means the YAML could not be parsed."""
    raw, body = split_frontmatter(text)
    if not raw.strip():
        return {}, body, tr("mdio.001")
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        return {}, body, tr("mdio.002", a0=e)
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        return {}, body, tr("mdio.003", a0=type(meta).__name__)
    return coerce(meta), body, None


def parse_file(path) -> tuple[dict, str, str | None]:
    return parse(read_text(path))


# --------------------------------------------------------------------------
# frontmatter output
# --------------------------------------------------------------------------

# the values of these two fields come from controlled lists; they read better unquoted
_UNQUOTED_FIELDS = {"status", "type"}


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_YAML_SPECIAL = re.compile(r"(?i)^(null|~|true|false|yes|no|on|off|y|n)$|^[-+]?(\d[\d_]*)?(\.\d+)?([eE][-+]?\d+)?$")


def _q(s: str) -> str:
    s = _CONTROL.sub("", str(s))                     # control characters make the file unparsable
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", "")
    return f'"{s}"'


def _bare_ok(s: str) -> bool:
    """Safe to write without quotes: plain token that YAML will not read as null, a bool or a number."""
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", s)) and not _YAML_SPECIAL.match(s)


def _emit(name: str, value, out: list) -> None:
    if isinstance(value, bool):
        out.append(f"{name}: {'true' if value else 'false'}")
    elif isinstance(value, int):
        out.append(f"{name}: {value}")
    elif isinstance(value, dict):
        import json
        out.append(f"{name}: {json.dumps(value, ensure_ascii=False)}")   # JSON is a valid YAML flow mapping
    elif isinstance(value, list):
        if not value:
            out.append(f"{name}: []")
        elif name in schema.BLOCK_LIST_FIELDS:
            out.append(f"{name}:")
            for item in value:
                out.append(f"  - {_q(item)}")
        else:
            items = [x if _bare_ok(str(x)) else _q(x) for x in value]
            out.append(f"{name}: [{', '.join(items)}]")
    elif name in _UNQUOTED_FIELDS and _bare_ok(str(value)):
        out.append(f"{name}: {value}")
    else:
        out.append(f"{name}: {_q(value)}")


def dump_frontmatter(meta: dict, kind: str) -> str:
    """Frontmatter in the schema's field order (without the surrounding `---`).

    Strings are always double-quoted: consistency matters more than looks, and it makes the rule "always quote
    title and arxiv" simply true, with no exceptions to remember.
    """
    order = list(schema.FIELDS[kind].keys())
    out: list[str] = []
    for name in order:
        if name in meta and meta[name] is not None:
            v = meta[name]
            if isinstance(v, str) and not v.strip():
                continue  # an empty string is the same as no value
            _emit(name, v, out)
    for name in meta:  # unknown fields go last; never dropped silently
        if name not in order and meta[name] is not None:
            _emit(name, meta[name], out)
    return "\n".join(out)


def compose(meta: dict, body: str, kind: str) -> str:
    return f"{FM_DELIM}\n{dump_frontmatter(meta, kind)}\n{FM_DELIM}\n\n{body.lstrip()}"


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def split_sections(body: str) -> list[tuple[str, str]]:
    """body -> [(heading, markdown content), ...], in order.

    A `## ` inside a code fence is not a heading. Non-blank content before the first `## ` comes first, with the
    heading "".
    """
    sections: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    current: list[str] | None = None
    fence: str | None = None

    for line in body.splitlines():
        m_fence = _FENCE_RE.match(line)
        if m_fence:
            mark = m_fence.group(1)
            if fence is None:
                fence = mark
            elif line.strip().startswith(fence):
                fence = None

        if fence is None:
            m = _H2_RE.match(line)
            if m:
                current = []
                sections.append((m.group(1).strip(), current))
                continue

        (current if current is not None else preamble).append(line)

    out = []
    if any(l.strip() for l in preamble):
        out.append(("", "\n".join(preamble).strip()))
    out.extend((h, "\n".join(lines).strip()) for h, lines in sections)
    return out


def replace_section(body: str, heading: str, new_content: str) -> str:
    """Replace one section's content and keep everything else verbatim. Returned unchanged if the section is
    not there."""
    secs = split_sections(body)
    if not any(h == heading for h, _ in secs):
        return body
    parts = []
    for h, content in secs:
        if h == "":
            parts.append(content)
            continue
        parts.append(f"## {h}\n\n{new_content.strip() if h == heading else content}")
    return "\n\n".join(p for p in parts if p) + "\n"


_FENCED_RE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def strip_code(body: str) -> str:
    """Remove code fences and inline code, so an example `[[x]]` is not taken for a real link.

    build.py goes through Python-Markdown's InlineProcessor, which never acts inside code; this is the
    equivalent approximation for callers that do not render markdown (check.py, the search index).
    """
    return _INLINE_CODE_RE.sub(" ", _FENCED_RE.sub(" ", body))


def wikilinks(body: str) -> list[str]:
    """Every [[target]] in the body, code removed."""
    return [
        m.group(1).strip()
        for m in schema.WIKILINK_RE.finditer(strip_code(body))
        if m.group(1).strip()
    ]


def has_todo(body: str) -> bool:
    return schema.TODO_MARK in body


def count_todos(body: str) -> int:
    """How many `> TODO` lines. A whole unwritten section and a single gap in a paragraph both count: both are
    holes to fill."""
    return sum(
        1 for line in strip_code(body).splitlines()
        if line.strip().startswith(schema.TODO_MARK)
    )


# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------


def load_vocabulary(path) -> set[str]:
    """The controlled tag set from docs/vocabulary.md.

    The format is a markdown list: ``- `rl` — reinforcement learning``.
    This human-readable file is the source of truth for tags; schema.py only holds structural rules.
    """
    p = Path(path)
    if not p.exists():
        return set()
    return {
        m.group(1)
        for m in (_VOCAB_RE.match(line) for line in read_text(p).splitlines())
        if m
    }


# --------------------------------------------------------------------------
# project paths
# --------------------------------------------------------------------------

# the knowledge-base root: set by rak.toml / RAK_ROOT / --root (see config.py), not where this file is.
# Importing only locates it and does not parse rak.toml (a parse error is reported by the CLI, not at import).
ROOT = config.find_root()


def content_files(kind: str):
    """Every content file of one kind, sorted by slug. Files starting with `_` are ignored."""
    d = ROOT / schema.DIR_OF[kind]
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.md") if not p.name.startswith("_"))


def all_content_files():
    for kind in schema.KINDS:
        for p in content_files(kind):
            yield kind, p


def today() -> str:
    return _dt.date.today().isoformat()
