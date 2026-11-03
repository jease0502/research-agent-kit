"""citation-check against recorded responses (no network).

The responses in fixtures/citation/responses/ were recorded from arXiv, Crossref and OpenAlex by
fixtures/citation/record.py. The sample inputs mix real citations, real records cited with a wrong
title or first author, and invented ones; each test pins what the checker must say about them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rak import citation as C

FIX = Path(__file__).resolve().parent / "fixtures" / "citation"
INPUTS = [FIX / "refs.bib", FIX / "note.md", FIX / "draft.md"]


class Replay(C.Fetcher):
    """Serves recorded bytes; any URL that was not recorded is a test failure, never a network call."""

    def __init__(self, overrides: dict[str, tuple[int, bytes]] | None = None):
        super().__init__("test")
        self.index = json.loads((FIX / "responses" / "index.json").read_text(encoding="utf-8"))
        self.overrides = overrides or {}
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        if url in self.overrides:
            return self.overrides[url]
        if url not in self.index:
            raise AssertionError(f"unrecorded request: {url}")
        e = self.index[url]
        return e["status"], (FIX / "responses" / e["file"]).read_bytes()


@pytest.fixture(scope="module")
def results():
    return {(r.claim.key or r.claim.arxiv or r.claim.doi): r
            for r in C.check(C.read_claims(INPUTS), Replay())}


@pytest.mark.parametrize("key", ["schulman2017", "mnih2015", "note"])
def test_real_citations_confirmed(results, key):
    assert results[key].status == "confirmed", results[key]


def test_title_search_without_id(results):
    # The recorded OpenAlex record of this 2017 paper says 2025 (its only Vaswani record). Title and author
    # match, but the year cannot be verified from an aggregator that has it wrong: unconfirmed, not confirmed,
    # and not "mismatch" either.
    r = results["vaswani2017"]
    assert r.looked_up == "openalex" and r.status == "unconfirmed" and "OpenAlex years are sometimes wrong" in r.reason
    assert r.found_title == "Attention Is All You Need" and r.found_authors[0] == "Ashish Vaswani"


def test_wrong_title_is_mismatch(results):
    r = results["wrong_title"]
    assert r.status == "mismatch" and "title differs" in r.reason
    assert r.found_title.startswith("RT-2")              # the report shows what the id really is


def test_wrong_first_author_is_mismatch(results):
    r = results["wrong_author"]
    assert r.status == "mismatch" and r.reason == "first author differs"


def test_title_case_and_braces_do_not_matter(results):
    # wrong_author's title has {R}einforcement; only the author is wrong
    assert "title" not in results["wrong_author"].reason


@pytest.mark.parametrize("key,reason", [("invented_doi", "no record"), ("invented_title", "no title match"),
                                        ("2399.99999", "no record")])
def test_invented_citations_unconfirmed(results, key, reason):
    assert results[key].status == "unconfirmed" and results[key].reason == reason


def test_bare_ids_are_existence_checks(results):
    assert results["1707.06347"].reason == "exists"
    assert results["10.1038/nature14236"].reason == "exists"


def test_inputs_are_never_modified():
    before = {p: p.read_bytes() for p in INPUTS}
    C.check(C.read_claims(INPUTS), Replay())
    assert {p: p.read_bytes() for p in INPUTS} == before


def test_one_lookup_per_doi_and_batched_arxiv():
    rep = Replay()
    C.check(C.read_claims(INPUTS), rep)
    assert sum("crossref" in u for u in rep.calls) == 2           # nature14236 once, invented once
    assert sum("export.arxiv.org" in u for u in rep.calls) == 1   # all arXiv ids in one request


def test_network_failure_is_unconfirmed_not_confirmed():
    class Down(C.Fetcher):
        def get(self, url):
            return 0, b"connection refused"

    res = C.check(C.read_claims(INPUTS), Down("test"))
    assert all(r.status == "unconfirmed" for r in res)
    assert {r.reason for r in res} <= {"lookup failed (network or service error)"}


def test_crossref_down_falls_back_to_openalex():
    claim = C.Claim("x", doi="10.1038/nature14236", title="Human-level control through deep reinforcement learning",
                    authors=["Mnih, V."])
    crossref = C.crossref_url(claim.doi)
    openalex = C.openalex_doi_url(claim.doi)
    body = json.dumps({"title": "Human-level control through deep reinforcement learning",
                       "authorships": [{"author": {"display_name": "Volodymyr Mnih"}}]}).encode()
    [r] = C.check([claim], Replay({crossref: (503, b""), openalex: (200, body)}))
    assert r.status == "confirmed" and r.looked_up == "openalex"


def test_ambiguous_title_is_unconfirmed():
    claim = C.Claim("x", title="Learning to Walk")
    body = json.dumps({"results": [{"title": "Learning to Walk", "authorships": []},
                                   {"title": "Learning to Walk.", "authorships": []},
                                   {"title": "Learning to walk!", "authorships": []},
                                   {"title": "Learning to Walk in Minutes", "authorships": []}]}).encode()
    [r] = C.check([claim], Replay({C.openalex_search_url(claim.title): (200, body)}))
    assert r.status == "confirmed"          # identical titles after normalization are the same work
    body2 = json.dumps({"results": [{"title": "Learning to Walk", "authorships": []},
                                    {"title": "Learning to Walks", "authorships": []}]}).encode()
    [r2] = C.check([claim], Replay({C.openalex_search_url(claim.title): (200, body2)}))
    assert r2.status == "unconfirmed" and "several" in r2.reason


def test_bib_parsing():
    claims = {c.key: c for c in C.read_bib(FIX / "refs.bib")}
    assert claims["schulman2017"].arxiv == "1707.06347"
    assert claims["wrong_title"].arxiv == "2307.15818"             # from the url, version stripped
    assert claims["mnih2015"].title == "Human-level control through deep reinforcement learning"
    assert claims["vaswani2017"].authors[0] == "Vaswani, Ashish"
    assert claims["schulman2017"].year == 2017


def test_surname_forms():
    assert C.surname("Vaswani, Ashish") == C.surname("Ashish Vaswani") == "vaswani"
    assert C.surname("José Müller") == "muller"


def test_exit_codes(tmp_path, monkeypatch, capsys):
    import sys
    good = tmp_path / "good.md"
    good.write_text("see arXiv:1707.06347\n", encoding="utf-8")
    rep = Replay()
    batch = next(u for u in rep.index if "export.arxiv.org" in u)
    recorded = (rep.index[batch]["status"], (FIX / "responses" / rep.index[batch]["file"]).read_bytes())
    monkeypatch.setattr(C, "Fetcher", lambda ua: Replay({C.arxiv_url(["1707.06347"]): recorded}))
    monkeypatch.setattr(sys, "argv", ["rak cite-check", str(good)])
    assert C.main() == 0
    monkeypatch.setattr(sys, "argv", ["rak cite-check", *map(str, INPUTS)])
    assert C.main() == 1
    assert "Nothing was changed." in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["rak cite-check", str(tmp_path / "missing.bib")])
    assert C.main() == 2


# Negative controls recorded live (2026-10-31 review, H3 / M3): real ids, wrong titles or year
@pytest.mark.parametrize("key,words", [("neg_bert", ("generation", "understanding")), ("neg_dqn", ("go", "atari"))])
def test_real_id_wrong_title_recorded(results, key, words):
    r = results[key]
    assert r.status == "mismatch" and all(w in r.reason for w in words), r


def test_wrong_year_on_an_authoritative_record_is_a_mismatch(results):
    r = results["wrong_year"]
    assert r.status == "mismatch" and "year differs (cited 2009, record 2015)" in r.reason


def test_eprint_with_arxiv_prefix_recorded(results):
    assert results["eprint_prefix"].status == "confirmed" and results["eprint_prefix"].claim.arxiv == "1707.06347"
