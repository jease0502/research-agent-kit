"""The knowledge base's schema: the single source of truth.

This module does **no I/O**: data definitions and pure functions only. `add_paper.py`, `build.py` and `check.py`
all take their field specifications from here, so changing the schema means changing this one file (plus the
knowledge base's own instructions and its existing notes, in the same change).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from .i18n import tr

# --------------------------------------------------------------------------
# kinds and folders
# --------------------------------------------------------------------------

KINDS = ("paper", "concept", "topic", "lesson")

DIR_OF = {"paper": "papers", "concept": "concepts", "topic": "topics",
          "lesson": "lessons"}
KIND_OF_DIR = {v: k for k, v in DIR_OF.items()}

PAGE_OF = {"paper": "paper.html", "concept": "concept.html",
           "topic": "topic.html", "lesson": "lesson.html"}

# the file name's stem is the unique id; the frontmatter has no id / slug field
SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------

PAPER_STATUS = ("queued", "reading", "read", "archived")
CONCEPT_TYPES = (
    "concept",
    "algorithm",
    "architecture",
    "benchmark",
    "dataset",
    "metric",
    "hardware",
    "problem",
)
TOPIC_TYPES = ("survey", "thread", "question", "reading-list")
TOPIC_STATUS = ("draft", "living", "done")

# lessons/ are teaching material read step by step; unlike topics/ they have an order and prerequisites.
# track picks the course track, order the position within it.
LESSON_TRACKS = ("foundations", "robot-learning", "engineering", "hands-on")
LESSON_LEVELS = ("beginner", "intermediate", "advanced")
LESSON_STATUS = ("draft", "living", "done")

MAX_TAGS = 5
MAX_SUMMARY = 80  # characters (a CJK summary counts each character)
YEAR_MIN = 1950

# for a paper still `queued`, these fields missing are only a note (no effect on the exit code)
LENIENT_WHEN_QUEUED = {"summary", "tags"}

# --------------------------------------------------------------------------
# field specifications
# --------------------------------------------------------------------------


class Field:
    """The specification of one frontmatter field.

    type: "str" | "int" | "list" | "date"
    slugs: every element of the list must be a valid slug (concepts / related / parents / tags)
    note: what the field is for; documentation only
    """

    __slots__ = ("type", "required", "enum", "slugs", "note")

    def __init__(self, type, required=False, enum=None, slugs=False, note=""):
        self.type = type
        self.required = required
        self.enum = enum
        self.slugs = slugs
        self.note = note


# dicts keep their order, so this is also the frontmatter's output order
PAPER_FIELDS = {
    "title": Field("str", required=True, note="the original title, verbatim; always quoted"),
    "title_zh": Field("str", note="a title in the base's own language, for display"),
    "authors": Field("list", required=True, note="the full author list, from the API, never from memory"),
    "year": Field("int", required=True),
    "venue": Field("str", note='"CoRL 2023" / "arXiv preprint"'),
    "arxiv": Field("str", note="bare id without version; always quoted"),
    "doi": Field("str"),
    "url": Field("str", required=True, note="the canonical source page; a note without a source is worthless"),
    "pdf": Field("str"),
    "code": Field("str", note="the code repository; a high-signal field for RL and robotics"),
    "tags": Field("list", required=True, slugs=True, note=f"controlled vocabulary, at most {MAX_TAGS}"),
    "concepts": Field("list", slugs=True, note="edges to concepts/"),
    "related": Field("list", slugs=True, note="real lineage only"),
    "status": Field("str", required=True, enum=PAPER_STATUS),
    "rating": Field("int", note="1-5, subjective"),
    "summary": Field("str", required=True, note=f"one sentence, at most {MAX_SUMMARY} characters, no line break"),
    "added": Field("date", required=True),
    "updated": Field("date", required=True),
    "aliases": Field("list", note="old slugs and short names, against link rot"),
}

CONCEPT_FIELDS = {
    "title": Field("str", required=True, note="the full English name"),
    "title_zh": Field("str"),
    "aliases": Field("list", note="names in every language the base uses; unique across the base"),
    "type": Field("str", required=True, enum=CONCEPT_TYPES),
    "tags": Field("list", required=True, slugs=True),
    "parents": Field("list", slugs=True, note="broader concepts; a DAG"),
    "related": Field("list", slugs=True, note="concepts at the same level"),
    "summary": Field("str", required=True, note=f"one sentence, at most {MAX_SUMMARY} characters"),
    "added": Field("date", required=True),
    "updated": Field("date", required=True),
}

TOPIC_FIELDS = {
    "title": Field("str", required=True),
    "title_zh": Field("str"),
    "type": Field("str", required=True, enum=TOPIC_TYPES),
    "tags": Field("list", required=True, slugs=True),
    "papers": Field("list", slugs=True, note="ordered: the order is the reading path"),
    "concepts": Field("list", slugs=True),
    "related": Field("list", slugs=True),
    "status": Field("str", required=True, enum=TOPIC_STATUS),
    "summary": Field("str", required=True),
    "added": Field("date", required=True),
    "updated": Field("date", required=True),
}

LESSON_FIELDS = {
    "title": Field("str", required=True),
    "title_zh": Field("str"),
    "track": Field("str", required=True, enum=LESSON_TRACKS, note="course track"),
    "order": Field("int", required=True, note="position within the track; defines the course path"),
    "level": Field("str", required=True, enum=LESSON_LEVELS),
    "minutes": Field("int", note="estimated reading time (minutes)"),
    "prereqs": Field("list", slugs=True, note="lessons to read first"),
    "tags": Field("list", required=True, slugs=True),
    "concepts": Field("list", slugs=True, note="concept cards this lesson teaches"),
    "papers": Field("list", slugs=True, note="papers this lesson cites"),
    "topics": Field("list", slugs=True, note="topic surveys to read next"),
    "related": Field("list", slugs=True),
    "status": Field("str", required=True, enum=LESSON_STATUS),
    "summary": Field("str", required=True),
    "added": Field("date", required=True),
    "updated": Field("date", required=True),
    "aliases": Field("list"),
}

FIELDS = {"paper": PAPER_FIELDS, "concept": CONCEPT_FIELDS, "topic": TOPIC_FIELDS,
          "lesson": LESSON_FIELDS}

# these list fields become graph edges (field name -> edge relation)
EDGE_FIELDS = {
    "paper": {"concepts": "uses", "related": "related"},
    "concept": {"parents": "is_a", "related": "related"},
    "topic": {"papers": "includes", "concepts": "covers", "related": "related"},
    "lesson": {"prereqs": "requires", "concepts": "teaches", "papers": "reads",
               "topics": "leads_to", "related": "related"},
}

# list fields written as a block (one item per line); the others as a flow list [a, b]
BLOCK_LIST_FIELDS = {"authors", "aliases"}

# --------------------------------------------------------------------------
# body sections
# --------------------------------------------------------------------------

# section headings depend on the base's language, so they come as presets: rak.toml's `sections` picks one (by
# default the one matching `locale`), and each note kind can be overridden (see config.py). Each preset also names:
#   search    sections in the weighted search index
#   no_index  sections kept out of the full-text index (a verbatim abstract would swamp queries in other languages)
#   abstract  the section add-paper writes the original abstract into
SECTION_PRESETS = {
    "zh-TW": {
        "paper": {
            "required": [
                "TL;DR",
                "問題與動機",
                "方法",
                "實驗與結果",
                "我的評論",
                "關鍵知識點",
                "延伸閱讀",
                "原文摘要",
            ],
            # the abstract's translation goes before the original abstract, so readers who do not read English
            # see it first; optional, because it is a machine translation and missing it is not an error
            "optional": ["摘要中文翻譯"],
        },
        "concept": {
            "required": ["一句話定義", "直覺", "為什麼重要", "常見誤解"],
            "optional": ["形式化", "代表論文"],
        },
        "topic": {
            "required": ["問題", "路線比較", "我的結論", "閱讀路徑", "未解問題"],
            "optional": [],
        },
        # a lesson's teaching sections cannot have fixed names: each lesson teaches something different, and one
        # set of headings forced on all of them only produces text written to fill a heading. So only the frame
        # (start and end) is fixed and the middle is free: free=True stops check_sections warning about them.
        "lesson": {
            "required": ["這一課要解決什麼", "先備知識", "自我檢核", "下一步"],
            "optional": ["動手做", "常見誤解", "延伸閱讀"],
            "free": True,
        },
        "search": ["TL;DR", "一句話定義", "直覺", "問題", "這一課要解決什麼"],
        # the original abstract is English and repeats the note: not in the full-text index; its translation is
        "no_index": ["原文摘要"],
        "abstract": "原文摘要",
    },
    "en": {
        "paper": {
            "required": [
                "TL;DR",
                "Problem and motivation",
                "Method",
                "Experiments and results",
                "Critique",
                "Key concepts",
                "Further reading",
                "Abstract",
            ],
            "optional": ["Abstract (translated)"],
        },
        "concept": {
            "required": ["Definition", "Intuition", "Why it matters", "Common misconceptions"],
            "optional": ["Formalism", "Key papers"],
        },
        "topic": {
            "required": ["Problem", "Routes compared", "Conclusion", "Reading path", "Open questions"],
            "optional": [],
        },
        "lesson": {
            "required": ["What this lesson solves", "Prerequisites", "Self-check", "Next steps"],
            "optional": ["Hands-on", "Common misconceptions", "Further reading"],
            "free": True,
        },
        "search": ["TL;DR", "Definition", "Intuition", "Problem", "What this lesson solves"],
        "no_index": ["Abstract"],
        "abstract": "Abstract",
    },
}

# the preset in use. use_sections() updates these objects in place, so other modules reading schema.SECTIONS
# always see the current one.
SECTIONS: dict = {}
SEARCH_SECTIONS: set = set()
NO_INDEX_SECTIONS: set = set()
_ABSTRACT = [""]


def use_sections(preset: str = "en", overrides: dict | None = None) -> None:
    """Pick a preset of section headings; overrides can replace required / optional per kind, or search /
    no_index / abstract."""
    import copy
    if preset not in SECTION_PRESETS:
        raise ValueError(f"unknown sections preset {preset!r} (available: {', '.join(SECTION_PRESETS)})")
    p = copy.deepcopy(SECTION_PRESETS[preset])
    for key, val in (overrides or {}).items():
        if key in KINDS:
            if not isinstance(val, dict) or set(val) - {"required", "optional", "free"}:
                raise ValueError(f"sections.{key}: only required / optional / free can be set")
            p[key].update(val)
        elif key in ("search", "no_index"):
            p[key] = list(val)
        elif key == "abstract":
            p[key] = str(val)
        else:
            raise ValueError(f"sections: unknown key {key!r}")
    if p["abstract"] not in p["paper"]["required"] + p["paper"]["optional"]:
        raise ValueError(f"sections: the abstract section {p['abstract']!r} is not a paper section")
    SECTIONS.clear()
    SECTIONS.update({k: p[k] for k in KINDS})
    SEARCH_SECTIONS.clear()
    SEARCH_SECTIONS.update(p["search"])
    NO_INDEX_SECTIONS.clear()
    NO_INDEX_SECTIONS.update(p["no_index"])
    _ABSTRACT[0] = p["abstract"]


def abstract_section() -> str:
    return _ABSTRACT[0]


use_sections("en")

TODO_MARK = "> TODO"

# links in the body: [[slug]] or [[slug|display text]]
WIKILINK_RE = re.compile(r"\[\[([^\]\|\n]+?)(?:\|([^\]\n]+?))?\]\]")

# the size budget of index.json. Over it, the list-view fields belong in a separate file.
# (Split once already, on 2026-10-08: 856 KB at 1,185 notes; see the field groups below. If it is exceeded again,
# rethink the split; do not raise this number.)
INDEX_BUDGET_BYTES = 800 * 1024

# index.json, loaded by every page, holds only these (item / chat / fulltext pages need only the build and the
# search box; list / graph / learn also load list.json)
INDEX_CORE_FIELDS = ("id", "kind", "title", "title_zh", "status", "type")
# the size budget of list.json (set on 2026-10-08, at 456 KB). Over it, build.py returns 1 and says how to split
# next.
LIST_BUDGET_BYTES = 1024 * 1024
# list.json: loaded only by the list (index.html), the graph (graph.html) and the lesson index (learn.html)
INDEX_LIST_FIELDS = ("summary", "tags", "deg", "todo", "year", "venue", "authors_short",
                     "updated", "ft", "ften", "track", "order", "level", "minutes")
# all other fields (url, pdf, arxiv, doi, code, aliases, added, rating, n_authors, prereqs, parents, ...) are only in
# the meta of items/<slug>.json: only single-item pages need them.

# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

SEARCH_WEIGHTS = {
    "aliases": 10,
    "title": 8,
    "tags": 6,
    "summary": 5,
    "section": 3,  # the sections listed in SEARCH_SECTIONS
    "authors": 2,
}

# SEARCH_SECTIONS / NO_INDEX_SECTIONS: see SECTION_PRESETS and use_sections() above.

# --------------------------------------------------------------------------
# slug generation
# --------------------------------------------------------------------------

STOPWORDS = {
    "a", "an", "the", "of", "for", "with", "via", "and", "in", "on", "to",
    "using", "towards", "toward", "is", "are", "we", "our", "from", "by",
    "at", "as", "its", "it", "that", "this", "can", "be", "into", "through",
}

# a short name first ("RT-2: Vision-Language-Action...") is a common convention in robotics and RL papers
SHORTNAME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]{1,14}):\s")


def slugify(text: str, max_words: int = 6, max_len: int = 60) -> str:
    """Squeeze any string into a valid slug."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in text.split() if w]
    kept = [w for w in words if w not in STOPWORDS] or words
    slug = "-".join(kept[:max_words])
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    slug = slug.strip("-")
    return slug


def slug_from_title(title: str) -> str:
    """Paper title -> slug. A title that starts with a short name gets the short name plus the next three content
    words."""
    m = SHORTNAME_RE.match(title.strip())
    if m:
        short = slugify(m.group(1), max_words=3)
        rest = slugify(title[m.end():], max_words=3)
        slug = f"{short}-{rest}".strip("-") if rest else short
        return slug[:60].rstrip("-")
    return slugify(title)


def is_slug(s) -> bool:
    return isinstance(s, str) and bool(SLUG_RE.match(s))


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _typename(v) -> str:
    return type(v).__name__


def validate(kind: str, meta: dict, vocab=None):
    """Validate frontmatter. Returns (errors, warnings, notes), each a list of strings.

    Notes mean "not finished yet", not "wrong", and never affect the exit code: a queued paper just imported by
    add_paper.py has no summary or tags yet, and counting that as a warning would make `--strict` block deploys,
    until nobody reads check's output any more.

    vocab: the allowed tags (read from docs/vocabulary.md by mdio.load_vocabulary). None skips the check.
    """
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    spec = FIELDS[kind]

    # `status: queued` means "in the base, not read yet". Such a note has no summary or tags yet; making that an
    # error would keep check.py red after every import, until nobody looks at it.
    lenient = kind == "paper" and meta.get("status") == "queued"

    for key in meta:
        if key not in spec:
            warnings.append(tr("schema.001", a0=key))

    for name, f in spec.items():
        if name not in meta:
            if f.required:
                if lenient and name in LENIENT_WHEN_QUEUED:
                    notes.append(tr("schema.002", a0=name))
                else:
                    errors.append(tr("schema.003", a0=name))
            continue

        v = meta[name]

        if v is None:
            warnings.append(tr("schema.004", a0=name))
            continue

        if f.type == "str":
            if not isinstance(v, str):
                errors.append(tr("schema.005", a0=name, a1=_typename(v)))
                continue
            if not v.strip():
                if not f.required:
                    warnings.append(tr("schema.006", a0=name))
                elif lenient and name in LENIENT_WHEN_QUEUED:
                    notes.append(tr("schema.007", a0=name))
                else:
                    errors.append(tr("schema.008", a0=name))
            if f.enum and v not in f.enum:
                errors.append(tr("schema.009", a0=name, a1='|'.join(f.enum), a2=v))

        elif f.type == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                errors.append(tr("schema.010", a0=name, a1=_typename(v)))

        elif f.type == "date":
            if not isinstance(v, str) or not DATE_RE.match(v):
                errors.append(tr("schema.011", a0=name, a1=v))

        elif f.type == "list":
            if not isinstance(v, list):
                errors.append(tr("schema.012", a0=name, a1=_typename(v)))
                continue
            if f.required and not v:
                if lenient and name in LENIENT_WHEN_QUEUED:
                    notes.append(tr("schema.013", a0=name))
                else:
                    errors.append(tr("schema.014", a0=name))
            for item in v:
                if not isinstance(item, str):
                    errors.append(tr("schema.015", a0=name, a1=item))
                elif f.slugs and not is_slug(item):
                    errors.append(
                        tr("schema.016", a0=name, a1=item)
                    )

    # --- extra rules per field ---

    if "tags" in meta and isinstance(meta.get("tags"), list):
        tags = meta["tags"]
        if len(tags) > MAX_TAGS:
            warnings.append(tr("schema.017", a0=len(tags), a1=MAX_TAGS))
        if vocab is not None:
            for t in tags:
                if isinstance(t, str) and t not in vocab:
                    warnings.append(
                        tr("schema.018", a0=t)
                    )

    if isinstance(meta.get("summary"), str):
        s = meta["summary"]
        if "\n" in s:
            errors.append(tr("schema.019"))
        if len(s) > MAX_SUMMARY:
            warnings.append(tr("schema.020", a0=len(s), a1=MAX_SUMMARY))

    # a literal None / null in venue: some program formatted a missing value as a string (42 notes with "CoRL None"
    # were cleaned on 2026-10-09; the source was add_paper.guess_venue's f"{name} {yr}"). Refused whichever path
    # wrote it.
    if isinstance(meta.get("venue"), str) and re.search(r"\b(None|null|nan)\b", meta["venue"]):
        errors.append(tr("schema.021", a0=meta['venue']))

    if isinstance(meta.get("year"), int) and not isinstance(meta.get("year"), bool):
        if not (YEAR_MIN <= meta["year"] <= date.today().year + 1):
            errors.append(tr("schema.022", a0=meta['year']))

    if isinstance(meta.get("rating"), int) and not isinstance(meta.get("rating"), bool):
        if not (1 <= meta["rating"] <= 5):
            errors.append(tr("schema.023", a0=meta['rating']))

    if isinstance(meta.get("arxiv"), str) and meta["arxiv"]:
        if re.search(r"v\d+$", meta["arxiv"]):
            warnings.append(tr("schema.024", a0=meta['arxiv']))

    for k in ("url", "pdf", "code"):
        v = meta.get(k)
        if isinstance(v, str) and v and not v.startswith(("http://", "https://")):
            scheme = re.match(r"^\s*([A-Za-z][A-Za-z0-9+.\-]*):", v)
            if scheme:
                # javascript:, data:, ... end up in an href on the site
                errors.append(tr("schema.031", a0=k, a1=scheme.group(1)))
            else:
                warnings.append(tr("schema.025", a0=k, a1=v))

    if isinstance(meta.get("added"), str) and isinstance(meta.get("updated"), str):
        if DATE_RE.match(meta["added"]) and DATE_RE.match(meta["updated"]):
            if meta["updated"] < meta["added"]:
                warnings.append(tr("schema.026"))

    return errors, warnings, notes


def check_sections(kind: str, headings) -> tuple[list[str], list[str]]:
    """Check the body's `## ` sections. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    required = SECTIONS[kind]["required"]
    optional = SECTIONS[kind]["optional"]
    present = list(headings)
    known = set(required) | set(optional)

    for h in required:
        if h not in present:
            errors.append(tr("schema.027", a0=h))

    if not SECTIONS[kind].get("free"):
        for h in present:
            if h not in known:
                warnings.append(tr("schema.028", a0=h))

    seen = set()
    for h in present:
        if h in seen:
            errors.append(tr("schema.029", a0=h))
        seen.add(h)

    # order: only the relative order of the required sections
    order = [h for h in present if h in required]
    if order != [h for h in required if h in order]:
        warnings.append(tr("schema.030"))

    return errors, warnings
