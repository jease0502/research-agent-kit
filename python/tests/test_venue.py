"""add_paper.guess_venue 與 schema 的 venue 守衛。不需要網路。

移植自原本知識庫的兩支測試；comment 字串逐字取自 arXiv API。起因：
`(IROS) 2026` 這類寫法（年份不緊貼會議名）曾讓 venue 變成字串 `IROS None`；
「target NeurIPS」「submitted to RA-L」這類投稿目標曾被當成發表場地。
"""
from __future__ import annotations

import pytest

from rak import add_paper as A
from rak import schema


def venue(comment: str, journal_ref: str = "") -> str:
    return A.guess_venue(journal_ref, comment)


IROS_LONG = "IEEE/RSJ International Conference on Intelligent Robots and Systems"

EXPECT = [
    # 三種基本寫法
    (f"Accepted to the {IROS_LONG} (IROS) 2026", "IROS 2026"),
    ("8 pages, 4 figures, accepted to IROS 2026", "IROS 2026"),
    ("Accepted at IROS'26", "IROS 2026"),
    # 實際踩到的其他寫法
    (f"Published in the {IROS_LONG} (IROS), 2026", "IROS 2026"),
    (f"Accepted to the 2026 {IROS_LONG} (IROS 2026)", "IROS 2026"),
    ("accepted by IROS 26", "IROS 2026"),
    # 不能產生 None，也不能亂編年份
    ("Accepted at IROS", "IROS"),
    ("Accepted at IROS. Code and data will be released after the camera-ready deadline in March 2026", "IROS"),
    # 其他會議、既有行為
    ("Accepted to ICRA 2027", "ICRA 2027"),
    ("accepted to the IEEE International Conference on Robotics and Automation (ICRA), 2027", "ICRA 2027"),
    ("CoRL 2026", "CoRL 2026"),
    ("12 pages, 5 figures", "arXiv preprint"),
    ("", "arXiv preprint"),
    # 投稿中、投稿目標不是發表場地
    ("14 pages, 6 tables, and 1 figure, target NeurIPS", "arXiv preprint"),
    ("Submitted to IROS 2026", "arXiv preprint"),
    ("8 pages, submitted to the IEEE/RSJ IROS 2026", "arXiv preprint"),
    ("Under review at ICRA 2027", "arXiv preprint"),
    ("preprint, in review at CoRL 2026", "arXiv preprint"),
    ("We are submitting to RSS 2026", "arXiv preprint"),
    (f"8 pages. Submitted to {IROS_LONG} (IROS) 2026", "arXiv preprint"),
    ("Accepted to IROS 2026. Supplementary video submitted separately", "IROS 2026"),
    ("This paper was submitted to IROS 2026 on March 2nd and accepted on June 17th", "IROS 2026"),
    # 會議名後面緊接 submission
    ("Revised version - updated with feedback from RA-L submission", "arXiv preprint"),
    ("Humanoids 2023 Conference Submission", "arXiv preprint"),
    # 網址裡的會議名
    ("https://sites.google.com/view/opal-iclr", "arXiv preprint"),
    ("Accepted to IROS 2026. Project website: https://toannguyen1904.github.io/ICLR", "IROS 2026"),
    # 特別活動不是主會議
    ("Extended abstract presented at IEEE ICRA@40, Rotterdam, Netherlands, September 2024. 2 pages, 1 figure",
     "arXiv preprint"),
    # workshop
    ("Accepted at the IROS 2026 Workshop on Sim2Real and Classical Control: From Rigorous Theory to "
     "Data-Driven Robotics", "IROS 2026 Workshop"),
    ("Accepted as an extended abstract at the DexHAND Workshop, ECCV 2026. Non-archival, non-proceedings. 4 pages",
     "ECCV 2026 Workshop"),
    ("Presented in NIPS 2014 Deep Learning and Representation Learning Workshop", "NIPS 2014 Workshop"),
    ("Accepted by CoRL 2026, also presented at IROS 2026 Human-Robot Dialogue workshop", "CoRL 2026"),
    ("Accepted to IROS 2026. 8 pages, 6 figures. Code released.", "IROS 2026"),
    # 年份寫在會議全名前面
    ("Accepted at 2026 Conference on Robot Learning (CoRL)", "CoRL 2026"),
    (f"Accepted at the 2026 {IROS_LONG} (IROS)", "IROS 2026"),
    ("Accepted as a contributed paper at the 2023 IEEE International Conference on Robotics and Automation (ICRA)",
     "ICRA 2023"),
    ("Accepted to ICRA (IEEE International Conference on Robotics and Automation)", "ICRA"),
    ("8 pages, 5 figures, submitted to RA-L", "arXiv preprint"),
]


@pytest.mark.parametrize("comment,want", EXPECT)
def test_guess_venue(comment, want):
    assert venue(comment) == want


def test_journal_ref_wins():
    assert venue("IROS 2026", journal_ref="IEEE RA-L 2025") == "IEEE RA-L 2025"


@pytest.mark.parametrize("comment", [
    "(IROS) 2026", "IROS", "ICRA", "(ICRA), 2027", "CoRL 2026", "accepted to (RSS)",
    "Accepted at the Conference on Robot Learning (CoRL), 2026",
    "Paper accepted to T-RO. Project page is at https://graspnet.net/anygrasp.html",
    "6th Conference on Robot Learning (CoRL), 2022",
    "Accepted to IEEE Transactions on Robotics (T-RO) 2024",
])
def test_never_none(comment):
    v = venue(comment)
    assert "None" not in v and "null" not in v


BASE = {"title": "T", "authors": ["A"], "year": 2023, "url": "https://arxiv.org/abs/2310.17596",
        "tags": ["rl"], "status": "queued", "summary": "s", "added": "2026-10-09", "updated": "2026-10-09"}


def venue_errors(v: str) -> list[str]:
    errs, _, _ = schema.validate("paper", {**BASE, "venue": v})
    return [e for e in errs if "venue" in e]


@pytest.mark.parametrize("bad", ["CoRL None", "IROS null", "iclr None", "RA-L nan"])
def test_schema_blocks_none_venue(bad):
    assert venue_errors(bad)


@pytest.mark.parametrize("ok", ["CoRL 2023", "arXiv preprint", "IROS", "NIPS Deep Learning Workshop 2013",
                                "Nonetheless Workshop 2024"])
def test_schema_accepts_real_venue(ok):
    assert not venue_errors(ok)
