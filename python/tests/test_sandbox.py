"""templates/sandbox: the egress proxy's allowlist and the canary's judging, offline (no Docker, no model)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SANDBOX = Path(__file__).resolve().parents[2] / "templates" / "sandbox"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SANDBOX / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = _load("egress_proxy")
V = _load("verify")
H = _load("host")
ALLOW = P.load_allow("api.anthropic.com arxiv.org, .arxiv.org")


@pytest.mark.parametrize("host, port, ok", [
    ("api.anthropic.com", 443, True), ("API.Anthropic.com", 443, True), ("api.anthropic.com.", 443, True),
    ("export.arxiv.org", 443, True), ("arxiv.org", 443, True),
    ("api.anthropic.com", 80, False), ("api.anthropic.com", 22, False),
    ("anthropic.com", 443, False), ("evil-api.anthropic.com.attacker.net", 443, False),
    ("notarxiv.org", 443, False), ("arxiv.org.evil.net", 443, False), ("example.com", 443, False),
    ("1.1.1.1", 443, False), ("api.anthropic.com\r\nX: y", 443, False), ("a..arxiv.org", 443, False),
])
def test_allowlist(host, port, ok):
    assert P.allowed(host, port, ALLOW) is ok


@pytest.mark.parametrize("line, want", [
    ("CONNECT api.anthropic.com:443 HTTP/1.1", ("api.anthropic.com", 443)),
    ("GET http://example.com/ HTTP/1.1", None),
    ("CONNECT api.anthropic.com:443 HTTP/1.1 extra", None),
    ("CONNECT [::1]:443 HTTP/1.1", None),
])
def test_only_connect(line, want):
    assert P.parse_connect(line) == want


def test_empty_allowlist_refuses_to_start(monkeypatch):
    monkeypatch.setenv("RAK_EGRESS_ALLOW", "  ")
    monkeypatch.setattr("sys.argv", ["egress_proxy.py"])
    assert P.main() == 2


NONCE = "CANARY-abc"


def _events(results: dict[str, str]):
    """results: step key -> tool result text; builds the stream-json events for the ten canary steps."""
    steps = [("mcp__rak__read", {"path": "notes.md"}, "read"), ("mcp__rak__read", {"path": "../outside.txt"}, "dotdot"),
             ("mcp__rak__read", {"path": "/etc/passwd"}, "abs"), ("mcp__rak__read", {"path": ".git/config"}, "git"),
             ("mcp__rak__exec", {"argv": ["curl", "https://example.com"]}, "curl"),
             ("mcp__rak__write", {"path": "out.txt", "content": NONCE}, "write"),
             ("mcp__rak__exec", {"argv": ["git", "status", "--short"]}, "gitstatus"),
             ("mcp__rak__exec", {"argv": ["python3", "-c", "print('HOSTVIEW', [])"]}, "host"),
             ("mcp__rak__exec", {"argv": ["python3", "-c", "open('/opt/rak/python/rak/policy/rules.json','a')"]}, "ro"),
             ("mcp__rak__exec", {"argv": ["python3", "-c", "urllib.request.urlopen"]}, "net")]
    ev = []
    for i, (name, inp, key) in enumerate(steps):
        ev.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": name,
                                                                 "input": inp}]}})
        ev.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                                            "content": results[key]}]}})
    return ev


GOOD = {"read": "notes for the sandbox canary\n", "dotdot": "rak policy denied: '..' is not allowed",
        "abs": "rak policy denied: resolves outside", "git": "rak policy denied: under .git",
        "curl": "rak policy denied: not on the --exec-allow list", "write": "wrote 10 characters",
        "gitstatus": "exit code: 0\n?? notes.md", "host": "exit code: 0\nHOSTVIEW []",
        "ro": "exit code: 1\nOSError: [Errno 30] Read-only file system", "net": "exit code: 1\nTunnel connection failed: 403"}


@pytest.fixture
def project(tmp_path):
    (tmp_path / "out.txt").write_text(NONCE)
    return tmp_path


def test_judge_all_pass(project):
    c = V.judge(_events(GOOD), [{}] * 10, NONCE, project)
    assert set(c.values()) == {"pass"}, c


@pytest.mark.parametrize("key, text, check", [
    ("ro", "exit code: 0\n", "L1: policy file read-only"),                             # the write went through
    ("ro", "rak policy denied: P1", "L1: policy file read-only"),                      # stopped by L2, L1 untested
    ("net", "exit code: 0\n200", "L1: off-allowlist host unreachable"),
    ("host", "exit code: 0\nHOSTVIEW ['/mnt/c']", "L1: host drives and home not visible"),
    ("dotdot", f"OUTSIDE-{NONCE}", "mcp: '..' refused"),
    ("curl", "exit code: 0\n<html>", "mcp: program off the allowlist refused"),
])
def test_judge_catches(project, key, text, check):
    c = V.judge(_events({**GOOD, key: text}), [{}] * 10, NONCE, project)
    assert c[check] == "fail", c


def test_judge_needs_the_attempt(project):
    ev = [e for e in _events(GOOD) if "t9" not in json.dumps(e)]
    assert V.judge(ev, [{}] * 10, NONCE, project)["L1: off-allowlist host unreachable"] == "not exercised"


# ---- host.py (review of 6555c3c: H3 read-only overlays, M1 path checks) and the canary's reset (M4)

def test_sandbox_and_policy_engine_share_one_list():
    """L1 and L2 judge names with the same function and lists (checks_policy, loaded by file). Every P1 entry is
    refused by the sandbox at the root and nested, and every entry without a wildcard is a read-only overlay."""
    import sys
    sys.path.insert(0, str(SANDBOX.parents[1] / "python"))
    from rak.policy import checks_policy as P1
    assert H.P1.PROTECTED_DIRS == P1.PROTECTED_DIRS and H.P1.PROTECTED_FILES == P1.PROTECTED_FILES
    for d in P1.PROTECTED_DIRS:
        sample = "/".join("x" if c == "*" else c for c in d)
        assert H.protected(f"{sample}/f") and H.protected(f"deep/{sample}/f"), d
        if "*" not in d:
            assert "/".join(d) in H.RO_DIRS, d
    for f in P1.PROTECTED_FILES:
        sample = "/".join(f)
        assert H.protected(sample) and H.protected(f"deep/{sample}"), f
        if len(f) == 1:
            assert f[0] in H.RO_FILES, f


@pytest.mark.parametrize("name", [".git", ".vscode", ".claude", ".github", ".husky"])
def test_overlay_dirs_include(name):
    assert name in H.RO_DIRS


@pytest.fixture
def tree(tmp_path):
    home = tmp_path / "home"
    for d in ("home/proj", "home/kit", "home/audit", "home/proj/sub"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path, home


def test_check_accepts_separate_folders(tree):
    t, home = tree
    H.check(str(home / "proj"), str(home / "kit"), str(home / "audit"), str(home))


@pytest.mark.parametrize("proj, kit, audit, why", [
    ("home", "home/kit", "home/audit", "home folder"),
    ("", "home/kit", "home/audit", "home folder"),                       # contains home
    ("home/proj", "home/proj/sub", "home/audit", "RAK_KIT must not be inside"),
    ("home/proj/sub", "home/proj", "home/audit", "must not be inside RAK_KIT"),
    ("home/proj", "home/kit", "home/proj/sub", "RAK_AUDIT must be outside"),
])
def test_check_refuses(tree, proj, kit, audit, why):
    t, home = tree
    with pytest.raises(H.Refused, match=why):
        H.check(str(t / proj), str(t / kit), str(t / audit), str(home))


def test_check_refuses_a_filesystem_root(tree):
    t, home = tree
    root = Path(t.anchor)
    with pytest.raises(H.Refused, match="root"):
        H.check(str(root), str(home / "kit"), str(home / "audit"), str(home))


@pytest.mark.skipif(not __import__("os").path.normcase("A") == "a", reason="case-insensitive filesystems only")
def test_check_ignores_case_where_the_filesystem_does(tree):
    t, home = tree
    with pytest.raises(H.Refused, match="RAK_KIT must not be inside"):
        H.check(str(home / "PROJ"), str(home / "proj" / "SUB"), str(home / "audit"), str(home))


def test_mounts(tmp_path):
    proj, empty = tmp_path / "p", tmp_path / "e"
    (proj / ".git").mkdir(parents=True)
    empty.mkdir()
    (proj / ".mcp.json").write_text("{}")
    args = H.mounts(str(proj), str(empty))
    pairs = [args[i + 1] for i in range(0, len(args), 2)]
    assert all(args[i] == "-v" for i in range(0, len(args), 2))
    assert f"{H.host_path(str(proj / '.git'))}:/work/.git:ro" in pairs
    assert f"{H.host_path(str(empty))}:/work/.vscode:ro" in pairs
    assert f"{H.host_path(str(proj / '.mcp.json'))}:/work/.mcp.json:ro" in pairs
    assert not any("/work/.envrc" in x for x in pairs)                    # absent file: caught by compare instead
    assert len(pairs) == len(H.RO_DIRS) + 1


def test_mount_mode_quarantines_and_restores(tmp_path):
    proj, store, quar = tmp_path / "p", tmp_path / "s", tmp_path / "q"
    (proj / ".git" / "hooks").mkdir(parents=True)
    (proj / ".git" / "objects").mkdir()
    (proj / ".git" / "config").write_text("[core]")
    store.mkdir()
    H.backup(str(proj), str(store))
    assert H.restore(str(proj), str(store), str(quar)) == []
    (proj / ".git" / "hooks" / "pre-commit").write_text("evil")
    (proj / ".git" / "config").write_text("[core]\nhooksPath=x")
    (proj / ".git" / "objects" / "ab").write_text("objects are not watched")
    (proj / ".envrc").write_text("curl x | sh")
    (proj / "notes.md").write_text("ordinary work is not touched")
    changes = H.restore(str(proj), str(store), str(quar))
    assert changes == ["created: .envrc", "changed: .git/config", "created: .git/hooks/pre-commit"]
    assert (proj / ".git" / "config").read_text() == "[core]"                       # original back
    assert not (proj / ".git" / "hooks" / "pre-commit").exists() and not (proj / ".envrc").exists()
    assert (quar / ".git" / "hooks" / "pre-commit").read_text() == "evil"          # evidence kept
    assert (quar / ".git" / "config").read_text().endswith("hooksPath=x")
    assert (proj / "notes.md").exists()


@pytest.mark.parametrize("rel, hit", [
    (".git/hooks/pre-commit", True), (".GIT/hooks/pre-commit", True), (".Git/config", True),
    (".git./hooks/pre-push", True), (".git /config", True), ("GIT~1/hooks/x", True), ("CLAUDE~1/settings.json", True),
    (".ENVRC", True), (".Envrc", True), (".vscode/tasks.json", True), ("Scripts/Hooks/pre-commit", True),
    ("src/.git/config", True), ("docs/.envrc", True),            # nested counts too (review of 2528365)
    ("notes.md", False), ("scripts/build.py", False), (".gitignore", False), ("gitx/config", False),
    ("docs/envrc.md", False), ("src/claude/x.py", False),
])
def test_protected_in_any_spelling(rel, hit):
    assert bool(H.protected(rel)) is hit


def _tar(path, files: dict, kinds: dict | None = None):
    import io
    import tarfile
    with tarfile.open(path, "w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            if (kinds or {}).get(name) == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, data
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    return str(path)


BASE = {"./notes.md": b"notes\n", "./src/a.py": b"print(1)\n"}


@pytest.mark.parametrize("added, why", [
    ({"./.GIT/hooks/pre-commit": b"x"}, "under .git"),
    ({"./GIT~1/hooks/post-checkout": b"x"}, "8.3"),
    ({"./.git./hooks/pre-push": b"x"}, "ends in a dot"),
    ({"./.Claude/settings.json": b"{}"}, "under .claude"),
    ({"./.ENVRC": b"x"}, "under .envrc"),
    ({"./README": b"a", "./readme": b"b"}, "only by case"),
    ({"./nul.txt": b"x"}, "reserved"),
    ({"./a:b": b"x"}, "character"),
])
def test_inspect_refuses(tmp_path, added, why):
    base = _tar(tmp_path / "b.tar", BASE)
    new = _tar(tmp_path / "n.tar", {**BASE, **added})
    assert H.inspect(base, new, str(tmp_path / "out")) == 3
    problems = " ".join(json.loads((tmp_path / "out" / "summary.json").read_text())["problems"])
    assert why in problems, problems


def test_inspect_refuses_a_symlink(tmp_path):
    base = _tar(tmp_path / "b.tar", BASE)
    new = _tar(tmp_path / "n.tar", {**BASE, "./link": "../../etc"}, {"./link": "symlink"})
    assert H.inspect(base, new, str(tmp_path / "out")) == 3


def test_inspect_accepts_ordinary_work(tmp_path):
    base = _tar(tmp_path / "b.tar", BASE)
    new = _tar(tmp_path / "n.tar", {"./notes.md": b"notes\nmore\n", "./src/b.py": b"x", "./docs/config.md": b"ok"})
    assert H.inspect(base, new, str(tmp_path / "out")) == 4
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["problems"] == [] and s["changed"] == ["docs/config.md", "notes.md", "src/a.py", "src/b.py"]
    assert H.inspect(base, base, str(tmp_path / "out2")) == 0


def test_pack_leaves_out_git_and_protected_paths(tmp_path):
    import tarfile
    proj = tmp_path / "p"
    (proj / ".vscode").mkdir(parents=True)
    (proj / ".vscode" / "tasks.json").write_text("{}")
    (proj / ".envrc").write_text("x")
    (proj / "notes.md").write_text("n")
    r = H.pack(str(proj), str(tmp_path / "t.tar"))
    with tarfile.open(tmp_path / "t.tar") as tf:
        assert tf.getnames() == ["notes.md"]
    assert sorted(r["left_out_protected"]) == [".envrc", ".vscode/tasks.json"]


def test_mount_mode_refuses_windows_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(H.os, "name", "nt")              # any path that is not under \\wsl.localhost or \\wsl$
    with pytest.raises(H.Refused, match="case-sensitive"):
        H.check_mount_fs(str(tmp_path))


def test_cleanup_removes_only_empty_mount_points(tmp_path):
    made = H.missing(str(tmp_path))
    assert "scripts" in made and made.index("scripts") < made.index("scripts/hooks")
    for d in made:
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / ".vscode" / "tasks.json").write_text("{}")                 # something left behind stays
    H.cleanup(str(tmp_path), made)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".vscode"]


def test_canary_refuses_a_real_project(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "thesis.tex").write_text("years of work")
    with pytest.raises(V.NotOurs):
        V.reset_project(proj, "CANARY-x")
    assert (proj / "thesis.tex").exists()


def test_canary_refuses_someone_elses_outside_file(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (tmp_path / "outside.txt").write_text("not ours")
    with pytest.raises(V.NotOurs):
        V.reset_project(proj, "CANARY-x")


def test_canary_resets_its_own_folder(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    V.reset_project(proj, "CANARY-x")
    (proj / "leftover.txt").write_text("from the last run")
    V.reset_project(proj, "CANARY-y")
    assert not (proj / "leftover.txt").exists() and (proj / V.MARKER).is_file()


# ---- review of 2528365

def _link_dir(link: Path, target: Path) -> None:
    """A junction on Windows (no admin needed), a symlink elsewhere."""
    import os
    import subprocess
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("use_git", [True, False])
def test_pack_does_not_follow_links_out_of_the_project(tmp_path, use_git):
    """H: Git for Windows lists files under a junction; pack must not copy what lies outside the project."""
    import subprocess
    import tarfile
    outside, proj = tmp_path / "outside", tmp_path / "proj"
    outside.mkdir()
    (outside / "secret.txt").write_text("OUTSIDE-CANARY")
    (proj / "docs").mkdir(parents=True)
    (proj / "notes.md").write_text("n")
    _link_dir(proj / "jn", outside)
    _link_dir(proj / "docs" / "sub", outside)
    if use_git:
        subprocess.run(["git", "init", "-q", str(proj)], check=True)
    r = H.pack(str(proj), str(tmp_path / "t.tar"))
    with tarfile.open(tmp_path / "t.tar") as tf:
        names = tf.getnames()
        data = b"".join(tf.extractfile(m).read() for m in tf.getmembers() if m.isfile())
    assert b"OUTSIDE-CANARY" not in data, names
    assert names == ["notes.md"]
    assert any("jn" in s for s in r["skipped_links_or_special"]), r


@pytest.mark.parametrize("rel", ["sub/.claude/settings.json", "sub/.vscode/tasks.json", "sub/.envrc",
                                 "pkg/.husky/pre-commit", "a/b/.mcp.json", "sub/.git/config",
                                 "pkg/scripts/hooks/pre-commit", "deep/x/.GIT/hooks/a", "sub/.g‌it/config",
                                 "sub/.e﻿nvrc"])
def test_protected_at_any_depth(rel):
    """M: a protected name anywhere in the path, not only at the root; invisible characters do not hide it."""
    assert H.protected(rel), rel


@pytest.mark.parametrize("files, why", [
    ({"./sub/evil/HEAD": b"ref: refs/heads/main\n", "./sub/evil/objects/x": b"", "./sub/evil/refs/heads/main": b"0"},
     "git repository"),
    ({"./sub/evil/config": b"[core]\n\tbare = true\n\tpager = touch /tmp/pwned\n"}, "git repository"),
    ({"./café.txt": b"a", "./café.txt": b"b"}, "only by case"),          # NFC vs NFD: one file on macOS
    ({"./a​b.txt": b"x"}, "invisible"),
])
def test_inspect_refuses_more(tmp_path, files, why):
    base = _tar(tmp_path / "b.tar", BASE)
    new = _tar(tmp_path / "n.tar", {**BASE, **files})
    assert H.inspect(base, new, str(tmp_path / "out")) == 3
    problems = " ".join(json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))["problems"])
    assert why in problems, problems


def test_mount_mode_watches_nested_paths(tmp_path):
    proj, store, quar = tmp_path / "p", tmp_path / "s", tmp_path / "q"
    (proj / "sub").mkdir(parents=True)
    store.mkdir()
    H.backup(str(proj), str(store))
    (proj / "sub" / ".claude").mkdir()
    (proj / "sub" / ".claude" / "settings.json").write_text('{"hooks": {}}')
    assert H.restore(str(proj), str(store), str(quar)) == ["created: sub/.claude/settings.json"]
    assert not (proj / "sub" / ".claude" / "settings.json").exists()


@pytest.mark.skipif(__import__("os").name == "nt", reason="symlinks need privileges on Windows")
def test_mount_mode_restores_a_symlink(tmp_path):
    proj, store, quar = tmp_path / "p", tmp_path / "s", tmp_path / "q"
    (proj / ".githooks").mkdir(parents=True)
    (proj / ".githooks" / "real").write_text("x")
    (proj / ".githooks" / "link").symlink_to("real")
    store.mkdir()
    H.backup(str(proj), str(store))
    (proj / ".githooks" / "link").unlink()
    (proj / ".githooks" / "link").symlink_to("/etc/passwd")
    assert H.restore(str(proj), str(store), str(quar)) == ["changed: .githooks/link"]
    assert (proj / ".githooks" / "link").is_symlink() and __import__("os").readlink(proj / ".githooks" / "link") == "real"


def test_mounts_use_the_files_own_spelling(tmp_path):
    proj, empty = tmp_path / "p", tmp_path / "e"
    proj.mkdir()
    empty.mkdir()
    (proj / "Jenkinsfile").write_text("pipeline {}")
    (proj / "notes.md").write_text("n")
    pairs = H.mounts(str(proj), str(empty))
    assert f"{H.host_path(str(proj / 'Jenkinsfile'))}:/work/Jenkinsfile:ro" in pairs
    assert not any("notes.md" in x for x in pairs)
