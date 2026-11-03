"""citation-check fixes from the 2026-10-31 cross-review (H3, H12, M3, M4, M5). Each test failed before its fix.

H3  a real id cited under a different title must not be "confirmed": one-word changes (including a negation)
    used to pass a 0.90 similarity ratio. Titles must now match word for word (case, punctuation, hyphenation
    and an omitted subtitle aside), and year and first author are cross-checked.
H12 a reference bullet ("- "Title" — Author, 2017, arXiv:...") must become a full claim (title, author,
    year, id), and a bullet that looks like a reference but cannot be parsed must count, as unconfirmed.
M3  BibTeX eprint = {arXiv:1707.06347} must be looked up as 1707.06347
M4  an unquoted arxiv id in frontmatter (a YAML float) must not be looked up as a different id
M5  first-author comparison: particles, suffixes, BibTeX escapes, transliteration, either name order
"""
from __future__ import annotations

import pytest

from rak import citation as C


def judged(claim_title, record_title, claim_author="", record_author="", claim_year=0, record_year=0,
           service="arxiv"):
    claim = C.Claim("x", arxiv="1", title=claim_title, authors=[claim_author] if claim_author else [],
                    year=claim_year)
    found = (record_title, [record_author] if record_author else [], record_year)
    return C.judge(claim, found, service)


# ── H3: the negative controls the review used (real ids, wrong titles) ──

@pytest.mark.parametrize("claim,record", [
    ("BERT: Pre-training of Deep Bidirectional Transformers for Language Generation",
     "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"),
    ("Playing Go with Deep Reinforcement Learning", "Playing Atari with Deep Reinforcement Learning"),
    ("Attention Is Not All You Need", "Attention Is All You Need"),
    ("Proximal Policy Optimization Algorithm", "Trust Region Policy Optimization"),
])
def test_real_id_with_a_wrong_title_is_not_confirmed(claim, record):
    r = judged(claim, record)
    assert r.status == "mismatch" and "title" in r.reason


@pytest.mark.parametrize("claim,record", [
    ("Attention is all you need", "Attention Is All You Need"),                       # case
    ("BERT: Pre-Training of Deep Bidirectional Transformers", "BERT: Pre-training of deep bidirectional transformers"),
    ("Pretraining at scale", "Pre-training at Scale"),                               # hyphenation
    ("{RT}-2", "RT-2: Vision-Language-Action Models Transfer Web Knowledge to Robotic Control"),  # subtitle omitted
])
def test_harmless_title_differences_still_confirm(claim, record):
    assert judged(claim, record).status == "confirmed"


def test_year_is_cross_checked():
    assert judged("A Title", "A Title", claim_year=2009, record_year=2015, service="crossref").status == "mismatch"
    assert judged("A Title", "A Title", claim_year=2016, record_year=2015, service="crossref").status == "confirmed"
    # arXiv's year is the first version; the cited year is often the later conference year
    assert judged("A Title", "A Title", claim_year=2018, record_year=2017, service="arxiv").status == "confirmed"
    assert judged("A Title", "A Title", claim_year=2015, record_year=2017, service="arxiv").status == "mismatch"


# ── M5 ──

@pytest.mark.parametrize("claimed,record", [
    ("van der Maaten, Laurens", "Laurens van der Maaten"),
    ("S{\\o}rensen, Anne", "Anne Sørensen"),
    ("Sørensen, A.", "A. Sorensen"),
    ("Zhang Wei", "Wei Zhang"),
    ("King, Martin Luther, Jr.", "Martin Luther King Jr."),
    ("M{\\\"u}ller, J.", "Jürgen Müller"),
    ("Strauß, R.", "Richard Strauss"),
])
def test_first_author_variants_match(claimed, record):
    assert judged("T", "T", claimed, record).status == "confirmed"


def test_different_first_author_is_a_mismatch():
    r = judged("T", "T", "Silver, David", "Volodymyr Mnih")
    assert r.status == "mismatch" and "author" in r.reason


# ── M3 / M4 ──

def test_bibtex_eprint_prefix_is_stripped(tmp_path):
    bib = tmp_path / "r.bib"
    bib.write_text("@article{a, title={X}, author={Y, Z}, eprint={arXiv:1707.06347v2}, archivePrefix={arXiv}}\n"
                   "@article{b, title={X}, author={Y, Z}, eprint={ARXIV:2307.15818}}\n", encoding="utf-8")
    assert [c.arxiv for c in C.read_bib(bib)] == ["1707.06347", "2307.15818"]


def test_unquoted_arxiv_id_in_frontmatter_is_flagged_not_looked_up(tmp_path):
    note = tmp_path / "n.md"
    note.write_text('---\ntitle: "X"\nauthors: [A]\narxiv: 2310.12340\n---\n', encoding="utf-8")
    [claim] = C.read_claims([note])
    assert claim.arxiv == "" and "quote" in claim.problem

    class NoNet(C.Fetcher):
        def get(self, url):
            raise AssertionError(f"must not look up {url}")

    [r] = C.check([claim], NoNet("t"))
    assert r.status == "unconfirmed" and "quote" in r.reason


# ── H12 ──

REFS = """# Related work

Trust-region methods [1] and clipping [2] ...

## References

- "Trust Region Policy Optimization" — John Schulman, 2015, arXiv:1502.05477
- *Proximal Policy Optimization Algorithms*, Schulman et al., 2017, arXiv:1707.06347
- "Human-level control through deep reinforcement learning" — Volodymyr Mnih, 2015, doi:10.1038/nature14236
- "A Paper With No Identifier" — Some Author, 2019
- Somebody wrote something about policies in 2018
"""


def test_reference_bullets_become_full_claims(tmp_path):
    f = tmp_path / "report.md"
    f.write_text(REFS, encoding="utf-8")
    claims = C.read_claims([f])
    by = {(c.arxiv or c.doi or c.title or c.problem)[:20]: c for c in claims}
    trpo = next(c for c in claims if c.arxiv == "1502.05477")
    assert trpo.title == "Trust Region Policy Optimization" and trpo.authors == ["John Schulman"] and trpo.year == 2015
    ppo = next(c for c in claims if c.arxiv == "1707.06347")
    assert ppo.title == "Proximal Policy Optimization Algorithms" and ppo.year == 2017
    dqn = next(c for c in claims if c.doi == "10.1038/nature14236")
    assert dqn.title.startswith("Human-level control")
    noid = next(c for c in claims if c.title == "A Paper With No Identifier")
    assert noid.authors == ["Some Author"] and noid.year == 2019
    assert any(c.problem for c in claims), by                         # the unparsable reference counts
    assert len(claims) == 5


def test_unparsed_reference_is_unconfirmed_without_a_lookup():
    claim = C.Claim("x", problem="reference could not be parsed")

    class NoNet(C.Fetcher):
        def get(self, url):
            raise AssertionError(url)

    [r] = C.check([claim], NoNet("t"))
    assert r.status == "unconfirmed" and "parsed" in r.reason
