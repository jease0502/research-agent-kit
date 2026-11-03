"""Reference formats the parser could not read (second cross-review of 58dbf9f). Each failed before its fix.

A correct reference that cannot be parsed ends up unconfirmed, so two writers with different formatting habits
would get different "bad citation" rates. These formats are now read:
  `1. Title. Author, J. 2017. arXiv:...`, straight single quotes `'Title' by Author`, em-dash separated
  `Title — J. Author — 2017 — arXiv:...`, and Vancouver `Author J, Author F. Title. arXiv 1707.06347. 2017.`
and an id written `arXiv 1707.06347` (no colon) is extracted.
"""
from __future__ import annotations

import pytest

from rak import citation as C

REC = {"1707.06347": ("Proximal Policy Optimization Algorithms", "John Schulman", 2017)}


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
    f.write_text("## References\n\n" + line + "\n", encoding="utf-8")
    claims = C.read_claims([f])
    return claims, C.check(claims, Fake("t"))


@pytest.mark.parametrize("line", [
    "1. Proximal Policy Optimization Algorithms. Schulman, J. 2017. arXiv:1707.06347",
    "- 'Proximal Policy Optimization Algorithms' by John Schulman, 2017, arXiv:1707.06347",
    "- Proximal Policy Optimization Algorithms — J. Schulman — 2017 — arXiv:1707.06347",
    "1. Schulman J, Wolski F, Dhariwal P. Proximal Policy Optimization Algorithms. arXiv 1707.06347. 2017.",
])
def test_more_formats_are_confirmed(tmp_path, line):
    claims, res = checked(tmp_path, line)
    assert [r.status for r in res] == ["confirmed"], [(c.title, c.authors, c.arxiv, r.reason)
                                                       for c, r in zip(claims, res)]


@pytest.mark.parametrize("line", [
    "1. Proximal Policy Gradient Algorithms. Schulman, J. 2017. arXiv:1707.06347",
    "- 'Proximal Policy Optimization Algorithms' by Sergey Levine, 2017, arXiv:1707.06347",
    "- Proximal Policy Optimization Algorithms — S. Levine — 2017 — arXiv:1707.06347",
    "1. Levine S, Finn C. Proximal Policy Optimization Algorithms. arXiv 1707.06347. 2017.",
])
def test_the_same_formats_still_catch_errors(tmp_path, line):
    _, res = checked(tmp_path, line)
    assert [r.status for r in res] == ["mismatch"], [(r.status, r.reason) for r in res]


def test_arxiv_id_without_a_colon():
    assert C.ARXIV_ID_RE.search("see arXiv 1707.06347v2.").group(1) == "1707.06347"


def test_an_apostrophe_inside_a_single_quoted_title():
    c = C.parse_reference("x", 1, "'Attention Isn't All You Need' by A. Author, 2020")
    assert c.title == "Attention Isn't All You Need" and c.authors == ["A. Author"]


def test_unparsed_is_counted_separately():
    claims = [C.Claim("x:1", arxiv="1707.06347", title="Proximal Policy Optimization Algorithms"),
              C.Claim("x:2", problem="reference could not be parsed (no title)")]
    res = C.check(claims, Fake("t"))
    assert C.summary(res) == {"n_refs": 2, "confirmed": 1, "mismatch": 0, "unconfirmed": 1, "unparsed": 1}


# ── L2 (2026-10-31 review): a draft in which nothing was found is not a clean pass ──

def test_no_citations_found_is_not_exit_0(tmp_path, monkeypatch, capsys):
    import sys
    f = tmp_path / "draft.md"
    f.write_text("Our method follows 1707.06347 closely.\n", encoding="utf-8")      # a bare id: not detected
    monkeypatch.setattr(sys, "argv", ["rak cite-check", str(f)])
    assert C.main() == 1
    err = capsys.readouterr().err
    assert "no citations found" in err and "arXiv:" in err
