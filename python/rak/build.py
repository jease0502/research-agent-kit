#!/usr/bin/env python3
"""Build papers/, concepts/, topics/ and lessons/ into the static site in dist/.

    rak build            # build into dist/
    rak build --serve    # build, then start a local server
    rak build --out X --commit <sha>

**Do not open dist/index.html through file://**: the pages read JSON with fetch(), which CORS blocks under
file://, leaving a blank page. Always use --serve.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
import subprocess
import time
import sys
import unicodedata
import xml.etree.ElementTree as etree
from collections import Counter, defaultdict
from pathlib import Path

import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.postprocessors import Postprocessor
from markdown.preprocessors import Preprocessor
import markdown.treeprocessors  # noqa: E402  (SafeUrlTree)

from . import check, config, i18n
from . import mdio
from . import schema
from .i18n import tr

WIKI_PATTERN = r"\[\[([^\]\|\n]+?)(?:\|([^\]\n]+?))?\]\]"

# --------------------------------------------------------------------------
# math: hidden first, restored afterwards
# --------------------------------------------------------------------------

_MATH_PH = "zzmathzz{}zz"  # letters and digits only, so markdown leaves it alone
_DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$")
# inline math: the opening $ is followed by a non-space ("$ x $" is not math). A pair whose content starts
# with a digit AND whose closing $ is followed by a digit is money, not math ("US$100 and US$50",
# "NT$100 ... NT$496", "$2.62-$82.30"); see _is_money. Everything else stays math, including "16$\times$",
# "CA$^3$C" and "$\pi$0.5" (measured on a 1,993-note base: narrower rules broke those).
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?=[^\s\$])([^\$\n]+?)\$(?!\$)")


def _is_money(m: re.Match, line: str) -> bool:
    after = line[m.end():m.end() + 1]
    return m.group(1)[:1].isdigit() and after.isdigit()
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_FENCE_LINE = re.compile(r"^\s*(```|~~~)")


class MathStashPre(Preprocessor):
    """Replace $...$ / $$...$$ with placeholders.

    Otherwise the `_` in `$\\pi_\\theta$` is eaten by Python-Markdown as <em>. Nothing inside a code fence is
    touched. Display math over several lines is not supported (rare in notes).
    """

    def __init__(self, md, stash):
        super().__init__(md)
        self.stash = stash

    def run(self, lines):
        out, fence = [], None
        for line in lines:
            m = _FENCE_LINE.match(line)
            if m:
                mark = m.group(1)
                fence = mark if fence is None else (None if line.strip().startswith(fence) else fence)
                out.append(line)
                continue
            if fence is not None or line.startswith("    "):
                out.append(line)
                continue

            def sub(m, display):
                self.stash.append((m.group(1), display))
                return _MATH_PH.format(len(self.stash) - 1)

            parts, last = [], 0
            for cm in _CODE_SPAN.finditer(line):          # leave `code spans` alone
                parts.append((line[last:cm.start()], True))
                parts.append((cm.group(), False))
                last = cm.end()
            parts.append((line[last:], True))
            def inline(s):
                s = _DISPLAY_RE.sub(lambda m: sub(m, True), s)
                return _INLINE_MATH_RE.sub(lambda m: m.group() if _is_money(m, s) else sub(m, False), s)

            line = "".join(inline(s) if outside else s for s, outside in parts)
            out.append(line)
        return out


class MathStashPost(Postprocessor):
    def __init__(self, md, stash):
        super().__init__(md)
        self.stash = stash

    def run(self, text):
        for i, (tex, display) in enumerate(self.stash):
            cls = "math math-display" if display else "math"
            text = text.replace(
                _MATH_PH.format(i), f'<span class="{cls}">{html.escape(tex)}</span>'
            )
        return text


# --------------------------------------------------------------------------
# [[wikilink]]
# --------------------------------------------------------------------------


class WikiLinkInline(InlineProcessor):
    """Turn [[slug]] / [[slug|text]] into links, recording each hit in ctx["sink"].

    An InlineProcessor rather than a regex over the raw markdown, because an inline processor never acts inside
    a code span or code block: a [[x]] in example code must not become a link.
    """

    def __init__(self, pattern, md, ctx):
        super().__init__(pattern, md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        target = m.group(1).strip()
        label = (m.group(2) or "").strip()
        hit = self.ctx["resolve"](target)
        if hit:
            el = etree.Element("a")
            el.set("href", f"{schema.PAGE_OF[hit['kind']]}?id={hit['slug']}")
            el.set("class", f"wl wl-{hit['kind']}")
            el.text = label or hit["title"]
            self.ctx["sink"].append(hit["slug"])
        else:
            el = etree.Element("span")
            el.set("class", "wl broken")
            el.set("title", tr("build.001"))
            el.text = label or target
            self.ctx["broken"].append(target)
        return el, m.start(0), m.end(0)


# videos: `![video](handson/<lesson>/videos/<file>.mp4 "caption")`
# paths are always relative to the base root and under handson/<lesson>/videos/, matching the object paths in the
# media bucket character for character, so the lesson text and the bucket always use the same string and need no
# second mapping table.
VIDEO_PATTERN = (
    r'!\[video\]\(\s*(handson/[A-Za-z0-9._-]+/videos/[A-Za-z0-9._-]+\.(?:mp4|webm))'
    r'(?:\s+"([^"]*)")?\s*\)'
)


class VideoInline(InlineProcessor):
    """Turn ![video](...) into <video> (internal site) or a one-line note (public site).

    `preload="none"`: with several videos on a page, preloading metadata makes the browser request each one, and
    each request needs a fresh signed URL. The video is fetched when the reader presses play.
    """

    def __init__(self, pattern, md, ctx):
        super().__init__(pattern, md)
        self.ctx = ctx

    def handleMatch(self, m, data):
        path, caption = m.group(1), (m.group(2) or "").strip()
        self.ctx["videos"].append(path)
        # phrasing content only (span / video): markdown wraps an inline processor's output in <p>, and a
        # <figure> or <p> inside a <p> is invalid HTML; the browser cuts the outer <p> and the layout breaks.
        # So: span plus CSS display:block.
        if not self.ctx.get("media"):
            el = etree.Element("span")
            el.set("class", "video-missing")
            el.text = tr("build.002", a0=caption or path.rsplit('/', 1)[-1])
            return el, m.start(0), m.end(0)

        box = etree.Element("span")
        box.set("class", "video")
        v = etree.SubElement(box, "video")
        v.set("controls", "controls")
        v.set("preload", "none")          # see the docstring
        v.set("playsinline", "playsinline")
        v.set("src", "/media/" + path)
        if caption:
            v.set("title", caption)
            cap = etree.SubElement(box, "span")
            cap.set("class", "video-cap")
            cap.text = caption
        return box, m.start(0), m.end(0)


SAFE_TAGS = {"br", "sub", "sup", "b", "i", "em", "strong", "kbd", "code", "small", "mark", "u", "s", "del", "ins"}
_BARE_TAG = re.compile(r"</?([A-Za-z]+)\s*/?>")


class SafeHtmlInline(markdown.inlinepatterns.HtmlInlineProcessor):
    """Inline raw HTML: keep a bare allowlisted tag (no attributes), escape everything else."""

    def handleMatch(self, m, data):
        raw = self.backslash_unescape(self.unescape(m.group(1)))
        tag = _BARE_TAG.fullmatch(raw)
        keep = bool(tag) and tag.group(1).lower() in SAFE_TAGS
        return self.md.htmlStash.store(raw if keep else html.escape(raw)), m.start(0), m.end(0)


_URL_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_URL_IGNORED = re.compile(r"[\x00-\x20\x7f]")
SAFE_SCHEMES = {"http", "https", "mailto"}
# attributes whose value a browser loads or follows as a URL
URL_ATTRS = {"href", "src", "poster", "action", "formaction", "background", "data", "cite", "xlink:href",
             "longdesc", "lowsrc", "dynsrc", "manifest", "ping", "codebase", "archive", "icon", "usemap"}
# attributes that run code, hold a document, a URL list, or can restyle the page over the site's own UI
DROP_ATTRS = {"srcdoc", "srcset", "imagesrcset", "style"}


def url_is_safe(value: str) -> bool:
    """Decide on the URL a browser would use: entities decoded (javascript&#58;, &#106;avascript:), then
    tabs, newlines and control characters removed (java<TAB>script:). No scheme (relative, #anchor) is safe."""
    v = value
    for _ in range(3):                              # nested entities (&amp;#58;) as well
        u = html.unescape(v)
        if u == v:
            break
        v = u
    m = _URL_SCHEME.match(_URL_IGNORED.sub("", v))
    return m is None or m.group(1).lower() in SAFE_SCHEMES


class SafeAttrTree(markdown.treeprocessors.Treeprocessor):
    """The last pass over the tree, after attr_list (which lets a note add any attribute: `{ onclick=... }`):
    drop event handlers (on*), DROP_ATTRS, and URL attributes with a scheme other than http(s) or mailto."""

    def run(self, root):
        for el in root.iter():
            for name in list(el.attrib):
                low = name.lower()
                if low.startswith("on") or low in DROP_ATTRS or (low in URL_ATTRS and not url_is_safe(el.attrib[name])):
                    del el.attrib[name]


SafeUrlTree = SafeAttrTree                          # the earlier name


class PaperHomeExtension(Extension):
    def __init__(self, ctx, stash):
        super().__init__()
        self.ctx, self.stash = ctx, stash

    def extendMarkdown(self, md):
        md.preprocessors.register(MathStashPre(md, self.stash), "mathstash", 100)
        md.postprocessors.register(MathStashPost(md, self.stash), "mathrestore", 0)
        # 190 > the built-in link (160) / reference (170), or [[x]] is taken by the reference-link syntax first
        md.inlinePatterns.register(
            WikiLinkInline(WIKI_PATTERN, md, self.ctx), "wikilink", 190
        )
        # 185 is squeezed between two limits:
        #   * **below** backtick (190), or a ![video](...) written in a code span also becomes a player, and a
        #     lesson cannot show the syntax;
        #   * **above** image_link (150), or the built-in image syntax takes it first and produces an <img> whose
        #     src is an mp4: a broken image.
        md.inlinePatterns.register(
            VideoInline(VIDEO_PATTERN, md, self.ctx), "video", 185
        )
        # Raw HTML in a note reaches the page through innerHTML, and add-paper writes API abstracts into
        # notes, so any arXiv submitter controls some of it (stored XSS). Block-level HTML is no longer
        # passed through (it becomes a paragraph), and inline HTML is escaped unless it is a bare,
        # attribute-free tag from SAFE_TAGS.
        if "html_block" in md.preprocessors:
            md.preprocessors.deregister("html_block")
        md.inlinePatterns.register(SafeHtmlInline(markdown.inlinepatterns.HTML_RE, md), "html", 90)
        # priority 0: runs after attr_list (8), so the attributes it adds pass through this check too
        md.treeprocessors.register(SafeAttrTree(md), "safe_attrs", 0)


def make_renderer(ctx):
    stash: list = []
    md = markdown.Markdown(
        extensions=["extra", "sane_lists", "attr_list", PaperHomeExtension(ctx, stash)],
        output_format="html",
    )

    def render(text: str) -> str:
        md.reset()
        stash.clear()
        return md.convert(text)

    return render


# --------------------------------------------------------------------------
# plain text and snippets
# --------------------------------------------------------------------------

_MD_NOISE = re.compile(r"[*_`>#]|!?\[|\]\([^)]*\)|\]\]|\[\[")
_SENT_BREAK = re.compile(r"[。！？；\n]")


def plain(text: str) -> str:
    """markdown -> rough plain text, for search and snippets."""
    text = mdio.strip_code(text)
    text = schema.WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)), text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = _MD_NOISE.sub("", text)
    return " ".join(text.split())


def snippet(section_text: str, target_label: str, target: str, resolve=None) -> str:
    """The sentence that mentions a link, with the link text wrapped in <mark>.

    This turns a concept page's backlinks panel from a bare list into what each paper says about the concept,
    the most valuable part of the page.
    """
    text = mdio.strip_code(section_text)
    m = None
    for cand in schema.WIKILINK_RE.finditer(text):
        if cand.group(1).strip().lower() in (target.lower(), target_label.lower()) or \
                (resolve is not None and resolve(cand.group(1).strip()) == target):
            m = cand
            break
    if not m:
        return ""

    left = text[: m.start()]
    right = text[m.end():]
    lb = max((left.rfind(c) for c in "。！？；\n"), default=-1)
    left = left[lb + 1:][-80:]
    rb = min((i for i in (right.find(c) for c in "。！？；\n") if i >= 0), default=-1)
    right = (right[: rb + 1] if rb >= 0 else right)[:80]

    label = m.group(2) or m.group(1)
    return (
        html.escape(plain(left).strip())
        + f"<mark>{html.escape(label)}</mark>"
        + html.escape(plain(right).strip())
    ).strip()


# --------------------------------------------------------------------------
# search tokenization (tokenize() in web/assets/search.js must match this exactly)
# --------------------------------------------------------------------------

CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_TOKEN_RE = re.compile(rf"[a-z0-9][a-z0-9+#._-]*|[{CJK}]+")
_IS_CJK = re.compile(rf"[{CJK}]")


def tokenize(s: str) -> list[str]:
    """CJK into character bigrams, Latin script into words. Indexing and querying must use the same rules."""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    out: list[str] = []
    for m in _TOKEN_RE.finditer(s):
        t = m.group(0)
        if not _IS_CJK.match(t[0]):
            out.append(t)
            if any(c in t for c in "-._"):
                out.extend(p for p in re.split(r"[-._]", t) if len(p) > 1)
        elif len(t) == 1:
            out.append(t)
        else:
            out.extend(t[i:i + 2] for i in range(len(t) - 1))
    return out


# --------------------------------------------------------------------------
# BibTeX
# --------------------------------------------------------------------------


def surname(name: str) -> str:
    parts = name.replace(",", " ").split()
    return parts[-1] if parts else name


def authors_short(authors: list) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return surname(authors[0])
    if len(authors) == 2:
        return f"{surname(authors[0])} & {surname(authors[1])}"
    return f"{surname(authors[0])} et al."


def bibtex(slug: str, meta: dict) -> str:
    authors = meta.get("authors") or []
    year = meta.get("year", "")
    first = re.sub(r"[^a-z0-9]", "", surname(authors[0]).lower()) if authors else slug
    word = next(
        (w for w in re.findall(r"[A-Za-z]{4,}", meta.get("title", "")) if w.lower() not in schema.STOPWORDS),
        "paper",
    ).lower()
    key = f"{first}{year}{word}"

    fields = [("title", f"{{{meta.get('title', '')}}}"), ("author", " and ".join(authors))]
    if year:
        fields.append(("year", str(year)))
    venue = meta.get("venue", "")
    if venue and venue != "arXiv preprint":
        fields.append(("booktitle", venue))
    if meta.get("arxiv"):
        fields += [("eprint", meta["arxiv"]), ("archivePrefix", "arXiv")]
    if meta.get("doi"):
        fields.append(("doi", meta["doi"]))
    if meta.get("url"):
        fields.append(("url", meta["url"]))

    body = ",\n".join(f"  {k} = {{{v}}}" if k != "title" else f"  title = {v}" for k, v in fields)
    return f"@inproceedings{{{key},\n{body}\n}}"


# --------------------------------------------------------------------------
# graph layout (Fruchterman-Reingold)
# --------------------------------------------------------------------------


def layout(nodes: list, edges: list, ticks: int = 400) -> None:
    """Compute the layout at build time, so the page loads a graph that has already converged.

    No randomness on purpose: initial positions follow a golden-angle spiral, and the push apart on overlap is
    set by the index. The same content always gets the same layout: builds are reproducible, and the graph
    becomes a place one can build a spatial memory of.
    """
    n = len(nodes)
    if n == 0:
        return
    if n == 1:
        nodes[0]["x"] = nodes[0]["y"] = 0.0
        return

    W = H = 1000.0
    k = math.sqrt(W * H / n)
    rep, spring, damp, center = k * k, 0.06, 0.85, 0.002
    maxd2 = (6 * k) ** 2
    golden = math.pi * (3 - math.sqrt(5))

    pos = []
    for i in range(n):
        r = k * math.sqrt(i + 0.5)
        a = i * golden
        pos.append([r * math.cos(a), r * math.sin(a), 0.0, 0.0])

    lens = {"is_a": 0.6, "includes": 0.9, "uses": 1.0, "covers": 1.0,
            "related": 1.3, "mentions": 1.2}
    ee = [(e["s"], e["t"], lens.get(e["r"], 1.0)) for e in edges]

    alpha = 1.0
    for _ in range(ticks):
        fx = [0.0] * n
        fy = [0.0] * n
        for i in range(n):
            xi, yi = pos[i][0], pos[i][1]
            for j in range(i + 1, n):
                dx, dy = xi - pos[j][0], yi - pos[j][1]
                d2 = dx * dx + dy * dy
                if d2 > maxd2:
                    continue
                if d2 < 1e-4:  # overlap: the index sets the direction, which keeps it deterministic
                    dx, dy = math.cos(i * 2.399) * 0.01, math.sin(i * 2.399) * 0.01
                    d2 = 1e-4
                d = math.sqrt(d2)
                f = rep / d2
                ux, uy = dx / d * f, dy / d * f
                fx[i] += ux; fy[i] += uy
                fx[j] -= ux; fy[j] -= uy

        for s, t, ln in ee:
            dx, dy = pos[t][0] - pos[s][0], pos[t][1] - pos[s][1]
            d = math.hypot(dx, dy) or 1e-3
            f = spring * (d - k * ln)
            ux, uy = dx / d * f, dy / d * f
            fx[s] += ux; fy[s] += uy
            fx[t] -= ux; fy[t] -= uy

        for i in range(n):
            p = pos[i]
            p[2] = (p[2] + (fx[i] - p[0] * center * n) * alpha) * damp
            p[3] = (p[3] + (fy[i] - p[1] * center * n) * alpha) * damp
            sp = math.hypot(p[2], p[3])
            if sp > 12:
                p[2] *= 12 / sp
                p[3] *= 12 / sp
            p[0] += p[2]
            p[1] += p[3]
        alpha *= 0.985
        if alpha < 0.008:
            break

    span = max(max(abs(p[0]) for p in pos), max(abs(p[1]) for p in pos), 1e-6)
    for node, p in zip(nodes, pos):
        node["x"] = round(p[0] / span, 4)
        node["y"] = round(p[1] / span, 4)


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def dump(path: Path, obj) -> int:
    """Deterministic output: sorted, non-ASCII not escaped (escaping triples the size of CJK text), minimal
    separators."""
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(text.encode("utf-8"))


# --------------------------------------------------------------------------
# full text (fulltext-zh/)
# --------------------------------------------------------------------------
#
# fulltext-zh/ is not under version control (see .gitignore), so **a GitHub Pages build does not have it**, and
# the public site has no full text. That is deliberate, not a bug. A deployment that uploads the local folder
# (for example `gcloud run deploy --source .`) carries it along, as long as its ignore files do not exclude it.
#
# One file per paper and language: a translated summary is often 20-40 KB and the English original larger;
# putting them all in index.json would make someone who only wants the list download tens of MB first.

FULLTEXT_DIR = "fulltext-zh"
_EN_SUFFIX = ".en.md"
_SRC_COMMENT = re.compile(r"^<!--.*?-->\s*", re.S)


def fulltext_slugs() -> tuple[set[str], set[str]]:
    """(slugs with a translated summary, slugs with the English original). Two empty sets if the folder is
    missing."""
    d = mdio.ROOT / FULLTEXT_DIR
    if not d.is_dir():
        return set(), set()
    zh = {p.stem for p in d.glob("*.md") if not p.name.endswith(_EN_SUFFIX)}
    en = {p.name[: -len(_EN_SUFFIX)] for p in d.glob(f"*{_EN_SUFFIX}")}
    return zh, en


def write_fulltext(data_dir: Path, render, ctx, zh: set[str], en: set[str]) -> int:
    """Render into data/ft/<slug>.{zh,en}.json; returns the total bytes.

    The renderer is the one the notes use, so [[wikilinks]] point at pages of the site and math and code fences
    behave the same. **Call it only after the edges are collected**, or the [[...]] in the full text would enter
    the knowledge graph and flood it.
    """
    src = mdio.ROOT / FULLTEXT_DIR
    total = 0
    for slug in sorted(zh):
        ctx["sink"], ctx["broken"] = [], []
        text = (src / f"{slug}.md").read_text(encoding="utf-8")
        total += dump(data_dir / "ft" / f"{slug}.zh.json", {"html": render(text)})
    for slug in sorted(en):
        ctx["sink"], ctx["broken"] = [], []
        text = (src / f"{slug}{_EN_SUFFIX}").read_text(encoding="utf-8")
        # the first line is <!-- source: ... -->, which markdown would put on the page as it is
        total += dump(
            data_dir / "ft" / f"{slug}.en.json",
            {"html": render(_SRC_COMMENT.sub("", text))},
        )
    return total



# a commit SHA is hexadecimal, so **it starts with a digit 10/16 = 62.5 % of the time**. A template once had
# `<script>window.__BUILD__ = "__BUILD__";</script>`: the placeholder stood both for a variable name and for a
# string value, so a SHA starting with a digit produced `window.1d660bd = "1d660bd"`, a syntax error. The whole
# inline script died, BUILD was undefined, the first getData() threw a ReferenceError, and the page stayed on
# "loading..." for good. The first two deploys happened to draw SHAs starting with a letter, so nobody noticed.
#
# This check makes sure the commit appears only in safe places: inside quotes, or after ?v=.
_SAFE_BEFORE = ('"', "'", "=", "/", "-", " ", "`")


def _assert_build_id_safe(src, text: str, commit: str) -> None:
    """The commit SHA may only be a value, never in an identifier position."""
    for i in _find_all(text, commit):
        before = text[i - 1] if i else ""
        after = text[i + len(commit)] if i + len(commit) < len(text) else ""
        if before == "." or (before not in _SAFE_BEFORE and before.isidentifier()):
            raise SystemExit(
                tr("build.003", a0=src, a1=text[max(0, i - 24):i + len(commit) + 8])
            )
        if after.isalnum() or after == "_":
            raise SystemExit(tr("build.004", a0=src))


def _find_all(hay: str, needle: str):
    i = hay.find(needle)
    while i != -1:
        yield i
        i = hay.find(needle, i + 1)

_WEB_TOKEN = re.compile(r"__T_web_(\d{3})__")
HTML_LANG = {"en": "en", "zh-TW": "zh-Hant"}


def _site_subst(text: str) -> str:
    """Fill the bundled web assets' placeholders.

    __T_web_NNN__ -> the interface text in the configured locale (i18n catalog key web.NNN). Done first,
    because some of those texts contain __SITE_NAME__ themselves.
    __HTML_LANG__ -> the page language; __ABSTRACT_SECTION__ -> the abstract heading (a CSS anchor).
    __SITE_NAME__ / __SOURCE_URL__ -> from rak.toml.
    A project's own web/ folder has no tokens, so this changes nothing there.
    """
    cfg = config.current()
    text = _WEB_TOKEN.sub(lambda m: i18n.text(f"web.{m.group(1)}"), text)
    text = text.replace("__HTML_LANG__", HTML_LANG[i18n.get_locale()])
    text = text.replace("__ABSTRACT_SECTION__", schema.abstract_section())
    return (text.replace("__SITE_NAME__", html.escape(cfg.site_name))
                .replace("__SOURCE_URL__", html.escape(cfg.source_url, quote=True)))


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=mdio.ROOT, capture_output=True, text=True, timeout=5,
        )
        sha = out.stdout.strip()
    except Exception:
        sha = ""
    # the build id outside git. Not a common word such as "dev": _assert_build_id_safe would find it inside words
    # like "device" in the web files and complain (it did, on the first build of a base that was not in git).
    return sha or f"nogit{int(time.time())}"


# the chat page exists only in the local preview: it starts a local process from user input, and published on a
# public site it would be a remote-execution hole.
CHAT_FILES = {"chat.html", "assets/chat.js"}


def build(out_dir: Path, commit: str, with_fulltext: bool = True,
          with_chat: bool = False, media: bool = False) -> int:
    rep = check.Report()
    items = check.load_all(rep)
    if items and not rep.errors:
        # the same checks as `rak check`: publishing content it rejects (an unquoted arxiv id that YAML
        # turned into a different number, a string year that crashes sorting) is how a site goes wrong
        vocab = mdio.load_vocabulary(config.current().vocabulary_path)
        amap0 = check.build_alias_map(items, rep)
        check.check_items(items, amap0, vocab, rep)
        check.check_parent_cycles(items, amap0, rep)
    if rep.errors:
        print(tr("build.005"), file=sys.stderr)
        for where, msg in rep.errors:
            print(f"  {where}: {msg}", file=sys.stderr)
        return 1
    if not items:
        print(tr("build.006"), file=sys.stderr)
        return 1

    amap = check.build_alias_map(items, rep)

    def resolve(target):
        hit = check.resolve(target, items, amap)
        if hit is None:
            return None
        return {"slug": hit, "kind": items[hit]["kind"],
                "title": items[hit]["meta"].get("title", hit)}

    # `media`: only the internal site has /media, the public one does not; the same deliberate asymmetry as the
    # full text. `videos` collects every referenced video path, printed at the end of the build, to check the
    # media manifest for missing uploads.
    ctx = {"resolve": resolve, "sink": [], "broken": [],
           "media": media, "videos": []}
    render = make_renderer(ctx)

    # ---- render and collect edges ----
    for slug, it in items.items():
        meta, kind = it["meta"], it["kind"]
        it["rendered"] = []
        it["broken"] = []
        body_links: dict[str, str] = {}  # target slug -> snippet

        for heading, content in it["sections"]:
            if not heading:
                continue
            ctx["sink"], ctx["broken"] = [], []
            html_out = render(content)
            it["rendered"].append({"h": heading, "a": schema.slugify(heading) or heading,
                                   "html": html_out})
            for t in ctx["sink"]:
                if t != slug and t not in body_links:
                    body_links[t] = snippet(content, items[t]["meta"].get("title", t), t,
                                            lambda x: (resolve(x) or {}).get("slug"))
            it["broken"].extend(ctx["broken"])

        edges: dict[str, dict] = {}
        for field, rel in schema.EDGE_FIELDS[kind].items():
            for target in meta.get(field) or []:
                hit = check.resolve(target, items, amap)
                if hit and hit != slug:
                    edges.setdefault(hit, {"rel": rel, "via": "meta", "ctx": ""})
        for target, ctx_snip in body_links.items():
            if target in edges:
                edges[target]["via"] = "both"
                edges[target]["ctx"] = edges[target]["ctx"] or ctx_snip
            else:
                edges[target] = {"rel": "mentions", "via": "body", "ctx": ctx_snip}
        it["edges"] = edges

    # ---- backlinks ----
    backlinks: dict[str, list] = defaultdict(list)
    for slug, it in items.items():
        for target, e in it["edges"].items():
            backlinks[target].append({
                "id": slug, "kind": it["kind"],
                "title": it["meta"].get("title", slug),
                "rel": e["rel"], "via": e["via"], "ctx": e["ctx"],
            })
    for lst in backlinks.values():
        lst.sort(key=lambda b: (b["kind"], b["id"]))

    degree = Counter()
    for slug, it in items.items():
        degree[slug] += len(it["edges"])
        for target in it["edges"]:
            degree[target] += 1

    # ---- index.json ----
    ft_zh, ft_en = fulltext_slugs() if with_fulltext else (set(), set())
    entries = []
    for slug, it in sorted(items.items()):
        meta, kind = it["meta"], it["kind"]
        e = {
            "id": slug, "kind": kind,
            "title": meta.get("title", slug),
            "summary": meta.get("summary", ""),
            "tags": meta.get("tags") or [],
            "deg": degree[slug],
            "todo": it.get("todos", mdio.count_todos(it["body"])),
            "added": meta.get("added", ""), "updated": meta.get("updated", ""),
        }
        for k in ("title_zh", "aliases", "status", "type", "venue", "year",
                  "rating", "arxiv", "url", "code", "doi", "pdf",
                  "track", "order", "level", "minutes", "prereqs"):
            if meta.get(k):
                e[k] = meta[k]
        if kind == "paper":
            authors = meta.get("authors") or []
            e["authors_short"] = authors_short(authors)
            e["n_authors"] = len(authors)
        if kind == "concept" and meta.get("parents"):
            e["parents"] = meta["parents"]
        # full-text flags: the page uses them to decide whether to show the links to the translation and the
        # English original. 1 instead of true keeps index.json a little smaller (3 bytes per entry)
        if slug in ft_zh:
            e["ft"] = 1
        if slug in ft_en:
            e["ften"] = 1
        entries.append(e)

    counts = Counter(it["kind"] for it in items.values())
    tag_counts = Counter(t for it in items.values() for t in (it["meta"].get("tags") or []))
    year_counts = Counter(
        it["meta"]["year"] for it in items.values() if it["meta"].get("year")
    )
    broken_total = sum(len(it["broken"]) for it in items.values())

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / BUILD_MARKER).write_text("written by rak build; rak build may delete and rebuild this folder\n",
                                        encoding="utf-8", newline="\n")
    data = out_dir / "data"
    # index.json holds only the core fields; the list fields go to list.json (loaded only by the list, the graph
    # and the lesson index); the full entry stays in the meta of items/<slug>.json. core.js's getListIndex() merges
    # the two on the page.
    def pick(e, fields):
        return {k: e[k] for k in fields if k in e}

    index_size = dump(data / "index.json", {
        "build": {"id": commit, "counts": dict(counts), "broken": broken_total},
        "items": [pick(e, schema.INDEX_CORE_FIELDS) for e in entries],
        "tags": sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "years": sorted(year_counts.items()),
    })
    list_size = dump(data / "list.json", {
        "build": commit,
        "items": [{"id": e["id"], **pick(e, schema.INDEX_LIST_FIELDS)} for e in entries],
    })

    # ---- items/<slug>.json ----
    by_id = {e["id"]: e for e in entries}
    for slug, it in items.items():
        outlinks = [
            {"id": t, "kind": items[t]["kind"], "title": items[t]["meta"].get("title", t),
             "rel": e["rel"], "via": e["via"]}
            for t, e in it["edges"].items()
        ]
        payload = {
            "id": slug, "kind": it["kind"], "meta": by_id[slug],
            "sections": it["rendered"],
            "outlinks": outlinks,
            "backlinks": backlinks.get(slug, []),
            "broken": sorted(set(it["broken"])),
        }
        if it["kind"] == "paper":
            payload["bibtex"] = bibtex(slug, it["meta"])
            payload["authors"] = it["meta"].get("authors") or []
        dump(data / "items" / f"{slug}.json", payload)

    # ---- graph.json ----
    order = [e["id"] for e in entries]
    idx = {s: i for i, s in enumerate(order)}
    nodes = [{
        "i": i, "id": s, "k": items[s]["kind"][0],
        "l": items[s]["meta"].get("title_zh") or items[s]["meta"].get("title", s),
        "tg": items[s]["meta"].get("tags") or [],
        "st": items[s]["meta"].get("status", ""),
        "deg": degree[s],
    } for i, s in enumerate(order)]
    if any(items[s]["meta"].get("year") for s in order):
        for node, s in zip(nodes, order):
            if items[s]["meta"].get("year"):
                node["yr"] = items[s]["meta"]["year"]

    seen_edge = set()
    gedges = []
    for slug, it in sorted(items.items()):
        for target, e in it["edges"].items():
            key = (idx[slug], idx[target])
            if key in seen_edge or (key[1], key[0]) in seen_edge:
                continue
            seen_edge.add(key)
            gedges.append({"s": key[0], "t": key[1], "r": e["rel"]})
    gedges.sort(key=lambda e: (e["s"], e["t"], e["r"]))

    layout(nodes, gedges)
    dump(data / "graph.json", {
        "nodes": nodes, "edges": gedges,
        "rels": sorted({e["r"] for e in gedges}),
    })

    # ---- search.json ----
    docs, terms = [], defaultdict(Counter)
    W = schema.SEARCH_WEIGHTS
    for i, e in enumerate(entries):
        slug = e["id"]
        it = items[slug]
        # the field order matches the D_* constants in search.js one to one
        docs.append([slug, it["kind"][0], e["title"], e["summary"],
                     e.get("year", 0), e["tags"], e.get("aliases") or [],
                     e.get("title_zh", "")])
        fields = [
            (W["title"], f"{e['title']} {e.get('title_zh', '')}"),
            (W["aliases"], " ".join(e.get("aliases") or [])),
            (W["tags"], " ".join(e["tags"])),
            (W["summary"], e["summary"]),
            (W["authors"], " ".join(surname(a) for a in (it["meta"].get("authors") or []))),
        ]
        for heading, content in it["sections"]:
            if heading in schema.SEARCH_SECTIONS:
                fields.append((W["section"], plain(content)))
        for weight, text in fields:
            if text and text.strip():
                for tok in tokenize(text):
                    terms[tok][i] += weight

    dump(data / "search.json", {
        "v": 1, "n": len(docs), "docs": docs,
        "terms": {t: sorted(c.items()) for t, c in sorted(terms.items())},
    })

    # ---- fulltext.json ----
    dump(data / "fulltext.json", {
        "docs": {
            slug: plain(
                " ".join(
                    c for h, c in it["sections"] if h not in schema.NO_INDEX_SECTIONS
                )
            )
            for slug, it in sorted(items.items())
        }
    })

    # ---- ft/<slug>.{zh,en}.json ----
    ft_bytes = write_fulltext(data, render, ctx, ft_zh, ft_en) if with_fulltext else 0

    # ---- INDEX.md ----
    write_index_md(items, entries, degree)

    # ---- web/ → dist/ ----
    web = config.current().asset_dir("web")
    if not web.exists():
        print(tr("build.007"), file=sys.stderr)
    else:
        for src in web.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(web).as_posix()
            # the chat page exists only in the local preview: it starts a local process from user input, and
            # published on a public site it would be a remote-execution hole.
            if rel in CHAT_FILES and not with_chat:
                continue
            dst = out_dir / src.relative_to(web)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix in (".html", ".js", ".css"):
                text = _site_subst(src.read_text(encoding="utf-8")).replace("__BUILD__", commit)
                _assert_build_id_safe(src, text, commit)
                dst.write_text(text, encoding="utf-8", newline="\n")
            else:
                shutil.copy2(src, dst)
        (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    # ---- handson/ figures and small logs -> dist/handson/ ----
    # hands-on lessons cite measured figures as ![](handson/<lesson>/figs/x.png); only small files under figs/ and
    # logs/ are copied (checkpoints, npz and gif are kept out by .gitignore, and once more here).
    handson = mdio.ROOT / "handson"
    if handson.exists():
        n_copied = 0
        for src in handson.rglob("*"):
            if src.is_dir():
                continue
            # figs/ may have subfolders (figs/openloop-*/traj_79.png); logs/ only its direct files: subfolders
            # there hold training output (rsl_rl and the like) the pages never use.
            rel = src.relative_to(handson).parts
            if not (len(rel) >= 3 and (rel[1] == "figs" or (rel[1] == "logs" and len(rel) == 3))):
                continue
            if src.suffix in (".pkl", ".pt", ".npz", ".gif", ".mp4") or src.stat().st_size > 400 * 1024:
                continue
            dst = out_dir / src.relative_to(mdio.ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_copied += 1
        print(tr("build.008", a0=n_copied))

    if ctx["videos"]:
        uniq = sorted(set(ctx["videos"]))
        where = tr("build.009") if media else tr("build.010")
        print(tr("build.011", a0=len(uniq), a1=where))
        for v in uniq:
            print(f"    {v}")
        if media:
            print(tr("build.012"))

    print(
        tr("build.013", a0=out_dir.name, a1=commit, a2=counts['paper'], a3=counts['concept'], a4=counts['topic'], a5=counts['lesson'], a6=len(gedges), a7=broken_total)
    )
    if ft_zh or ft_en:
        print(
            tr("build.014", a0=len(ft_zh), a1=len(ft_en), a2=ft_bytes // 1024 // 1024)
        )
    elif with_fulltext:
        print(tr("build.015"))
    return check_budgets(index_size, list_size)


def check_budgets(index_size: int, list_size: int) -> int:
    """The size guard for index.json / list.json. Over budget returns 1 (which fails the deploy and check
    workflows). The fix is in the message; do not raise the budget to turn it green, which loosens the guard."""
    print(
        tr("build.016", a0=index_size // 1024, a1=schema.INDEX_BUDGET_BYTES // 1024, a2=list_size // 1024, a3=schema.LIST_BUDGET_BYTES // 1024)
    )
    rc = 0
    if index_size > schema.INDEX_BUDGET_BYTES:
        print(
            tr("build.017", a0=index_size // 1024, a1=schema.INDEX_BUDGET_BYTES // 1024),
            file=sys.stderr,
        )
        rc = 1
    if list_size > schema.LIST_BUDGET_BYTES:
        print(
            tr("build.018", a0=list_size // 1024, a1=schema.LIST_BUDGET_BYTES // 1024),
            file=sys.stderr,
        )
        rc = 1
    return rc


def write_index_md(items: dict, entries: list, degree: Counter) -> None:
    """Write INDEX.md: one line per item, a table of contents for Claude Code instead of globbing hundreds of
    files.

    The only generated file that is committed.
    """
    lines = [
        tr("build.019"),
        tr("build.020"),
        "",
        tr("build.021"),
        tr("build.022"),
        "",
    ]

    papers = [e for e in entries if e["kind"] == "paper"]
    lines += [tr("build.023", a0=len(papers)), "",
              tr("build.024"),
              "|---|---|---|---|---|---|"]
    for e in sorted(papers, key=lambda x: (-(x.get("year") or 0), x["id"])):
        lines.append(
            f"| [{e['id']}](papers/{e['id']}.md) | {e.get('year', '')} | "
            f"{md_cell(e['title'])} | {md_cell(e['summary'])} | "
            f"{', '.join(e['tags'])} | {e.get('status', '')} |"
        )

    concepts = [e for e in entries if e["kind"] == "concept"]
    lines += ["", tr("build.025", a0=len(concepts)), "",
              tr("build.026"), "|---|---|---|---|---|"]
    for e in sorted(concepts, key=lambda x: -degree[x["id"]]):
        lines.append(
            f"| [{e['id']}](concepts/{e['id']}.md) | {e.get('type', '')} | "
            f"{md_cell(e['summary'])} | {', '.join(e.get('aliases') or [])} | "
            f"{degree[e['id']]} |"
        )

    topics = [e for e in entries if e["kind"] == "topic"]
    if topics:
        lines += ["", tr("build.027", a0=len(topics)), "",
                  tr("build.028"), "|---|---|---|---|---|"]
        for e in sorted(topics, key=lambda x: x["id"]):
            n = len(items[e["id"]]["meta"].get("papers") or [])
            lines.append(
                f"| [{e['id']}](topics/{e['id']}.md) | {e.get('type', '')} | "
                f"{md_cell(e['summary'])} | {n} | {e.get('status', '')} |"
            )

    mdio.write_text(mdio.ROOT / "INDEX.md", "\n".join(lines))


def md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


BUILD_MARKER = ".rak-build"
PROTECTED_DIRS = ("papers", "concepts", "topics", "lessons", "docs", "templates", "web", "handson",
                  "fulltext-zh", "media", ".git")


def out_dir_problem(out_dir: Path, root: Path) -> str | None:
    """Why `rak build` must not delete out_dir before building into it, or None.

    The output folder is deleted and rebuilt, so `--out papers` or `--out .` would destroy notes. Only an
    empty folder, a missing one, or one that carries the marker file a previous `rak build` wrote may go.
    """
    if out_dir == root or root.is_relative_to(out_dir):
        return "it is the knowledge base or contains it"
    if out_dir.is_relative_to(root) and out_dir.relative_to(root).parts[0] in PROTECTED_DIRS:
        return "it is (inside) a content folder"
    if (out_dir / "rak.toml").exists():
        return "it holds a rak.toml"
    if out_dir.exists() and any(out_dir.iterdir()) and not (out_dir / BUILD_MARKER).is_file():
        return f"it is not empty and has no {BUILD_MARKER} marker from a previous rak build; delete it yourself"
    return None


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def request_problem(headers, port: int, post: bool) -> tuple[int, str] | None:
    """Why a request to the local server must be refused, or None.

    Binding to loopback is not enough: a page on any site can make the browser send a request to
    127.0.0.1 (CSRF), and DNS rebinding makes a foreign name resolve to 127.0.0.1 so that the page can
    read the responses. So every request must name this server in Host, a request carrying an Origin must
    come from this server, and /api/ask (which starts a local process) must be a JSON request, which a
    page on another origin cannot send without a CORS preflight that this server never approves.
    """
    allowed = {f"{h}:{port}" for h in LOOPBACK_HOSTS}
    host = (headers.get("Host") or "").strip().lower()
    if host not in allowed:
        return 403, "forbidden host"
    origin = headers.get("Origin")
    if origin is not None and origin.strip().lower() not in {f"http://{h}" for h in allowed}:
        return 403, "forbidden origin"
    if post:
        ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return 415, "application/json required"
    return None


def serve(directory: Path, port: int = 8000) -> None:
    """The local preview server, plus the Q&A bridge under /api/*.

    **Loopback only** (127.0.0.1 and ::1): /api/ask starts a local process from user input, and binding 0.0.0.0
    would offer that to the whole network. Do not change this.
    """
    import functools
    import http.server
    import json as jsonlib
    import socket
    import threading

    from . import chat

    class Handler(http.server.SimpleHTTPRequestHandler):
        def _refused(self, post: bool) -> bool:
            problem = request_problem(self.headers, port, post)
            if problem:
                self.send_error(problem[0], problem[1])
                return True
            return False

        def do_GET(self):
            if self._refused(False):
                return
            if self.path.split("?")[0] == "/api/health":
                return self._send_json(chat.status())
            return super().do_GET()

        def do_HEAD(self):
            if self._refused(False):
                return
            return super().do_HEAD()

        def do_POST(self):
            if self._refused(True):
                return
            if self.path.split("?")[0] != "/api/ask":
                return self.send_error(404, "File not found")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                question = (jsonlib.loads(self.rfile.read(n) or b"{}").get("q") or "").strip()
            except Exception:
                return self.send_error(400, "bad request")
            if not question:
                return self.send_error(400, "empty question")

            # SSE: a query takes seconds to minutes; without streaming the reader would think it hung
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for ev in chat.ask(question):
                    payload = jsonlib.dumps(ev, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # the reader closed the tab

        def _send_json(self, obj):
            body = jsonlib.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    Handler.extensions_map[".json"] = "application/json"
    handler = functools.partial(Handler, directory=str(directory))
    # bind both loopbacks. On Windows, browsers resolve localhost to ::1 first, and ::1:8000 is often taken by
    # something else (WSL's wslrelay, Docker Desktop's port proxy). Bound to 127.0.0.1 only, `localhost:8000`
    # sometimes reaches us and sometimes that forwarder: the symptom is an intermittent "page does nothing", with
    # nothing in the server log, because the request never arrived.
    #
    # This is still loopback only: /api/ask starts a local process from user input, and that must not be offered
    # to the network.
    servers = []
    for family, addr in (
        (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::1", port)),
    ):
        klass = type(
            "S", (http.server.ThreadingHTTPServer,),
            {"address_family": family, "daemon_threads": True},
        )
        try:
            servers.append(klass(addr, handler))
        except OSError as e:
            print(tr("build.029", a0=addr[0], a1=port, a2=e.strerror or e))

    if not servers:
        print(tr("build.030", a0=port))
        return

    st = chat.status()
    where = " / ".join(
        f"http://{'[::1]' if s.address_family == socket.AF_INET6 else '127.0.0.1'}:{port}"
        for s in servers
    )
    print(tr("build.031", a0=chr(10), a1=where))
    print(tr("build.032", a0=tr('build.040') + st['cmd'] if st['ok'] else st['hint'], a1=chr(10)))

    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        print(tr("build.033", a0=chr(10)))


def main() -> int:
    mdio.enable_utf8_output()
    ap = argparse.ArgumentParser(description=tr("build.034"))
    ap.add_argument("--out", default="dist")
    ap.add_argument("--commit", default="", help=tr("build.035"))
    ap.add_argument("--serve", action="store_true", help=tr("build.036"))
    ap.add_argument("--chat", action="store_true",
                    help=tr("build.037"))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--media", action="store_true",
                    help=tr("build.038"))
    ap.add_argument(
        "--no-fulltext",
        action="store_true",
        help=tr("build.039"),
    )
    args = ap.parse_args()

    out_dir = (mdio.ROOT / args.out).resolve()
    commit = (args.commit or git_sha())[:12]
    problem = out_dir_problem(out_dir, mdio.ROOT.resolve())
    if problem:
        print(tr("build.041", a0=out_dir, a1=problem), file=sys.stderr)
        return 2
    if out_dir.exists():
        shutil.rmtree(out_dir)

    rc = build(out_dir, commit, with_fulltext=not args.no_fulltext,
               with_chat=args.chat or args.serve, media=args.media)
    if rc == 0 and args.serve:
        serve(out_dir, args.port)
    return rc


if __name__ == "__main__":
    sys.exit(main())
