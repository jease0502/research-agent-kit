"""scan_private.py 擋得住的證明。

每個樣式至少一個「要擋」和一個「不能誤擋」的例子。所有看起來像機密或私有路徑的字串都在執行時才拼起來，
這支測試檔本身才不會被掃描器擋下（掃描器會掃整個 repo，包含這裡）。

私有名稱用測試專用的假名單（`zorblax`、`宇宙鴨`），不碰真的名單 —— 真的名單不在 repo 裡（任何形式都不行）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scan_private as S  # noqa: E402

J = "".join  # 執行時拼字串


FAKE_LIST = "# test list\nzorblax\nacme-corp\n宇宙鴨\n10.1.2.3\n"


@pytest.fixture
def terms():
    return S.Terms.from_lines(FAKE_LIST.splitlines())


@pytest.fixture
def deny_file(tmp_path, monkeypatch):
    f = tmp_path / "deny.txt"
    f.write_text(FAKE_LIST, encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(f))
    return f


def rules_hit(text, terms):
    return [r for _, _, _, r, _ in S.scan_text("t", text, terms)]


BLOCK = {
    "user-path": [J(["C:", "\\Users\\", "alice\\x"]), J(["/c/", "Users/", "alice/x"]), J(["/Us", "ers/alice/x"])],
    "drive-path": [J(["D:", "\\github\\repo"]), J(["E:/", "data/x"]), J(["/mn", "t/d/work"])],
    "home-path": [J(["/ho", "me/alice/.ssh"])],
    "email": [J(["alice", "@", "corp-mail.com"])],
    "gcp-project-id": [J(["project-", "1a2b3c4d", "-5e6f"])],
    "gcs-bucket": [J(["gs:", "//lab-results-7f3a/run1"])],
    "cgnat-ip": [J(["100.", "101.", "2.3"])],
    "telegram-token": [J(["123456789", ":AA", "A" * 33])],
    "hf-token": [J(["hf_", "a" * 34])],
    "github-token": [J(["ghp_", "b" * 36])],
    "aws-key": [J(["AKIA", "ABCDEFGHIJKLMNOP"])],
    "google-api-key": [J(["AIza", "c" * 35])],
    "anthropic-key": [J(["sk-ant-", "d" * 24])],
    "openai-key": [J(["sk-", "e" * 40])],
    "slack-token": [J(["xoxb-", "1234567890-abc"])],
    "private-key": [J(["-----BEGIN ", "RSA PRIVATE KEY-----"])],
    "gcp-sa-key": [J(['"private_', 'key_id": "', "f" * 40, '"'])],
}


@pytest.mark.parametrize("rule,text", [(r, t) for r, ts in BLOCK.items() for t in ts])
def test_rule_blocks(rule, text, terms):
    assert rule in rules_hit(f"x = '{text}'", terms)


def test_every_rule_has_a_blocking_case():
    assert set(BLOCK) == set(S.RULES)


ALLOW = [
    "see https://arxiv.org/abs/2307.15818",           # URL 不是磁碟路徑
    J(["/ho", "me/user/.cache"]),                      # 占位使用者
    J(["me", "@", "example.com"]),
    J(["t", "@", "example.invalid"]),                  # RFC 2606 保留網域
    J(["noreply", "@", "anthropic.com"]),
    J(["gs:", "//your-bucket/out"]), J(["gs:", "//bucket/x"]), J(["gs:", "//$BUCKET/x"]),
    "100.63.1.1 and 100.128.0.1",                      # CGNAT 範圍外
    "sk-short",
    "ratio 3:2 at a:b",
]


@pytest.mark.parametrize("text", ALLOW)
def test_no_false_positive(text, terms):
    assert rules_hit(text, terms) == []


@pytest.mark.parametrize("text", ["the Zorblax lab", "zorblax_data/x", "ACME-Corp", "acme corp", "acmecorp",
                                  "這是宇宙鴨專案", "ssh 10.1.2.3"])
def test_private_term_blocks(text, terms):
    assert "private-term" in rules_hit(text, terms)


@pytest.mark.parametrize("text", ["zorblaxian", "pre-zorbla", "acme", "宇宙", "10.1.2.33"])
def test_private_term_word_boundaries(text, terms):
    assert "private-term" not in rules_hit(text, terms)


def test_adjacent_words_are_joined_on_purpose(terms):
    # 相鄰的詞會接起來比對（才抓得到 "Acme Corp"、"acme_corp"），代價是 "zorbla x" 也會被擋：寧可多擋。
    assert "private-term" in rules_hit("pre-zorbla x", terms)


def test_output_is_masked(terms):
    secret = J(["hf_", "Z" * 34])
    out = list(S.scan_text("f", f"token={secret} zorblax", terms))
    joined = " ".join(d for *_, d in out)
    assert secret not in joined and "zorblax" not in joined.lower()
    assert "deny list line 2" in joined     # referred to by its line only (line 1 is a comment)


def test_inline_allow(terms):
    line = J(["D:", "\\github\\repo"]) + "  # rak-scan: allow drive-path"
    assert rules_hit(line, terms) == []
    assert "private-term" in rules_hit("zorblax  # rak-scan: allow private-term", terms)  # 私有名稱不能放行


def test_allow_file_and_path_names(tmp_path, terms):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "paths.md").write_text(J(["D:", "\\github\\repo\n"]), encoding="utf-8")
    (root / "zorblax_notes.txt").write_text("clean\n", encoding="utf-8")
    (root / "font.woff2").write_bytes(b"\0\0" + J(["hf_", "q" * 34]).encode())
    (root / S.ALLOW_FILE_NAME).write_text("docs/*.md drive-path\n", encoding="utf-8")
    allow = S.load_allow(root)
    hits = list(S.scan_files(list(S.walk([root], root)), root, terms, allow))
    # the private name in the file name is reported, but the printed path masks it (review H6)
    assert [(h[0], h[3]) for h in hits] == [("<private-term line 2> (path)", "private-term")]


def test_allow_file_rejects_unknown_rule(tmp_path):
    (tmp_path / S.ALLOW_FILE_NAME).write_text("* everything\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        S.load_allow(tmp_path)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_history_catches_removed_content(tmp_path, terms):
    root = tmp_path / "h"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("zorblax\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-qm", "add")
    (root / "a.txt").write_text("clean\n", encoding="utf-8")
    _git(root, "commit", "-qam", "scrub the acme corp name")
    tree = list(S.scan_files([root / "a.txt"], root, terms, []))
    hist = list(S.scan_history(root, terms, []))
    assert tree == []
    assert any(h[0].startswith("a.txt@") for h in hist)          # 舊 blob
    assert any("message" in h[0] for h in hist)                   # commit message


def test_cli_exit_codes(tmp_path, deny_file):
    clean, dirty = tmp_path / "clean.txt", tmp_path / "dirty.txt"
    clean.write_text("nothing here\n", encoding="utf-8")
    dirty.write_text(J(["gs:", "//lab-results-7f3a/x\n"]), encoding="utf-8")
    assert S.main(["--root", str(tmp_path), str(clean)]) == 0
    assert S.main(["--root", str(tmp_path), str(dirty)]) == 1


def test_cli_private_term_hit(tmp_path, deny_file, capsys):
    f = tmp_path / "notes.md"
    f.write_text("met the Zorblax team\n", encoding="utf-8")
    assert S.main(["--root", str(tmp_path), str(f)]) == 1
    out = capsys.readouterr().out
    assert "private-term" in out and "zorblax" not in out.lower()


def test_ci_without_list_fails(tmp_path, monkeypatch, capsys):
    # CI 不能「沒名單就當作沒有私有名稱」：那正是名單被誤刪時會發生的事
    f = tmp_path / "clean.txt"
    f.write_text("nothing here\n", encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.setenv("CI", "true")
    assert S.main(["--root", str(tmp_path), str(f)]) == 2
    (tmp_path / "empty.txt").write_text("# only a comment\n", encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(tmp_path / "empty.txt"))
    assert S.main(["--root", str(tmp_path), str(f)]) == 2


def test_local_without_list_warns_and_still_scans(tmp_path, monkeypatch, capsys):
    clean, dirty = tmp_path / "clean.txt", tmp_path / "dirty.txt"
    clean.write_text("nothing here\n", encoding="utf-8")
    dirty.write_text(J(["gs:", "//lab-results-7f3a/x\n"]), encoding="utf-8")
    monkeypatch.setenv("RAK_DENY_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.delenv("CI", raising=False)
    assert S.main(["--root", str(tmp_path), str(clean)]) == 0
    assert "找不到私有名單" in capsys.readouterr().err
    assert S.main(["--root", str(tmp_path), str(dirty)]) == 1


def test_default_list_location_is_outside_the_repo():
    repo = S.HERE.parent.resolve()
    assert not S.DEFAULT_DENY_FILE.resolve().is_relative_to(repo)


def test_no_deny_list_in_any_form_in_the_repo():
    """名單不能進 repo —— 明文不行，雜湊也不行（短名稱可以被猜回來）。"""
    files = S.git_files(S.HERE.parent) or []
    assert not [f for f in files if "deny" in f.lower() and f.endswith((".txt", ".json"))]
    assert not [f for f in files if "private_terms" in f]


def test_repo_itself_is_clean():
    """整個 repo（工作區）必須掃得乾淨 —— 這就是 CI 會跑的那一項。

    用的是真的名單（RAK_DENY_FILE 或預設位置）；本機沒有名單時只檢查樣式規則（掃描器會印警告）。
    """
    assert S.main([]) == 0


# ── 核可的 commit 身分（maintainer 2026-11-01：使用者決定 commit 身分不重寫）──────────────────────

IDENT = (J(["Zorb", "lax Dev"]), J(["dev@zorb", "lax.invalid"]))     # 名字裡有名單上的字


def _ident_repo(tmp_path, commits):
    """commits: [(author_name, author_email, committer_name, committer_email, message)]"""
    root = tmp_path / "ident"
    root.mkdir()
    _git(root, "init", "-q")
    for i, (an, ae, cn, ce, msg) in enumerate(commits):
        (root / f"f{i}.txt").write_text(f"clean {i}\n", encoding="utf-8")
        _git(root, "add", f"f{i}.txt")
        env = {**os.environ, "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae, "GIT_COMMITTER_NAME": cn,
               "GIT_COMMITTER_EMAIL": ce}
        subprocess.run(["git", "commit", "-qm", msg], cwd=root, check=True, capture_output=True, env=env)
    return root


def _fields(hits):
    return sorted({h[0].split(" ", 2)[2] for h in hits if h[0].startswith("commit ")})


def test_allowed_identity_is_not_a_hit(tmp_path, terms):
    root = _ident_repo(tmp_path, [(*IDENT, *IDENT, "plain message")])
    assert _fields(S.scan_history(root, terms, [])) == ["author", "committer"]      # without the list: hits
    assert list(S.scan_history(root, terms, [], identities={IDENT})) == []


@pytest.mark.parametrize("other", [
    (IDENT[0].lower(), IDENT[1]),                       # 大小寫
    (IDENT[0].replace(" ", "  "), IDENT[1]),            # 多空白
    (IDENT[0], J(["dev2@zorb", "lax.invalid"])),         # 不同 email
    (IDENT[0], IDENT[1].upper()),                        # email 大小寫
])
def test_similar_identity_still_hits(tmp_path, terms, other):
    root = _ident_repo(tmp_path, [(*other, *other, "plain message")])
    assert _fields(S.scan_history(root, terms, [], identities={IDENT})) == ["author", "committer"]


def test_author_and_committer_are_judged_separately(tmp_path, terms):
    other = (J(["zorb", "lax bot"]), "bot@example.invalid")
    root = _ident_repo(tmp_path, [(*IDENT, *other, "m1"), (*other, *IDENT, "m2")])
    hits = list(S.scan_history(root, terms, [], identities={IDENT}))
    assert sorted(h[0].split(" ", 2)[2] for h in hits) == ["author", "committer"]


def test_allowed_identity_elsewhere_still_hits(tmp_path, terms):
    root = _ident_repo(tmp_path, [(*IDENT, *IDENT, f"signed off by {IDENT[0]}")])
    (root / "README.md").write_text(f"maintainer: {IDENT[0]}\n", encoding="utf-8")
    _git(root, "add", "README.md")
    subprocess.run(["git", "commit", "-qm", "readme"], cwd=root, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": IDENT[0], "GIT_AUTHOR_EMAIL": IDENT[1],
                        "GIT_COMMITTER_NAME": IDENT[0], "GIT_COMMITTER_EMAIL": IDENT[1]})
    names = [h[0] for h in S.scan_history(root, terms, [], identities={IDENT})]
    assert any(n.endswith("message") for n in names)
    assert any(n.startswith("README.md@") for n in names)
    assert not any(n.endswith(("author", "committer")) for n in names)
    assert list(S.scan_files([root / "README.md"], root, terms, []))


def test_identity_file_format(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text(f"# comment\n\n{IDENT[0]} <{IDENT[1]}>\n  Other  Name <o@example.invalid>  \n", encoding="utf-8")
    assert S.load_identities_file(f) == {IDENT, ("Other  Name", "o@example.invalid")}
    for bad in ("no email here", "Name <>", "<a@b.invalid>", "Name <a@b.invalid> trailing"):
        f.write_text(bad + "\n", encoding="utf-8")
        with pytest.raises(S.TermsError):
            S.load_identities_file(f)


def test_cli_reads_the_identity_list_and_never_prints_it(tmp_path, deny_file, monkeypatch, capsys):
    root = _ident_repo(tmp_path, [(*IDENT, *IDENT, "plain message")])
    monkeypatch.setenv("RAK_ALLOW_IDENTITIES", str(tmp_path / "missing.txt"))
    assert S.main(["--root", str(root), "--history"]) == 1                       # no list: as before
    ids = tmp_path / "ids.txt"
    ids.write_text(f"{IDENT[0]} <{IDENT[1]}>\n", encoding="utf-8")
    monkeypatch.setenv("RAK_ALLOW_IDENTITIES", str(ids))
    capsys.readouterr()
    assert S.main(["--root", str(root), "--history"]) == 0
    out = capsys.readouterr()
    assert IDENT[0].lower() not in (out.out + out.err).lower() and IDENT[1] not in out.out + out.err
    ids.write_text("broken line\n", encoding="utf-8")
    assert S.main(["--root", str(root), "--history"]) == 2


def test_default_identity_list_is_outside_the_repo():
    assert S.DEFAULT_IDENTITIES_FILE == Path.home() / ".config" / "research-agent-kit" / "allow_identities.txt"
    assert not (HERE.parent.parent / "allow_identities.txt").exists()


# ── maintainer 2026-11-01（cross-review ec6f722 之後）──────────────────────────────────────────────

def test_lists_written_with_a_bom_are_read(tmp_path):
    """Notepad and PowerShell 5 write UTF-8 with a BOM; the first entry must still count (utf-8-sig)."""
    f = tmp_path / "ids.txt"
    f.write_bytes(f"{IDENT[0]} <{IDENT[1]}>\n".encode("utf-8-sig"))
    assert S.load_identities_file(f) == {IDENT}
    d = tmp_path / "deny.txt"
    d.write_bytes("zorblax\n".encode("utf-8-sig"))
    assert list(S.Terms.load(d).find("zorblax"))


def test_empty_and_missing_lists_say_which(tmp_path, monkeypatch, capsys):
    f = tmp_path / "clean.txt"
    f.write_text("nothing here\n", encoding="utf-8")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("RAK_DENY_FILE", str(tmp_path / "missing.txt"))
    assert S.main(["--root", str(tmp_path), str(f)]) == 2
    err = capsys.readouterr().err
    assert "找不到" in err and "空" not in err.split("。")[0]
    empty = tmp_path / "deny-empty.txt"
    empty.write_text("\n", encoding="utf-8")                 # what printf writes for an unset secret
    monkeypatch.setenv("RAK_DENY_FILE", str(empty))
    assert S.main(["--root", str(tmp_path), str(f)]) == 2
    err = capsys.readouterr().err
    assert "空" in err and "RAK_DENY_TERMS" in err and "沒設" in err
    assert str(empty) not in err and "deny-empty" not in err                      # no path for an empty list


def test_identity_list_empty_and_missing_say_which(tmp_path, monkeypatch):
    monkeypatch.setenv("RAK_ALLOW_IDENTITIES", str(tmp_path / "missing.txt"))
    ids, note = S.load_identities()
    assert ids == set() and "沒有" in note
    (tmp_path / "ids.txt").write_text("\n", encoding="utf-8")
    monkeypatch.setenv("RAK_ALLOW_IDENTITIES", str(tmp_path / "ids.txt"))
    ids, note = S.load_identities()
    assert ids == set() and "空" in note and "RAK_ALLOW_IDENTITIES" in note and "沒設" in note
    assert "ids.txt" not in note


def test_email_hit_prints_nothing_of_the_address(terms):
    addr = J(["alice", "@", "corp-mail.com"])
    hits = list(S.scan_text("f", f"x\nmail {addr}\n", terms))
    assert [(n, rule, desc) for _, n, _, rule, desc in hits] == [(2, "email", "email：<redacted>")]


def _tag(root, name, tagger_name, tagger_email):
    env = {**os.environ, "GIT_COMMITTER_NAME": tagger_name, "GIT_COMMITTER_EMAIL": tagger_email}
    subprocess.run(["git", "tag", "-a", name, "-m", "release"], cwd=root, check=True, capture_output=True, env=env)


def test_annotated_tag_tagger_is_scanned_and_approved_identity_exempt(tmp_path, terms):
    clean = ("Rel Bot", "bot@example.invalid")
    root = _ident_repo(tmp_path, [(*clean, *clean, "plain message")])
    _tag(root, "v1", *IDENT)
    hits = [h[0] for h in S.scan_history(root, terms, [])]
    assert any(h.startswith("tag ") and h.endswith(" tagger") for h in hits), hits
    assert list(S.scan_history(root, terms, [], identities={IDENT})) == []
    _tag(root, "v2", IDENT[0].lower(), IDENT[1])                                   # not exact: still a hit
    hits = [h[0] for h in S.scan_history(root, terms, [], identities={IDENT})]
    assert len({h for h in hits if h.endswith(" tagger")}) == 1          # one field (name and email both hit)


def test_allow_file_with_a_bom(tmp_path):
    (tmp_path / S.ALLOW_FILE_NAME).write_bytes("docs/*.md email\n".encode("utf-8-sig"))
    assert S.load_allow(tmp_path) == [("docs/*.md", "email")]
