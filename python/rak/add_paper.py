#!/usr/bin/env python3
"""Create the skeleton of papers/<slug>.md from arXiv, Crossref or manual input.

The network is reached with the standard library only (urllib, xml.etree); no requests or arxiv package.

    rak add-paper 2307.15818
    rak add-paper https://arxiv.org/abs/2307.15818v2
    rak add-paper arXiv:1707.06347 --slug ppo
    rak add-paper --doi 10.1109/ICRA.2024.12345
    rak add-paper --manual --title "…" --authors "A. Chen; B. Lin" \
        --year 2024 --url "…"
    rak add-paper 2307.15818 --dry-run   # print, write nothing
    rak add-paper 2307.15818 --refresh   # re-fetch metadata, keep the human-written content
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from string import Template

from . import __version__, config, mdio
from . import schema
from .i18n import tr

def _user_agent() -> str:
    # API etiquette: arXiv and Crossref ask for contact details in the User-Agent; sent only if rak.toml sets contact
    c = config.current().contact
    return f"research-agent-kit/{__version__}" + (f" (mailto:{c})" if c else "")


UA = None  # the name is kept for older code; what is sent is _user_agent()
ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/"

ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[:\s]\s*)?"
    r"(\d{4}\.\d{4,5}(?:v\d+)?(?![\d])|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?(?![\d]))",
    re.I,
)
VERSION_RE = re.compile(r"v\d+$")

VENUE_RE = re.compile(
    r"\b(CoRL|ICRA|IROS|NeurIPS|NIPS|ICML|ICLR|RSS|CVPR|ICCV|ECCV|AAAI|"
    r"Humanoids|RA-L|T-RO|IJRR|L4DC)\b[\s'’]*(\d{2,4})?",
    re.I,
)

# these words right before a venue name mean submitted or targeted, not published
NOT_VENUE_RE = re.compile(
    r"(submitted|submitting|submission|target(?:ed|ing)?|under review|in review|aim(?:s|ed|ing)?|prepared)\b[^.;:]{0,110}$",
    re.I,
)
# these words right after a venue name are a submission too: `feedback from RA-L submission`,
# `Humanoids 2023 Conference Submission`
NOT_VENUE_AFTER_RE = re.compile(r"^[^.;:]{0,25}\b(submission|under review|in review)\b", re.I)
# words inside a URL are not a venue: `sites.google.com/view/opal-iclr` (on 2026-10-09 a paper got the venue `iclr`
# this way)
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\S+\.github\.io\S*", re.I)
# "workshop" in the same sentence: a workshop, not the main conference (written `IROS 2026 Workshop (BLPC)`; the name in
# parentheses is left for a person to fill in)
WORKSHOP_RE = re.compile(r"workshop", re.I)
# the year before the full conference name and the short name in parentheses: `Accepted at 2026 Conference on Robot
# Learning (CoRL)`,
# `the 2026 IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)`
YEAR_BEFORE_RE = re.compile(r"\b((?:19|20)\d{2})\s+(?:[A-Za-z/&-]+\s+){1,10}\($")

NS = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """arXiv titles and abstracts carry hard line breaks and double spaces: squeeze them to single spaces."""
    return " ".join((text or "").split())


def die(msg: str, code: int = 1):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's certificate store.

    The Windows store does not include the intermediate certificate of export.arxiv.org's chain by default, and
    OpenSSL does not fetch it the way Windows does (AIA chasing), so the result is CERTIFICATE_VERIFY_FAILED.
    Without certifi this falls back to the system default; on Linux CI either works.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch(url: str, retries: int = 1, backoff: float = 5.0,
          timeout: int = 20) -> bytes:
    """GET with retries. arXiv allows one request every 3 s and answers 503 under load."""
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    ctx = _ssl_context()
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last = e
            if attempt < retries:
                print(tr("add_paper.001", a0=e, a1=backoff), file=sys.stderr)
                time.sleep(backoff)
    die(tr("add_paper.002", a0=url, a1=last))


# --------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------


def extract_arxiv_id(raw: str) -> str | None:
    m = ARXIV_RE.search(raw.strip())
    return m.group(1) if m else None


def strip_version(aid: str) -> str:
    return VERSION_RE.sub("", aid)


def guess_venue(journal_ref: str, comment: str) -> str:
    """journal_ref first; otherwise a venue name from the comment field. Finds one about 70 % of the time."""
    if journal_ref:
        return clean(journal_ref)
    # "submitted to X", "target X", "under review at X" are a submission status, not a venue: skip such hits.
    # (2026-10-05: a comment "target NeurIPS" was taken for the venue NeurIPS, so the daily collection would have
    # recorded an unaccepted paper as published.)
    c = comment or ""
    m = None
    # unless the comment also says accepted / to appear / published ("submitted to X on March 2nd and accepted on
    # June 17th")
    accepted = re.search(r"accept|to appear|published|camera.?ready", c, re.I)
    urls = [u.span() for u in URL_RE.finditer(c)]
    for cand in VENUE_RE.finditer(c):
        if any(a <= cand.start() < b for a, b in urls):
            continue                                   # a word inside a URL
        if c[cand.end(1):cand.end(1) + 1] == "@":
            continue                                   # a special event such as `ICRA@40`, not the main conference
        pre = c[max(0, cand.start() - 140):cand.start()]
        if not accepted and NOT_VENUE_RE.search(pre):
            continue
        if NOT_VENUE_AFTER_RE.search(c[cand.end(1):]):
            continue                                   # `RA-L submission`: a submission, accepted or not before it
        m = cand
        break
    if m:
        name, yr = m.group(1), m.group(2)
        if not yr:
            # the year not right after the name: `(IROS) 2026`, `(IROS), 2026`. Only a year right after the name
            # and some punctuation counts; searching the rest of the comment would pick up unrelated years.
            m2 = re.match(r"[\s),.:;\]]{1,6}((?:19|20)\d{2})\b", c[m.end():])
            yr = m2.group(1) if m2 else None
        if not yr:
            # the year before the full name and the short name in parentheses (looked for only right after "(")
            pre = c[max(0, m.start() - 160):m.start()]          # can only match when it ends with "("
            m3 = YEAR_BEFORE_RE.search(pre) if pre.endswith("(") else None
            yr = m3.group(1) if m3 else None
        if yr and len(yr) == 2:
            yr = ("20" if int(yr) < 50 else "19") + yr
        # "workshop" in the same sentence (up to the full stops around it): a workshop, not the main conference
        s0 = max(c.rfind(". ", 0, m.start()), c.rfind("; ", 0, m.start()))
        s1 = min([i for i in (c.find(". ", m.end()), c.find("; ", m.end())) if i >= 0] or [len(c)])
        # unless another venue name sits in between, whose workshop it is: `Accepted by CoRL 2026, also presented at
        # IROS 2026 ... workshop`
        ws = ""
        for w in WORKSHOP_RE.finditer(c, s0 + 1, s1):
            between = c[m.end():w.start()] if w.start() >= m.end() else c[w.end():m.start()]
            if not VENUE_RE.search(between):
                ws = " Workshop"
                break
        # without a year, only the name; the old f"{name} {yr}" produced the string "IROS None"
        return (f"{name} {yr}" if yr else name) + ws
    return "arXiv preprint"


def parse_entry(entry) -> dict | None:
    """One Atom entry -> a metadata dict. None for an entry that cannot be used."""
    title = clean(entry.findtext("a:title", "", NS))
    # a wrong id gets HTTP 200 and an entry titled "Error"
    if not title or title.lower() == "error":
        return None

    aid = clean(entry.findtext("a:id", "", NS)).split("/abs/", 1)[-1]   # hep-th/9901001 keeps its archive

    authors = [
        clean(n.text) for n in entry.findall("a:author/a:name", NS) if clean(n.text)
    ]
    published = entry.findtext("a:published", "", NS)
    year = int(published[:4]) if published[:4].isdigit() else 0

    bare = strip_version(aid)
    pdf = ""
    for link in entry.findall("a:link", NS):
        if link.get("title") == "pdf":
            # arXiv's link carries a version (...15818v1); without it, the link always points at the latest
            pdf = VERSION_RE.sub("", link.get("href", ""))

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "venue": guess_venue(
            entry.findtext("ar:journal_ref", "", NS), entry.findtext("ar:comment", "", NS)
        ),
        "arxiv": bare,
        "doi": clean(entry.findtext("ar:doi", "", NS)),
        "url": f"https://arxiv.org/abs/{bare}",
        "pdf": pdf or f"https://arxiv.org/pdf/{bare}",
        "abstract": clean(entry.findtext("a:summary", "", NS)),
    }


def fetch_arxiv(aid: str) -> dict:
    # always query without a version: asked for a version that does not exist, arXiv returns an empty feed instead
    # of an error, and only the unversioned id is stored anyway
    aid = strip_version(aid)
    qs = urllib.parse.urlencode({"id_list": aid, "max_results": 1})
    entry = ET.fromstring(fetch(f"{ARXIV_API}?{qs}")).find("a:entry", NS)
    if entry is None:
        die(tr("add_paper.003", a0=aid))
    info = parse_entry(entry)
    if info is None:
        die(tr("add_paper.004", a0=aid))
    return info


def fetch_arxiv_many(ids: list[str], chunk: int = 10) -> dict[str, dict]:
    """Look up many ids at once.

    arXiv's id_list takes several comma-separated ids, so N papers need ceil(N/10) requests, not N. **This
    matters**: one request per paper soon hits HTTP 429, and after a 429 the cool-down is long.
    """
    out: dict[str, dict] = {}
    bare = [strip_version(i) for i in ids]
    for i in range(0, len(bare), chunk):
        part = bare[i:i + chunk]
        qs = urllib.parse.urlencode({"id_list": ",".join(part), "max_results": len(part)})
        root = ET.fromstring(
            fetch(f"{ARXIV_API}?{qs}", retries=4, backoff=45.0, timeout=90)
        )
        for entry in root.findall("a:entry", NS):
            info = parse_entry(entry)
            if info:
                out[info["arxiv"]] = info
        if i + chunk < len(bare):
            time.sleep(8)  # arXiv asks for one request every 3 s; batches wait longer
    return out


# --------------------------------------------------------------------------
# Crossref (ICRA / IROS / Humanoids papers that are not on arXiv)
# --------------------------------------------------------------------------


def fetch_doi(doi: str) -> dict:
    data = json.loads(fetch(CROSSREF_API + urllib.parse.quote(doi)))
    m = data.get("message", {})
    titles = m.get("title") or []
    if not titles:
        die(tr("add_paper.005", a0=doi))

    authors = []
    for a in m.get("author", []) or []:
        name = " ".join(x for x in (a.get("given"), a.get("family")) if x)
        if name:
            authors.append(clean(name))

    issued = (m.get("issued", {}).get("date-parts") or [[0]])[0]
    container = (m.get("container-title") or [""])[0]

    return {
        "title": clean(titles[0]),
        "authors": authors,
        "year": int(issued[0]) if issued and issued[0] else 0,
        "venue": clean(container),
        "doi": doi,
        "url": m.get("URL") or f"https://doi.org/{doi}",
        "abstract": "",
    }


# --------------------------------------------------------------------------
# slugs and duplicate detection
# --------------------------------------------------------------------------


def existing_papers() -> dict[str, dict]:
    out = {}
    for p in mdio.content_files("paper"):
        meta, _, err = mdio.parse_file(p)
        out[p.stem] = {"path": p, "meta": {} if err else meta}
    return out


def norm_doi(doi: str) -> str:
    d = (doi or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip(".")


def find_duplicate(existing: dict, info: dict):
    """The slug of a note for the same paper (same arXiv id, or the same DOI), or None."""
    hit = find_by_arxiv(existing, info.get("arxiv", ""))
    if hit:
        return hit
    doi = norm_doi(info.get("doi", ""))
    if doi:
        for slug, rec in existing.items():
            if norm_doi(str(rec["meta"].get("doi") or "")) == doi:
                return slug
    return None


def refresh_message(slug: str, changed: list[str], dry_run: bool) -> str:
    head = tr("add_paper.041", a0=slug) if dry_run else tr("add_paper.024", a0=slug)
    return head + (tr("add_paper.025", a0=", ".join(changed)) if changed else tr("add_paper.026"))


def find_by_arxiv(existing: dict, aid: str):
    if not aid:
        return None
    for slug, rec in existing.items():
        if rec["meta"].get("arxiv") == aid:
            return slug
    return None


def resolve_slug(want: str, info: dict, existing: dict) -> str:
    """Never overwrite a note. A different paper with the same slug gets a suffix, printed loudly."""
    if want not in existing:
        return want
    if existing[want]["meta"].get("arxiv") and existing[want]["meta"]["arxiv"] == info.get("arxiv"):
        return want  # the same paper; the caller takes the "already there" branch
    for cand in [f"{want}-{info.get('year') or 'x'}"] + [f"{want}-{i}" for i in range(2, 20)]:
        if cand not in existing:
            print(tr("add_paper.006", a0=want, a1=cand))
            return cand
    die(tr("add_paper.007", a0=want))


# --------------------------------------------------------------------------
# composing the file
# --------------------------------------------------------------------------


def build_meta(info: dict, existing_meta: dict | None = None) -> dict:
    """metadata -> frontmatter. With existing_meta, the --refresh merge."""
    today = mdio.today()
    meta = dict(existing_meta) if existing_meta else {}

    # these fields come from the API and may be overwritten
    for key in ("title", "authors", "year", "venue", "arxiv", "doi", "url", "pdf"):
        v = info.get(key)
        if key == "venue" and v == "arXiv preprint" and meta.get("venue"):
            continue    # guess_venue's fallback must not replace a venue someone set (--refresh)
        if v:
            meta[key] = v

    if existing_meta is None:
        meta.setdefault("tags", [])
        meta.setdefault("concepts", [])
        meta.setdefault("status", "queued")
        meta.setdefault("summary", "")
        meta.setdefault("added", today)

    meta["updated"] = today
    return meta


def paper_template() -> str:
    """The knowledge base's own templates/paper.md if it has one; otherwise the bundled template of the
    section preset in use; with per-kind section overrides, one generated from the configured sections."""
    cfg = config.current()
    own = cfg.root / "templates" / "paper.md"
    if own.is_file():
        return mdio.read_text(own)
    bundled = config.PACKAGE_DIR / "templates" / (cfg.sections or cfg.locale) / "paper.md"
    if bundled.is_file() and not cfg.section_overrides:
        return mdio.read_text(bundled)
    abstract = schema.abstract_section()
    return "\n".join(f"## {h}\n\n" + ("$abstract" if h == abstract else schema.TODO_MARK) + "\n"
                     for h in schema.SECTIONS["paper"]["required"])


def render_body(abstract: str) -> str:
    tpl = Template(paper_template())
    return tpl.safe_substitute(abstract=abstract.strip() or schema.TODO_MARK)


def handoff(slug: str) -> str:
    return (
        tr("add_paper.008", a0=slug, a1=" / ".join(schema.SECTIONS["paper"]["required"][:4]))
    )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    mdio.enable_utf8_output()
    ap = argparse.ArgumentParser(
        description=tr("add_paper.009"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("target", nargs="?", help=tr("add_paper.010"))
    ap.add_argument("--doi", help=tr("add_paper.011"))
    ap.add_argument("--manual", action="store_true", help=tr("add_paper.012"))
    ap.add_argument("--title")
    ap.add_argument("--authors", help=tr("add_paper.013"))
    ap.add_argument("--year", type=int)
    ap.add_argument("--url")
    ap.add_argument("--venue")
    ap.add_argument("--slug", help=tr("add_paper.014"))
    ap.add_argument("--batch", metavar="FILE",
                    help=tr("add_paper.015"))
    ap.add_argument("--dry-run", action="store_true", help=tr("add_paper.016"))
    ap.add_argument("--refresh", action="store_true", help=tr("add_paper.017"))
    args = ap.parse_args()

    if args.batch:
        return run_batch(args.batch, args.dry_run)

    # --- get the metadata ---
    if args.manual:
        if not (args.title and args.url and args.year):
            die(tr("add_paper.018"))
        info = {
            "title": clean(args.title),
            "authors": [clean(a) for a in (args.authors or "").split(";") if a.strip()],
            "year": args.year,
            "venue": clean(args.venue) if args.venue else "",
            "url": args.url,
            "abstract": "",
        }
    elif args.doi:
        info = fetch_doi(args.doi.strip())
    elif args.target:
        aid = extract_arxiv_id(args.target)
        if not aid:
            die(tr("add_paper.019", a0=args.target))
        info = fetch_arxiv(aid)
    else:
        ap.print_help()
        return 2

    if args.venue and not args.manual:
        info["venue"] = clean(args.venue)
    if not info.get("title"):
        die(tr("add_paper.020"))

    existing = existing_papers()

    # --- duplicates: another slug, the same arXiv id ---
    dup = find_duplicate(existing, info)

    if args.refresh:
        slug = args.slug or dup
        if not slug or slug not in existing:
            die(tr("add_paper.021"))
        old_meta, old_body, err = mdio.parse_file(existing[slug]["path"])
        if err:
            die(tr("add_paper.022", a0=slug, a1=err))
        meta = build_meta(info, old_meta)
        body = old_body
        if info.get("abstract"):
            body = mdio.replace_section(body, schema.abstract_section(), info["abstract"])
        text = mdio.compose(meta, body, "paper")
        changed = [k for k in ("title", "authors", "year", "venue", "pdf", "doi")
                   if old_meta.get(k) != meta.get(k)]
        if args.dry_run:
            print(text)
        else:
            mdio.write_text(existing[slug]["path"], text)
        print(refresh_message(slug, changed, args.dry_run))
        return 0

    if dup:
        print(tr("add_paper.027", a0=dup))
        if info.get("arxiv"):
            print(tr("add_paper.028", a0=info['arxiv']))
        return 0

    return create(info, args.slug, existing, args.dry_run, verbose=True)


def create(info: dict, want_slug: str | None, existing: dict,
           dry_run: bool = False, verbose: bool = False) -> int:
    """Write one paper's metadata as papers/<slug>.md. Never overwrites a note."""
    want = want_slug or schema.slug_from_title(info["title"])
    if not schema.is_slug(want):
        die(tr("add_paper.029", a0=want))
    slug = resolve_slug(want, info, existing)

    if slug in existing:
        print(tr("add_paper.030", a0=slug))
        return 0

    meta = build_meta(info)
    text = mdio.compose(meta, render_body(info.get("abstract", "")), "paper")

    if dry_run:
        print(text)
        print(tr("add_paper.031", a0=slug), file=sys.stderr)
        return 0

    path = mdio.ROOT / "papers" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    mdio.write_text(path, text)
    existing[slug] = {"path": path, "meta": meta}
    print(tr("add_paper.032", a0=slug))
    if not info.get("abstract"):
        print(tr("add_paper.033", h=schema.abstract_section()))
    if verbose:
        print(handoff(slug))
    return 0


def _meta_all(html_text: str, name: str) -> list[str]:
    import html as _html
    pat = re.compile(r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), re.I)
    return [_html.unescape(m) for m in pat.findall(html_text)]


def fetch_arxiv_abs_pages(ids: list[str], pause: float = 6.0) -> dict[str, dict]:
    """The fallback when the API is rate-limited (429 / 503 / timeout): the citation_* meta of arxiv.org/abs/<id>.

    Authors, title, year and abstract come from the arXiv page itself (not from memory); the page writes authors
    "Family, Given", turned into "Given Family". The Comments field is read as well, for guess_venue. One request
    per paper, so this path is taken only when the API is unavailable.
    """
    import html as _html
    out: dict[str, dict] = {}
    for n, aid in enumerate(ids):
        bare = strip_version(aid)
        try:
            page = fetch(f"https://arxiv.org/abs/{bare}", retries=2, backoff=20.0, timeout=60).decode("utf-8", "replace")
        except SystemExit:
            print(tr("add_paper.034", a0=bare), file=sys.stderr)
            continue
        titles = _meta_all(page, "citation_title")
        if not titles:
            continue
        authors = []
        for a in _meta_all(page, "citation_author"):
            a = clean(a)
            if "," in a:
                last, first = a.split(",", 1)
                a = f"{first.strip()} {last.strip()}".strip()
            if a:
                authors.append(a)
        date = (_meta_all(page, "citation_date") or [""])[0]
        year = int(date[:4]) if date[:4].isdigit() else 0
        abstract = clean((_meta_all(page, "citation_abstract") or [""])[0])
        m = re.search(r'class="tablecell comments[^"]*">(.*?)</td>', page, re.S)
        comment = clean(_html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))) if m else ""
        m = re.search(r'class="tablecell jref[^"]*">(.*?)</td>', page, re.S)
        jref = clean(_html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))) if m else ""
        out[bare] = {
            "title": clean(titles[0]), "authors": authors, "year": year,
            "venue": guess_venue(jref, comment), "arxiv": bare, "doi": "",
            "url": f"https://arxiv.org/abs/{bare}", "pdf": f"https://arxiv.org/pdf/{bare}",
            "abstract": abstract,
        }
        if n + 1 < len(ids):
            time.sleep(pause)
    return out


def run_batch(path: str, dry_run: bool) -> int:
    """One paper per line, `<arxiv-id> [slug]`. The whole batch takes ceil(N/10) API requests."""
    wanted: list[tuple[str, str | None]] = []
    for line in mdio.read_text(path).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        aid = extract_arxiv_id(parts[0])
        if not aid:
            print(tr("add_paper.035", a0=parts[0]))
            continue
        wanted.append((strip_version(aid), parts[1] if len(parts) > 1 else None))

    if not wanted:
        die(tr("add_paper.036", a0=path))
    seen: set[str] = set()
    wanted = [(a, s) for a, s in wanted if not (a in seen or seen.add(a))]     # 1707.06347 and ...v2 once
    bad = [s for _, s in wanted if s is not None and not schema.is_slug(s)]
    if bad:
        die(tr("add_paper.029", a0=", ".join(bad)))                         # before any request or write

    existing = existing_papers()
    todo = [(a, s) for a, s in wanted if not find_by_arxiv(existing, a)]
    skipped = len(wanted) - len(todo)
    print(tr("add_paper.037", a0=len(wanted), a1=skipped, a2=len(todo)))
    if not todo:
        return 0

    import os as _os
    if _os.environ.get("ADD_PAPER_VIA_ABS") == "1":
        infos = fetch_arxiv_abs_pages([a for a, _ in todo])
    else:
        try:
            infos = fetch_arxiv_many([a for a, _ in todo])
        except SystemExit:
            print(tr("add_paper.038"), file=sys.stderr)
            infos = fetch_arxiv_abs_pages([a for a, _ in todo])
    print(tr("add_paper.039", a0=len(infos)) + '\n')

    missing = []
    for aid, slug in todo:
        info = infos.get(aid)
        if info is None:
            missing.append(aid)
            continue
        create(info, slug, existing, dry_run)

    if missing:
        print('\n' + tr("add_paper.040", a0=', '.join(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
