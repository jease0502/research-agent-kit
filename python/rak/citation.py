"""Citation check: does every cited paper exist, and do its title and first author match the claim?

    rak cite-check draft.md refs.bib papers/            # report to stdout
    rak cite-check refs.bib --json report.json

What it reads:
  * BibTeX entries (`.bib`): title, author, year, doi, eprint/arXiv id, arxiv.org or doi.org urls.
  * Markdown notes with YAML frontmatter (`title`, `authors`, `arxiv`, `doi`): one claim per file.
  * Reference lists in any text (bullets, [n] lines, table rows with an id or a year): full claims.
  * Other arXiv ids and DOIs in text: existence checks only (there is no claimed title).

Where it looks:
  * arXiv ids: arXiv API (batched, 3.5 s between requests).
  * DOIs: Crossref; if Crossref has no record, OpenAlex.
  * Entries with a title but no id: OpenAlex title search; accepted only on a near-exact title match.

What it reports, per citation:
  * confirmed: the record exists and the claimed title and first author (when given) match it.
  * mismatch: the record exists but the claimed title or first author does not match it.
  * unconfirmed: no record was found, the lookup failed, the title search was ambiguous, or the title /
    first author cannot be compared (an added subtitle, no letters, an initial only, a non-Latin name).

**It never edits, deletes or completes anything.** A checker that "fixes" a citation by filling in
whatever the search returned would turn a fabricated reference into a plausible-looking real one.
Unconfirmed stays unconfirmed until a person looks at it.

Exit code: 0 if every citation is confirmed, 1 if any is a mismatch or unconfirmed or if no citation was
found at all, 2 on usage errors.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/"
OPENALEX_API = "https://api.openalex.org/works"
NS = {"a": "http://www.w3.org/2005/Atom"}

TITLE_MATCH = 0.90     # SequenceMatcher ratio used only to find candidates in a title search; judging is exact
ARXIV_PAUSE = 3.5      # arXiv asks for at most one request every 3 s
ARXIV_BATCH = 20

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[:\s]\s*)(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?", re.I)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>{}\]\[),;]+)")
VERSION_RE = re.compile(r"v\d+$")


@dataclass
class Claim:
    source: str                 # file:line or file (for a note)
    arxiv: str = ""
    doi: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    key: str = ""               # BibTeX key or note slug, for the report
    problem: str = ""           # set when the citation itself cannot be checked (unparsable, unquoted id)


@dataclass
class Result:
    claim: Claim
    status: str                 # confirmed | mismatch | unconfirmed
    reason: str
    found_title: str = ""
    found_authors: list[str] = field(default_factory=list)
    looked_up: str = ""         # which service answered


# ── normalization ───────────────────────────────────────────────────────────

def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


_LATEX_LETTERS = {"AA": "A", "aa": "a", "AE": "AE", "ae": "ae", "OE": "OE", "oe": "oe", "O": "O", "o": "o",
                  "L": "L", "l": "l", "ss": "ss", "i": "i", "j": "j"}
_LATEX_ACCENT_RE = re.compile(r"\\(?:[cvHukrdbt](?=[\s{])|['\"^`~=.])\s*\{?\s*(\\?[A-Za-z])\s*\}?")
_LATEX_LETTER_RE = re.compile(r"\\(AA|aa|AE|ae|OE|oe|ss|O|o|L|l|i|j)(?![A-Za-z])\s*(?:\{\})?")


def delatex(s: str) -> str:
    """BibTeX accents and special letters to plain letters: \\c{c} -> c, \\v{s} -> s, \\H{o} -> o, {\\'a} -> a,
    {\\AA} -> A, \\l{} -> l, {\\ss} -> ss. Braces are removed."""
    s = _LATEX_ACCENT_RE.sub(lambda m: m.group(1), s)
    s = _LATEX_LETTER_RE.sub(lambda m: _LATEX_LETTERS[m.group(1)], s)
    return re.sub(r"[{}]", "", s)


def norm_title(s: str) -> str:
    """Words of a title, lowercase and accent-folded. Any script's letters and digits count (B1: a title in
    Chinese or with a Greek letter used to reduce to nothing, so any two such titles matched)."""
    s = re.sub(r"[{}\\$]", "", delatex(s))               # BibTeX braces, LaTeX escapes and math
    return " ".join(re.findall(r"[^\W_]+", fold(unicodedata.normalize("NFKC", s))))


def title_similarity(a: str, b: str) -> float:
    a, b = norm_title(a), norm_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def title_key(s: str) -> str:
    """A title reduced to its letters and digits, without spaces: case, punctuation, LaTeX braces and
    hyphenation ("Pre-training" / "Pretraining") do not matter; every word does."""
    return norm_title(s).replace(" ", "")


def title_verdict(claimed: str, record: str) -> tuple[str, str]:
    """("match" | "differ" | "unclear", note).
    match:   equal after title_key, or the citation omits the record's subtitle (the part after a colon);
    unclear: either side has nothing to compare, or the citation ADDS a subtitle the record does not have
             (B3: "Attention Is All You Need: Why Recurrence Still Wins" must not be confirmed);
    differ:  anything else, however similar."""
    a, b = title_key(claimed), title_key(record)
    if not a or not b:
        return "unclear", "title has no letters or digits to compare"
    if a == b:
        return "match", ""
    if ":" in record and a == title_key(record.split(":", 1)[0]):
        return "match", "subtitle omitted"
    if ":" in claimed and title_key(claimed.split(":", 1)[0]) == b:
        return "unclear", "the citation adds a subtitle the record does not have; check by hand"
    wa, wb = norm_title(claimed).split(), norm_title(record).split()
    only_a = [w for w in wa if w not in wb]
    only_b = [w for w in wb if w not in wa]
    return "differ", ("title differs: only in the citation: " + (" ".join(only_a) or "—")
                      + "; only in the record: " + (" ".join(only_b) or "—"))


def title_check(claimed: str, record: str) -> tuple[bool, str]:
    """(matches, note): title_verdict reduced to a yes / no."""
    v, note = title_verdict(claimed, record)
    return v == "match", note


_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "ß": "ss", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE",
                           "œ": "oe", "Œ": "OE", "đ": "d", "Đ": "D", "þ": "th", "Þ": "Th", "ı": "i"})
PARTICLES = {"van", "der", "den", "de", "von", "la", "le", "di", "da", "du", "del", "della", "dos", "das",
             "do", "bin", "ibn", "al", "ter", "ten", "zu", "y", "e"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _norm_name(name: str) -> str:
    return fold(unicodedata.normalize("NFKC", delatex(name).translate(_TRANSLIT)).translate(_TRANSLIT))


def _units(text: str) -> list[tuple[str, ...]]:
    """Whitespace-separated name units, each a tuple of its letter parts ("garcia-lopez" -> ("garcia", "lopez")).
    Initials and suffixes (Jr., III) are dropped."""
    out = []
    for u in text.split():
        parts = tuple(re.findall(r"[^\W\d_]+", u))
        if parts and not (len(parts) == 1 and (len(parts[0]) == 1 or parts[0] in SUFFIXES)):
            out.append(parts)
    return out


def _family(name: str) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """(family-name units, all units). "Family, Given": the part before the comma. Otherwise the last unit
    and the particles right before it ("Laurens van der Maaten" -> van der maaten)."""
    norm = _norm_name(name)
    if "," in norm:
        head, tail = norm.split(",", 1)
        if _units(tail):                                   # "King, Martin Luther" (not "Martin Luther King, Jr.")
            return _units(head), _units(norm)
        norm = head
    us = _units(norm)
    if not us:
        return [], []
    i = len(us) - 1
    while i > 0 and len(us[i - 1]) == 1 and us[i - 1][0] in PARTICLES:
        i -= 1
    return us[i:], us


def _key(units: list[tuple[str, ...]]) -> tuple[str, ...]:
    parts = [x for u in units for x in u]
    core = [x for x in parts if x not in PARTICLES]
    return tuple(core or parts)                            # "Le, Quoc": the particle IS the surname


def compare_names(claimed: str, record: str) -> str:
    """"same" | "different" | "unclear" for two spellings of a first author. Only surnames are compared
    (B2: a shared given name, John Smith / John Doe, is not a match). "unclear" when a surname is missing
    (an initial only), the names are not in Latin script, or the surnames overlap only partly
    (Garcia-Lopez / Lopez): the caller reports those as unconfirmed, never as confirmed.
    Known limit: given names are not compared, so two people with one surname match ("Wang, Lei" / "Jun Wang")."""
    fc, ac = _family(claimed)
    fr, ar = _family(record)
    if not fc or not fr:
        return "unclear"
    kc, kr = _key(fc), _key(fr)
    if kc == kr:
        return "same"
    if any(not re.fullmatch(r"[a-z]+", x) for x in kc + kr):
        return "unclear"
    all_c = sorted(x for u in ac for x in u)
    all_r = sorted(x for u in ar for x in u)
    if all_c == all_r:                                     # family name first: "Zhang Wei" / "Wei Zhang"
        return "same"
    if set(kc) & set(kr) or set(kc) <= set(all_r) or set(kr) <= set(all_c):
        return "unclear"
    return "different"


def same_person(claimed: str, record: str) -> bool:
    return compare_names(claimed, record) == "same"


def surname(name: str) -> str:
    """The surname as one token (particles dropped unless they are the whole surname)."""
    fam, _ = _family(name)
    return "".join(_key(fam)) if fam else ""


def strip_version(aid: str) -> str:
    return VERSION_RE.sub("", aid)


# ── reading claims ──────────────────────────────────────────────────────────

def _bib_fields(body: str) -> dict[str, str]:
    """Fields of one BibTeX entry body. Handles {nested {braces}} and "quoted" values."""
    out: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        m = re.compile(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*").match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < n and body[i] == "{":
            depth, j = 0, i
            while j < n:
                depth += {"{": 1, "}": -1}.get(body[j], 0)
                if depth == 0:
                    break
                j += 1
            out[name], i = body[i + 1:j], j + 1
        elif i < n and body[i] == '"':
            j = body.index('"', i + 1)
            out[name], i = body[i + 1:j], j + 1
        else:
            m2 = re.compile(r"[^,}\s]+").match(body, i)
            out[name] = m2.group() if m2 else ""
            i = m2.end() if m2 else i + 1
    return out


def read_bib(path: Path) -> list[Claim]:
    text = path.read_text(encoding="utf-8", errors="replace")
    claims = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if m.group(1).lower() in ("comment", "string", "preamble"):
            continue
        # entry body runs to the brace that closes the one after @type
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        f = _bib_fields(text[m.end():j - 1])
        line = text.count("\n", 0, m.start()) + 1
        arxiv, problem = eprint_id(f.get("eprint", ""), f.get("archiveprefix", ""))
        for k in ("url", "journal", "note"):
            mm = ARXIV_ID_RE.search(f.get(k, ""))
            if not arxiv and not problem and mm:
                arxiv = strip_version(mm.group(1))
        doi = f.get("doi", "").strip()
        if not doi:
            mm = DOI_RE.search(f.get("url", ""))
            doi = mm.group(1) if mm else ""
        authors = [a.strip() for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        year = int(f["year"]) if f.get("year", "").strip().isdigit() else 0
        claims.append(Claim(f"{path}:{line}", arxiv, doi.rstrip("."), " ".join(f.get("title", "").split()),
                            authors, year, m.group(2), problem))
    return claims


BARE_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?", re.I)


def eprint_id(eprint: str, archive: str) -> tuple[str, str]:
    """(arXiv id, problem) from a BibTeX eprint: "2307.15818", "arXiv:2307.15818v2", "arXiv 2307.15818",
    an arxiv.org URL, or an old-style "hep-th/9901001". An eprint with a different archivePrefix (PubMed, ...)
    is not an arXiv id. One that claims to be arXiv but is malformed is a problem, not a lookup."""
    raw, archive = eprint.strip(), archive.strip().lower()
    if not raw or (archive and archive != "arxiv"):
        return "", ""
    v = re.sub(r"(?i)^arxiv\s*[:\s]\s*", "", raw).strip()
    m = ARXIV_ID_RE.search(v) or BARE_ARXIV_RE.fullmatch(v)
    if m:
        return strip_version(m.group(1)), ""
    if archive == "arxiv" or re.match(r"(?i)arxiv", raw) or re.match(r"\d{4}\.\d", v):
        return "", f"eprint {raw!r} is not a valid arXiv id"
    return "", ""


def read_note(path: Path, text: str) -> list[Claim] | None:
    """A markdown note with YAML frontmatter that names a paper. None if it is not one."""
    if not text.startswith("---"):
        return None
    try:
        import yaml
        end = text.index("\n---", 3)
        meta = yaml.safe_load(text[3:end]) or {}
    except Exception:
        return None
    if not isinstance(meta, dict) or not (meta.get("arxiv") or meta.get("doi")):
        return None
    authors = meta.get("authors") or []
    if isinstance(meta.get("arxiv"), (list, dict)):
        return [Claim(str(path), title=str(meta.get("title") or ""), key=path.stem,
                      problem="arxiv in the frontmatter is a list; write one quoted id")]
    if isinstance(meta.get("arxiv"), (int, float)) and not isinstance(meta.get("arxiv"), bool):
        # YAML read an unquoted id as a number (2310.12340 -> 2310.1234): looking it up would check a different paper
        return [Claim(str(path), title=str(meta.get("title") or ""), key=path.stem,
                      problem="arxiv id is a number in the frontmatter (YAML dropped digits); quote it")]
    return [Claim(str(path), strip_version(str(meta.get("arxiv") or "")), str(meta.get("doi") or ""),
                  str(meta.get("title") or ""), [str(a) for a in authors] if isinstance(authors, list) else [],
                  int(meta.get("year") or 0) if str(meta.get("year") or "").isdigit() else 0, path.stem)]


BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]|\[\d+\])\s+(.*)$")         # "- ", "1. ", "[1] "
TABLE_RE = re.compile(r"^\s*\|(.+)\|\s*$")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d\d)\b")
QUOTED_RES = [re.compile(r"[“\"]([^”\"]{3,})[”\"]"), re.compile(r"‘([^’]{3,})’"),
              re.compile(r"(?<![\w'])'((?:[^']|'(?=\w)){3,}?)'(?!\w)")]       # 'Title', apostrophes inside kept
SEG_SPLIT_RE = re.compile(r"\.\s+(?=[A-Z0-9'\"“‘(\[])|\s+[—–]\s+|\s+-\s+")
_INITIAL_RE = re.compile(r"^[A-Z]\.?$")
_NAME_RE = re.compile(r"\b[A-Z][\w'’-]+(?:\s+(?:[A-Z][\w'’-]+|[A-Z]\.?)(?![\w'’-]))*")
_NOT_NAMES = {"arxiv", "in", "proceedings", "the", "preprint", "journal", "conference", "vol", "pp", "advances",
              "available", "retrieved", "doi", "url", "and"}
LINK_RE = re.compile(r"\[([^\]]{3,})\]\([^)]*\)")
EMPHASIS_RES = [re.compile(r"\*\*([^*]{3,})\*\*"), re.compile(r"(?<!\*)\*([^*]{3,})\*(?!\*)"),
                re.compile(r"(?<!\w)_([^_]{3,})_(?!\w)")]
KV_TITLE_RE = re.compile(r"(?i)\btitle\s*[:=]\s*([^;|]+)")
KV_AUTHOR_RE = re.compile(r"(?i)\b(?:first\s+)?authors?\s*[:=]\s*([^;|]+)")
APA_RE = re.compile(r"^(?P<auth>[^()]+?)\s*\((?P<year>(?:19|20)\d\d)[a-z]?\)\.\s*(?P<title>.+?[^A-Z])\.(?:\s|$)")


def _first_author_after(rest: str) -> list[str]:
    rest = re.sub(r"^[\s,.:;—–’”\"'-]+", "", rest)
    by = re.match(r"(?i)by\s+([^(,;]+)", rest)
    author = (by.group(1) if by else rest.split(",", 1)[0]).strip()
    author = re.sub(r"\s+et\s+al\.?$", "", author).strip()
    return [author] if author and not re.search(r"\d|arxiv|doi|http", author, re.I) else []


def _is_title(s: str) -> bool:
    return len(s.split()) >= 1 and not ARXIV_ID_RE.search(s) and not DOI_RE.search(s) \
        and not re.fullmatch(r"[\W\d]+", s)


def parse_reference(path: Path, n: int, body: str, cells: list[str] | None = None) -> Claim:
    """One reference (bullet, "[n]" line or table row) -> a claim with title, first author, year and id.
    Recognized titles, most explicit first: `Title: ...` key-value, quotes (straight, curly, single curly),
    a markdown link's text, the longest **bold** / *italic* span, APA "Authors (Year). Title.", and in a
    table the first cell with words. The first author follows the title ("— Name", ", Name", "by Name")."""
    src = f"{path}:{n}"
    aid = doi = ""
    m = ARXIV_ID_RE.search(body)
    if m:
        aid = strip_version(m.group(1))
    d = DOI_RE.search(body)
    if d:
        doi = d.group(1).rstrip(".")
        if doi.lower().startswith("10.48550/arxiv."):
            aid, doi = aid or strip_version(doi[len("10.48550/arXiv."):]), ""
    without_ids = DOI_RE.sub(" ", ARXIV_ID_RE.sub(" ", body))
    y = YEAR_RE.search(without_ids)
    year = int(y.group(1)) if y else 0
    doi = doi if not aid else ""

    def claim(title, authors):
        return Claim(src, aid, doi, " ".join(title.split()).rstrip(".,"), authors, year)

    if cells is not None:
        words = [c for c in cells if _is_title(c) and not YEAR_RE.fullmatch(c) and len(c.split()) >= 2]
        if words:
            i = cells.index(words[0])
            nxt = [c for c in cells[i + 1:] if _is_title(c) and not YEAR_RE.fullmatch(c)]
            return claim(words[0], [nxt[0]] if nxt else [])
    kv = KV_TITLE_RE.search(body)
    if kv:
        a = KV_AUTHOR_RE.search(body)
        return claim(kv.group(1).strip(), [a.group(1).strip()] if a else [])
    for rx in QUOTED_RES:
        tm = rx.search(body)
        if tm:
            return claim(tm.group(1), _first_author_after(body[tm.end():]))
    tm = LINK_RE.search(body)
    if tm and _is_title(tm.group(1)):
        return claim(tm.group(1), _first_author_after(body[tm.end():]))
    spans = [mm for rx in EMPHASIS_RES for mm in rx.finditer(body) if _is_title(mm.group(1))]
    if spans:
        tm = max(spans, key=lambda mm: len(mm.group(1).split()))
        return claim(tm.group(1), _first_author_after(body[tm.end():]))
    apa = APA_RE.match(body)
    if apa:
        pieces = [x.strip() for x in apa.group("auth").split(",")]
        first = pieces[0] + (", " + pieces[1] if len(pieces) > 1 and re.fullmatch(r"(?:[A-Z]\.\s*-?)+", pieces[1])
                             else "")
        return claim(apa.group("title"), [first] if pieces[0] else [])
    sent = _sentence_reference(body)
    if sent:
        return claim(*sent)
    return Claim(src, aid, doi, year=year, problem=UNPARSED + " (no title in quotes, emphasis, a link or `Title:`, "
                                                              "and no separate title segment)")


UNPARSED = "reference could not be parsed"


def _author_like(seg: str) -> bool:
    toks = re.findall(r"[^\s,;]+", seg)
    return bool(toks) and (sum(bool(_INITIAL_RE.match(t)) for t in toks) / len(toks) >= 0.3
                           or bool(re.search(r"\bet al\b", seg)))


def _first_name(text: str) -> str:
    for m in _NAME_RE.finditer(text):
        if m.group().split()[0].lower() not in _NOT_NAMES:
            return m.group()
    return ""


def _sentence_reference(body: str) -> tuple[str, list[str]] | None:
    """Formats with no quotes or markup: segments separated by ". " or dashes, where the title is the longest
    segment of three or more words that is not an author list. Covers `Title. Author, J. 2017. arXiv:...`,
    `Title — J. Author — 2017`, and Vancouver `Author J, Author F. Title. arXiv 1707.06347. 2017.`
    The first author is the first name in the part before the title, else after it. Needs at least two
    segments, so a sentence of prose is not mistaken for a reference."""
    text = YEAR_RE.sub(" ", DOI_RE.sub(" ", ARXIV_ID_RE.sub(" ", body)))
    segs = [s.strip(" .,;:") for s in SEG_SPLIT_RE.split(text)]
    segs = [s for s in segs if s]
    if len(segs) < 2:
        return None
    cand = [(i, s) for i, s in enumerate(segs) if len(s.split()) >= 3 and not _author_like(s)
            and s.split()[0].lower() not in _NOT_NAMES]
    if not cand:
        return None
    i, title = max(cand, key=lambda c: len(c[1].split()))
    author = _first_name(" , ".join(segs[:i])) or _first_name(" , ".join(segs[i + 1:]))
    return title, [author] if author else []


def summary(results: list[Result]) -> dict:
    """Counts per status, plus `unparsed`: references that could not be read at all. They are also counted as
    unconfirmed; a caller comparing writers can leave them out, since they measure formatting, not truth."""
    counts = {s: sum(r.status == s for r in results) for s in ("confirmed", "mismatch", "unconfirmed")}
    unparsed = sum(r.claim.problem.startswith(UNPARSED) for r in results)
    return {"n_refs": len(results), **counts, "unparsed": unparsed}


def read_text_ids(path: Path, text: str) -> list[Claim]:
    """Reference lines (a bullet, "[n]" line or table row with an id or a year) become full claims; a
    reference without an id is looked up by title, so it counts. Other ids are existence checks."""
    claims, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        b = BULLET_RE.match(line)
        row = TABLE_RE.match(line) if not b else None
        if (b or row) and (ARXIV_ID_RE.search(line) or DOI_RE.search(line) or YEAR_RE.search(line)):
            cells = [c.strip() for c in row.group(1).split("|")] if row else None
            c = parse_reference(path, n, b.group(1) if b else row.group(1), cells)
            if c.arxiv:
                seen.add(("a", c.arxiv))
            if c.doi:
                seen.add(("d", c.doi.lower()))
            claims.append(c)
            continue
        for m in ARXIV_ID_RE.finditer(line):
            aid = strip_version(m.group(1))
            if ("a", aid) not in seen:
                seen.add(("a", aid))
                claims.append(Claim(f"{path}:{n}", arxiv=aid))
        for m in DOI_RE.finditer(line):
            doi = m.group(1).rstrip(".")
            if doi.lower().startswith("10.48550/arxiv."):   # arXiv's own DOI: check it as an arXiv id
                aid = strip_version(doi[len("10.48550/arXiv."):])
                if ("a", aid) not in seen:
                    seen.add(("a", aid))
                    claims.append(Claim(f"{path}:{n}", arxiv=aid))
                continue
            if ("d", doi.lower()) not in seen:
                seen.add(("d", doi.lower()))
                claims.append(Claim(f"{path}:{n}", doi=doi))
    return claims


def read_claims(paths: list[Path]) -> list[Claim]:
    out: list[Claim] = []
    files: list[Path] = []
    for p in paths:
        files += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix in (".md", ".bib", ".tex", ".txt")) \
            if p.is_dir() else [p]
    for f in files:
        if f.suffix == ".bib":
            out += read_bib(f)
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        note = read_note(f, text) if f.suffix == ".md" else None
        out += note if note is not None else read_text_ids(f, text)
    return out


# ── lookups ─────────────────────────────────────────────────────────────────

class Fetcher:
    """GET with a status code instead of an exception. Tests replace it with recorded responses."""

    def __init__(self, user_agent: str, timeout: int = 20):
        self.ua, self.timeout = user_agent, timeout
        self._last_arxiv = 0.0

    def get(self, url: str) -> tuple[int, bytes]:
        if url.startswith(ARXIV_API):
            wait = ARXIV_PAUSE - (time.monotonic() - self._last_arxiv)
            if wait > 0:
                time.sleep(wait)
            self._last_arxiv = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua})
        from .add_paper import _ssl_context
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() if hasattr(e, "read") else b""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return 0, str(e).encode()


def arxiv_url(ids: list[str]) -> str:
    return f"{ARXIV_API}?id_list={','.join(ids)}&max_results={len(ids)}"


def crossref_url(doi: str) -> str:
    return CROSSREF_API + urllib.parse.quote(doi)


def openalex_doi_url(doi: str) -> str:
    return f"{OPENALEX_API}/doi:{urllib.parse.quote(doi)}"


def openalex_search_url(title: str) -> str:
    return f"{OPENALEX_API}?{urllib.parse.urlencode({'search': norm_title(title), 'per-page': 5})}"


def lookup_arxiv(fetch: Fetcher, ids: list[str]) -> dict[str, tuple[str, list[str]] | str]:
    """id -> (title, authors), or id -> "not_found" / "lookup_failed"."""
    out: dict[str, tuple[str, list[str]] | str] = {}
    for k in range(0, len(ids), ARXIV_BATCH):
        chunk = ids[k:k + ARXIV_BATCH]
        status, body = fetch.get(arxiv_url(chunk))
        if status != 200:
            out.update({i: "lookup_failed" for i in chunk})
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            out.update({i: "lookup_failed" for i in chunk})
            continue
        for e in root.findall("a:entry", NS):
            title = " ".join((e.findtext("a:title", "", NS) or "").split())
            eid = strip_version((e.findtext("a:id", "", NS) or "").rsplit("/abs/", 1)[-1])
            if not title or title.lower() == "error" or not eid:
                continue
            pub = (e.findtext("a:published", "", NS) or "")[:4]
            out[eid] = (title, [" ".join((a.text or "").split()) for a in e.findall("a:author/a:name", NS)],
                        int(pub) if pub.isdigit() else 0)
        for i in chunk:
            out.setdefault(i, "not_found")
    return out


def lookup_doi(fetch: Fetcher, doi: str) -> tuple[tuple[str, list[str]] | str, str]:
    status, body = fetch.get(crossref_url(doi))
    if status == 200:
        try:
            m = json.loads(body).get("message", {})
            authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
                       for a in m.get("author", []) or []]
            parts = ((m.get("issued") or {}).get("date-parts") or [[None]])[0]
            year = int(parts[0]) if parts and parts[0] else 0
            return (" ".join(((m.get("title") or [""])[0]).split()), authors, year), "crossref"
        except (ValueError, AttributeError):
            pass
    crossref_missing = status == 404
    status, body = fetch.get(openalex_doi_url(doi))
    if status == 200:
        try:
            w = json.loads(body)
            authors = [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])]
            return (" ".join((w.get("title") or "").split()), authors, int(w.get("publication_year") or 0)), "openalex"
        except ValueError:
            pass
    if crossref_missing and status == 404:
        return "not_found", "crossref+openalex"
    return "lookup_failed", "crossref+openalex"


def search_title(fetch: Fetcher, title: str, year: int = 0, author: str = "") -> tuple[tuple | str, str]:
    status, body = fetch.get(openalex_search_url(title))
    if status != 200:
        return "lookup_failed", "openalex"
    try:
        results = json.loads(body).get("results", [])
    except ValueError:
        return "lookup_failed", "openalex"
    scored = sorted(((title_similarity(title, w.get("title") or ""), w) for w in results),
                    key=lambda t: -t[0])
    if not scored or scored[0][0] < TITLE_MATCH:
        return "no_match", "openalex"
    # two different works with the same near-exact title cannot be told apart by title alone
    if len(scored) > 1 and scored[1][0] >= TITLE_MATCH and \
            norm_title(scored[1][1].get("title") or "") != norm_title(scored[0][1].get("title") or ""):
        return "ambiguous", "openalex"
    # OpenAlex often holds several records of one work (preprint, proceedings, re-indexed copies, some with a
    # wrong year). Among the records with the top title, prefer the one whose year and first author agree.
    top = title_key(scored[0][1].get("title") or "")
    same = [w for s, w in scored if title_key(w.get("title") or "") == top]

    def fit(w):
        y = int(w.get("publication_year") or 0)
        first = ((w.get("authorships") or [{}])[0].get("author") or {}).get("display_name", "")
        return (0 if not author or same_person(author, first) else 1, abs(y - year) if year and y else 99)

    w = min(same, key=fit) if (year or author) else scored[0][1]
    authors = [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])]
    return (" ".join((w.get("title") or "").split()), authors, int(w.get("publication_year") or 0)), "openalex"


# ── judging ─────────────────────────────────────────────────────────────────

def judge(claim: Claim, found: tuple[str, list[str]] | str, service: str) -> Result:
    if isinstance(found, str):
        why = {"not_found": "no record", "lookup_failed": "lookup failed (network or service error)",
               "no_match": "no title match", "ambiguous": "several works match the title"}[found]
        return Result(claim, "unconfirmed", why, looked_up=service)
    title, authors, year = (tuple(found) + (0,))[:3]
    problems, notes = [], []
    doubts = []
    if claim.title:
        verdict, note = title_verdict(claim.title, title)
        if note:
            {"match": notes, "differ": problems, "unclear": doubts}[verdict].append(note)
    if claim.authors and authors:
        who = compare_names(claim.authors[0], authors[0])
        if who == "different":
            problems.append("first author differs")
        elif who == "unclear":
            doubts.append(f"first author cannot be compared ({claim.authors[0]} / {authors[0]}); check by hand")
    if claim.year and year:
        # arXiv's year is the first version's; the cited year is often a later venue's
        lo, hi = (year, year + 2) if service == "arxiv" else (year - 1, year + 1)
        if not lo <= claim.year <= hi:
            if service == "openalex":
                # an aggregator: its years are sometimes wrong (seen: a 2017 paper listed as 2025), so a
                # disagreement is a doubt to check by hand, not evidence that the citation is wrong
                doubts.append(f"year differs (cited {claim.year}, OpenAlex {year}); OpenAlex years are "
                              "sometimes wrong, check by hand")
            else:
                problems.append(f"year differs (cited {claim.year}, record {year})")
    if problems:
        return Result(claim, "mismatch", "; ".join(problems), title, authors, service)
    if doubts:
        return Result(claim, "unconfirmed", "; ".join(doubts), title, authors, service)
    what = "exists" if not claim.title else "title and first author match" if claim.authors else "title matches"
    if notes:
        what += f" ({', '.join(notes)})"
    return Result(claim, "confirmed", what, title, authors, service)


def check(claims: list[Claim], fetch: Fetcher) -> list[Result]:
    arxiv_ids = sorted({c.arxiv for c in claims if c.arxiv and not c.problem})
    arxiv = lookup_arxiv(fetch, arxiv_ids) if arxiv_ids else {}
    results = []
    dois: dict[str, tuple] = {}       # one lookup per DOI / title, however often it is cited
    titles: dict[str, tuple] = {}
    for c in claims:
        if c.problem:
            results.append(Result(c, "unconfirmed", c.problem))
        elif c.arxiv:
            results.append(judge(c, arxiv.get(c.arxiv, "lookup_failed"), "arxiv"))
        elif c.doi:
            key = c.doi.lower()
            if key not in dois:
                dois[key] = lookup_doi(fetch, c.doi)
            results.append(judge(c, *dois[key]))
        elif c.title:
            first = c.authors[0] if c.authors else ""
            key = (norm_title(c.title), c.year, first)
            if key not in titles:
                titles[key] = search_title(fetch, c.title, c.year, first)
            results.append(judge(c, *titles[key]))
        else:
            results.append(Result(c, "unconfirmed", "no id and no title to look up"))
    return results


# ── report ──────────────────────────────────────────────────────────────────

def report(results: list[Result]) -> str:
    lines = ["| status | citation | where | detail |", "|---|---|---|---|"]
    order = {"mismatch": 0, "unconfirmed": 1, "confirmed": 2}
    for r in sorted(results, key=lambda r: order[r.status]):
        c = r.claim
        ident = c.key or (f"arXiv:{c.arxiv}" if c.arxiv else f"doi:{c.doi}" if c.doi else c.title[:60])
        detail = r.reason
        if r.status == "mismatch":
            detail += f" — record: “{r.found_title[:80]}”" + (f", {r.found_authors[0]}" if r.found_authors else "")
        lines.append(f"| {r.status} | {ident} | {c.source} | {detail} |")
    counts = {s: sum(r.status == s for r in results) for s in order}
    lines.append("")
    lines.append(f"{len(results)} citations: {counts['confirmed']} confirmed, {counts['mismatch']} mismatch, "
                 f"{counts['unconfirmed']} unconfirmed. Nothing was changed.")
    return "\n".join(lines)


def main() -> int:
    from . import config
    ap = argparse.ArgumentParser(prog="rak cite-check", description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, help="also write the full results as JSON")
    a = ap.parse_args()
    missing = [p for p in a.paths if not p.exists()]
    if missing:
        print(f"not found: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2
    claims = read_claims(a.paths)
    if not claims:
        # not a clean pass: a draft whose references were all missed (bare ids, an unknown format) looks the
        # same as one with none, so say what is detected and exit 1 (review L2)
        print("no citations found: nothing was checked. Detected: BibTeX, notes with frontmatter, reference "
              "lines (bullets, [n], table rows) with an id or a year, and ids written as arXiv:1707.06347, "
              "arXiv 1707.06347, arxiv.org links or DOIs. A bare 1707.06347 is not detected.", file=sys.stderr)
        return 1
    contact = config.current().contact
    from . import __version__
    ua = f"research-agent-kit/{__version__}" + (f" (mailto:{contact})" if contact else "")
    results = check(claims, Fetcher(ua))
    print(report(results))
    if a.json:
        a.json.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return 0 if all(r.status == "confirmed" for r in results) else 1
