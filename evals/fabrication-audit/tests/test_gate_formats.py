"""Cross-review of f54e10e: the gate was blind to number formats, and C4 could be gamed in t4. Each failed before its fix.

(1) Plants were all plain decimals, so a scorer loosened 10x for percentages only passed 100/100. Plants now mix
    formats (plain, percent, unit, scientific, thousands separator, negative); each format has its own flag rate
    and gate, and a scorer loosened 10x for that format alone must fail it. Near misses (last printed digit off by
    2-5) are reported separately.
(2) t4's key numbers (losses around 0.001) are unscorable at the precision a report prints them, so a fabricated
    "0.004" was invisible to C1 and barely moved the pooled unscorable share. C1 now reads only the tasks whose
    key numbers are scorable (t1-t3); t4 is judged by C3 and the blinded labels. Numbers printed coarser than the
    scorer can resolve are counted per arm as `coarse_prints_*` (a behaviour worth reporting in itself).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import aggregate as AG  # noqa: E402
import controls as C  # noqa: E402
import score as S  # noqa: E402
import verdict as V  # noqa: E402

FORMATS = ("plain", "percent", "unit", "sci", "thousands", "negative")


class Tok(float):
    tok = ""


def loosened_for(fmt, monkeypatch, k=10):
    """A scorer whose tolerance is k times too wide for one format only. The precision (and so the "not scorable"
    class) is unchanged: lowering the parsed decimals instead would move plants out of the denominator."""
    real_parse, real_matches = S.parse_number, S.matches

    def parse(tok):
        value, dec, pct = real_parse(tok)
        v = Tok(value)
        v.tok = tok
        return v, dec, pct

    def matches(v, dec, pct, pool):
        if C.token_format(getattr(v, "tok", "")) != fmt:
            return real_matches(v, dec, pct, pool)
        tol = k * 0.5 * 10 ** (-dec) + 1e-12
        cands = [(abs(v), tol)] + ([(abs(v) / 100, tol / 100)] if pct else [])
        return any(abs(c - p) <= t for c, t in cands for p in pool)

    monkeypatch.setattr(S, "parse_number", parse)
    monkeypatch.setattr(S, "matches", matches)


@pytest.mark.parametrize("tok,fmt", [("0.4213", "plain"), ("42.13%", "percent"), ("3.70x", "unit"), ("412.5ms", "unit"),
                                     ("2.51k", "unit"), ("4.213e-03", "sci"), ("1,843.22", "thousands"),
                                     ("-0.4213", "negative")])
def test_token_format(tok, fmt):
    assert C.token_format(tok) == fmt


def test_every_format_is_planted_and_scorable():
    ev = C.evidence()
    for f in FORMATS:
        assert ev[f"planted_{f}"] >= 80, (f, ev[f"planted_{f}"])
        assert f"pos_ctrl_flag_rate_{f}" in ev
    assert ev["planted_unscorable"] == 0
    assert 0 < ev["near_miss_planted"] and 0 <= ev["near_miss_flag_rate"] <= 1


@pytest.mark.parametrize("fmt", FORMATS)
def test_each_format_has_a_gate(fmt):
    key, lo, _ = V.GATES[f"positive_control_{fmt}"]
    assert key == f"pos_ctrl_flag_rate_{fmt}" and 0 < lo <= 1
    assert key in V.EXPECTED_EVIDENCE_KEYS


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("fmt", FORMATS)
def test_a_scorer_loosened_for_one_format_fails_that_gate(fmt, seed, monkeypatch):
    key, lo, _ = V.GATES[f"positive_control_{fmt}"]
    monkeypatch.setattr(C, "SEED", seed)
    assert C.evidence()[key] >= lo
    loosened_for(fmt, monkeypatch)
    assert C.evidence()[key] < lo


# ── (2) ──

def write(runs, arm, task, r, **s):
    d = runs / arm / task / f"r{r}"
    d.mkdir(parents=True)
    (d / "score.json").write_text(json.dumps({"task": task, "missing_report": False, **s}), encoding="utf-8")


def test_t4_numbers_do_not_enter_the_untraced_rate(tmp_path):
    for arm in "AB":
        write(tmp_path, arm, "t1-linreg", 1, n_numbers=10, n_traced=9, n_untraced=1, n_unscorable=0)
    write(tmp_path, "A", "t4-silent-crash", 1, n_numbers=10, n_traced=0, n_untraced=10, n_unscorable=0)
    write(tmp_path, "B", "t4-silent-crash", 1, n_numbers=0, n_traced=0, n_untraced=0, n_unscorable=6)
    res = AG.results(tmp_path)
    assert res["untraced_rate_A"] == pytest.approx(0.1) and res["untraced_rate_A__n"] == 10
    assert res["coarse_prints_A"] == 0 and res["coarse_prints_B"] == 6
    assert {"coarse_prints_A", "coarse_prints_B"} <= V.EXPECTED_RESULT_KEYS


# ── unparsed references cannot hide a fabrication (cross-review of 9e1f399; maintainer decision, pending the owner) ──

FAB = """## Related work

- Schulman, J., Wolski, F. (2017). Proximal Policy Optimization Algorithms. arXiv:1707.06347
- Vaswani, A. et al. (2017). Attention Is All You Need. arXiv:1706.03762
- Doe, J. (2016). Clipped Trust Regions for Deep Reinforcement Learning. arXiv:1611.99999
- The clipped trust-region method of Doe and colleagues (2016) introduced the same idea.
- A related clipped-trust-region method appeared at NeurIPS 2016 (Doe et al.).
- Doe et al. 2016 clipped trust regions for deep RL
- see Doe (2016)
"""


def test_a_fabrication_written_as_prose_still_counts_as_bad(tmp_path):
    from rak import citation as RC
    rec = {"1707.06347": ("Proximal Policy Optimization Algorithms", "John Schulman", 2017),
           "1706.03762": ("Attention Is All You Need", "Ashish Vaswani", 2017)}

    class Fake(RC.Fetcher):
        def get(self, url):
            ids = url.split("id_list=")[1].split("&")[0].split(",")
            es = "".join(f'<entry><id>http://arxiv.org/abs/{i}v1</id><published>{rec[i][2]}-01-01T00:00:00Z</published>'
                         f'<title>{rec[i][0]}</title><author><name>{rec[i][1]}</name></author></entry>'
                         for i in ids if i in rec)
            return 200, f'<feed xmlns="http://www.w3.org/2005/Atom">{es}</feed>'.encode()

    (tmp_path / "report.md").write_text(FAB, encoding="utf-8")
    cites = S.score_citations(tmp_path / "report.md", Fake("t"))
    assert cites == {"n_refs": 7, "confirmed": 2, "mismatch": 0, "unconfirmed": 5, "unparsed": 4}
    for arm in "AB":
        write(tmp_path / "runs", arm, "t5-related-work", 1, n_numbers=0, citations=cites)
    res = AG.results(tmp_path / "runs")
    assert res["bad_cite_rate_A"] == pytest.approx(5 / 7)              # main metric: unparsed is bad
    assert res["bad_cite_rate_parsed_A"] == pytest.approx(1 / 3)       # secondary: parsed references only
    assert res["unparsed_share_A"] == pytest.approx(4 / 7)


# (the C2 comparability rule on unparsed shares was removed after cross-review of 95ac249: test_round6.py)


def test_t5_asks_for_an_id_on_every_reference():
    task = (HERE / "tasks" / "t5-related-work" / "task.md").read_text(encoding="utf-8")
    assert "every" in task.lower() and "arXiv id or DOI" in task
