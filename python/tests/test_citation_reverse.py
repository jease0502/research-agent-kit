"""Reverse cross-review of the citation fixes (2026-10-31). Each failed before its fix.

B1 non-Latin titles were reduced to an empty key, so any two of them "matched"; a title with nothing to
   compare must never be confirmed
B2 a first author matched on any shared token (a given name: John Smith ~ John Doe), and a particle surname
   (Le, Quoc) was stripped to nothing, which also matched. Compare surnames; if they cannot be compared,
   the result is unconfirmed, not confirmed
B3 a subtitle the record does not have is unconfirmed; only an omitted subtitle is harmless
B4 BibTeX accent commands \\c{c} \\v{s} \\H{o} and the letter {\\AA}
B5 references in other formats (APA, key-value, markdown link, [n] numbered, table rows, single quotes,
   "by Author") are read, and a numbered reference without an id still counts (title lookup)
B6 eprint variants (URL, "arXiv 2307.15818", old-style ids without a prefix, a non-arXiv archivePrefix,
   a malformed id) and `arxiv: [..]` in frontmatter
"""
from __future__ import annotations

import pytest

from rak import citation as C


def judged(claim_title, record_title, claim_author="", record_author="", service="arxiv"):
    claim = C.Claim("x", arxiv="1", title=claim_title, authors=[claim_author] if claim_author else [])
    return C.judge(claim, (record_title, [record_author] if record_author else [], 0), service)


# ── B1 ──

@pytest.mark.parametrize("a,b", [("深度學習在機器人", "強化學習的理論"), ("α-VAE: Learning Basic Visual Concepts",
                                                                  "β-VAE: Learning Basic Visual Concepts")])
def test_non_latin_titles_are_compared(a, b):
    assert judged(a, b).status == "mismatch"


def test_same_non_latin_title_matches():
    assert judged("深度學習在機器人", "深度學習在機器人").status == "confirmed"
    assert judged("ｄｅｅｐ ｌｅａｒｎｉｎｇ", "Deep Learning").status == "confirmed"      # full width (NFKC)


@pytest.mark.parametrize("a,b", [("!!!", "???"), ("—", "Attention Is All You Need")])
def test_a_title_with_nothing_to_compare_is_never_confirmed(a, b):
    assert judged(a, b).status == "unconfirmed"


# ── B2 ──

@pytest.mark.parametrize("claimed,record", [
    ("John Smith", "John Doe"), ("Ashish Vaswani", "Ashish Sharma"), ("Le, Quoc", "Geoffrey Hinton"),
    ("Do, Minh", "Yann LeCun"), ("Du, Yilun", "Kaiming He"), ("De, Soham", "Oriol Vinyals"),
    ("Wei Li", "Wei Chen"),
])
def test_a_shared_given_name_or_a_particle_surname_is_not_a_match(claimed, record):
    assert judged("T", "T", claimed, record).status == "mismatch"


@pytest.mark.parametrize("claimed,record", [("Le, Quoc", "Quoc V. Le"), ("Do, Minh", "Minh Do"),
                                            ("De, Soham", "Soham De")])
def test_particle_surnames_still_match_themselves(claimed, record):
    assert judged("T", "T", claimed, record).status == "confirmed"


@pytest.mark.parametrize("claimed,record", [("J.", "Anybody Else"), ("张伟", "李娜"), ("Garcia-Lopez, Ana", "Ana Lopez")])
def test_names_that_cannot_be_compared_are_unconfirmed(claimed, record):
    assert judged("T", "T", claimed, record).status == "unconfirmed"


def test_family_name_first_order_still_matches():
    assert judged("T", "T", "Zhang Wei", "Wei Zhang").status == "confirmed"


# ── B3 ──

@pytest.mark.parametrize("a,b", [("Attention Is All You Need: Why Recurrence Still Wins", "Attention Is All You Need"),
                                 ("Not: A Study", "Not")])
def test_an_added_subtitle_is_not_confirmed(a, b):
    assert judged(a, b).status != "confirmed"


def test_an_omitted_subtitle_is_still_fine():
    assert judged("BERT", "BERT: Pre-training of Deep Bidirectional Transformers").status == "confirmed"


# ── B4 ──

@pytest.mark.parametrize("claimed,record", [
    ("Gon\\c{c}alves, J.", "João Gonçalves"), ("Ko\\v{s}eck{\\'a}, Jana", "Jana Košecká"),
    ("Erd\\H{o}s, Paul", "Paul Erdős"), ("{\\AA}str{\\\"o}m, K.", "Karl Åström"),
    ("Pi\\l{}sudski, J.", "Józef Piłsudski"), ("Ho{\\ss}, M.", "Max Hoss"),
])
def test_bibtex_accent_commands(claimed, record):
    assert judged("T", "T", claimed, record).status == "confirmed"


# ── B5 ──

REC = {"1707.06347": ("Proximal Policy Optimization Algorithms", "John Schulman", 2017),
       "1502.05477": ("Trust Region Policy Optimization", "John Schulman", 2015)}


class Fake(C.Fetcher):
    def get(self, url):
        if "openalex" in url:
            return 200, b'{"results": []}'
        ids = url.split("id_list=")[1].split("&")[0].split(",")
        es = "".join(f'<entry><id>http://arxiv.org/abs/{i}v1</id><published>{REC[i][2]}-01-01T00:00:00Z</published>'
                     f'<title>{REC[i][0]}</title><author><name>{REC[i][1]}</name></author></entry>'
                     for i in ids if i in REC)
        return 200, f'<feed xmlns="http://www.w3.org/2005/Atom">{es}</feed>'.encode()


def checked(tmp_path, line):
    f = tmp_path / "report.md"
    f.write_text("Related work.\n\n## References\n\n" + line + "\n", encoding="utf-8")
    claims = C.read_claims([f])
    return claims, C.check(claims, Fake("t"))


@pytest.mark.parametrize("line", [
    "- Schulman, J., Wolski, F., et al. (2017). Proximal Policy Optimization Algorithms. arXiv:1707.06347",
    "- Title: Proximal Policy Optimization Algorithms; first author: John Schulman; year: 2017; arXiv:1707.06347",
    "1. [Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347), John Schulman, 2017",
    "- **PPO** (Schulman et al., 2017): *Proximal Policy Optimization Algorithms*, arXiv:1707.06347",
    "- ‘Trust Region Policy Optimization’, John Schulman, 2015, arXiv:1502.05477",
])
def test_correct_references_in_other_formats_are_confirmed(tmp_path, line):
    claims, res = checked(tmp_path, line)
    assert [r.status for r in res] == ["confirmed"], [(c.title, c.authors, r.reason) for c, r in zip(claims, res)]


@pytest.mark.parametrize("line", [
    '- "Proximal Policy Optimization Algorithms" by Sergey Levine (2017), arXiv:1707.06347',
    '[1] "Proximal Policy Gradient Algorithms" — John Schulman, 2017, arXiv:1707.06347',
    "| Proximal Policy Gradient Algorithms | John Schulman | 2017 | arXiv:1707.06347 |",
])
def test_wrong_references_in_other_formats_are_not_confirmed(tmp_path, line):
    _, res = checked(tmp_path, line)
    assert res and all(r.status != "confirmed" for r in res), [(r.status, r.reason) for r in res]


def test_a_numbered_reference_without_an_id_still_counts(tmp_path):
    claims, res = checked(tmp_path, '[2] "Clipped Trust Regions for Deep RL" — Jane Doe, 2016')
    assert len(res) == 1 and res[0].status == "unconfirmed" and claims[0].title.startswith("Clipped")


def test_a_table_header_is_not_a_reference(tmp_path):
    claims, _ = checked(tmp_path, "| Title | Author | Year | Id |\n|---|---|---|---|\n"
                                  "| Trust Region Policy Optimization | John Schulman | 2015 | arXiv:1502.05477 |")
    assert len(claims) == 1 and claims[0].title == "Trust Region Policy Optimization"


# ── B6 ──

def test_eprint_variants(tmp_path):
    bib = tmp_path / "r.bib"
    bib.write_text("""@article{a2, title={X}, eprint={https://arxiv.org/abs/2307.15818}, archivePrefix={arXiv}}
@article{a3, title={X}, eprint={https://arxiv.org/abs/2307.15818}}
@article{a5, title={X}, eprint={hep-th/9901001}}
@article{a7, title={X}, eprint={arXiv 2307.15818}}
@article{a9, title={X}, eprint={2307.15818}, archivePrefix={PubMed}}
@article{a11, title={X}, eprint={2307.158}, archivePrefix={arXiv}}
""", encoding="utf-8")
    got = {c.key: (c.arxiv, bool(c.problem)) for c in C.read_bib(bib)}
    assert got["a2"] == ("2307.15818", False) and got["a3"] == ("2307.15818", False)
    assert got["a5"] == ("hep-th/9901001", False) and got["a7"] == ("2307.15818", False)
    assert got["a9"][0] == ""                                   # a PubMed id is not an arXiv id
    assert got["a11"] == ("", True)                             # malformed: reported, not looked up


def test_arxiv_list_in_frontmatter_is_flagged(tmp_path):
    n = tmp_path / "n.md"
    n.write_text('---\ntitle: "X"\narxiv: [2310.12340]\n---\n', encoding="utf-8")
    [c] = C.read_claims([n])
    assert c.problem and not c.arxiv
