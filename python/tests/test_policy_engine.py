"""The policy engine on its own: rules file pinned and validated, first deny wins, errors, the Claude Code adapter's
mapping, and the vendored copies in the plugins."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rak.policy import engine
from rak.policy.adapters import claude_code_event

REPO = Path(__file__).resolve().parents[2]


def test_rules_load_and_every_plugin_hook_has_rules():
    rules = engine.load_rules()
    assert {r["plugin"] for r in rules} == {"rak-discipline", "rak-team", "rak-cloud", "rak-policy"}
    assert [r["id"] for r in rules] == ["D1-D2", "D3-D4", "D5", "D6", "T1-T3", "C1", "C2", "P1"]


def test_changed_rules_file_is_refused(tmp_path):
    data = json.loads(engine.RULES_FILE.read_text(encoding="utf-8"))
    data["rules"] = [r for r in data["rules"] if r["id"] != "T1-T3"]              # a rule quietly dropped
    f = tmp_path / "rules.json"; f.write_text(json.dumps(data, indent=3).replace("\n", "\r\n"))
    with pytest.raises(engine.PolicyError, match="not to be edited"):
        engine.load_rules(f)
    data = json.loads(engine.RULES_FILE.read_text(encoding="utf-8"))
    f.write_text(json.dumps(data, indent=3).replace("\n", "\r\n"))             # formatting and CRLF only: same hash
    assert len(engine.load_rules(f)) == 8


@pytest.mark.parametrize("bad", [{"check": "nope"}, {"decision": "allow"}, {"on": ["Bash"]}, {"on": []}, {"extra": 1}])
def test_malformed_rules_are_refused(tmp_path, bad):
    data = json.loads(engine.RULES_FILE.read_text(encoding="utf-8"))
    data["rules"][0] = {**data["rules"][0], **bad}
    f = tmp_path / "rules.json"; f.write_text(json.dumps(data))
    with pytest.raises(engine.PolicyError):
        engine.load_rules(f, sha256=engine.canonical_sha256(data))


def test_first_deny_in_file_order_wins_and_unknown_tools_are_allowed():
    calls = []
    engine.CHECKS["t.a"] = lambda e: calls.append("a") or None
    engine.CHECKS["t.b"] = lambda e: calls.append("b") or "b says no"
    engine.CHECKS["t.c"] = lambda e: calls.append("c") or "c says no"
    try:
        rules = [{"id": i, "plugin": "p", "on": ["shell"], "check": f"t.{i}", "decision": "deny", "covers": ""}
                 for i in "abc"]
        d = engine.evaluate(engine.Event("shell", {"command": "x"}), rules=rules)
        assert (d.decision, d.rule, d.reason, calls) == ("deny", "b", "b says no", ["a", "b"])
        assert engine.evaluate(engine.Event("other:Read", {}), rules=rules).decision == "allow"
        assert engine.evaluate(engine.Event("shell", {}), plugin="q", rules=rules).decision == "allow"
    finally:
        for k in ("t.a", "t.b", "t.c"):
            engine.CHECKS.pop(k)


def test_errors_propagate_and_evaluate_closed_denies(tmp_path):
    (tmp_path / ".rak").mkdir(); (tmp_path / ".rak/team.json").write_text('{"typo": 1}')
    ev = engine.Event("shell", {"command": "git status"}, cwd=str(tmp_path))
    with pytest.raises(ValueError):
        engine.evaluate(ev, plugin="rak-team")
    d = engine.evaluate_closed(ev, plugin="rak-team")
    assert d.decision == "deny" and "unknown keys" in d.reason


def test_claude_code_adapter_mapping():
    e = claude_code_event({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/r"}, {})
    assert (e.tool, e.args, e.cwd, e.native_tool) == ("shell", {"command": "ls"}, "/r", "Bash")
    e = claude_code_event({"tool_name": "Edit", "tool_input": {"file_path": "a", "old_string": "x", "new_string": "y"}}, {})
    assert e.tool == "file.edit" and e.args["edits"] == [{"file_path": "a", "old_string": "x", "new_string": "y"}]
    e = claude_code_event({"tool_name": "MultiEdit", "tool_input": {"file_path": "a", "edits": [{"old_string": "x"}]}}, {})
    assert e.args == {"path": "a", "edits": [{"old_string": "x"}]}
    e = claude_code_event({"tool_name": "Write", "tool_input": {"file_path": "a", "content": "c"}}, {})
    assert (e.tool, e.args) == ("file.write", {"path": "a", "content": "c"})
    e = claude_code_event({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "n.ipynb"}}, {})
    assert (e.tool, e.args) == ("notebook.edit", {"path": "n.ipynb"})
    assert claude_code_event({"tool_name": "Read", "tool_input": None}, {}).tool == "other:Read"


def test_vendored_copies_match_the_source():
    r = subprocess.run([sys.executable, str(REPO / "scripts/vendor_policy.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    plugins_with_hooks = {p.parent.parent.name for p in REPO.glob("plugins/*/hooks/hooks.json")}
    vendored = {p.parent.parent.name for p in REPO.glob("plugins/*/_vendor/rak_policy")}
    assert vendored == plugins_with_hooks


# ---- step 2: the MCP server's allowlist, the policy-file rule, ask in the Claude Code adapters ----

def test_unknown_tools_are_denied_in_allowlist_mode():
    ev = engine.Event("other:Glob", {})
    assert engine.evaluate(ev).decision == "allow"                       # hooks: unchanged
    d = engine.evaluate(ev, unknown="deny")
    assert (d.decision, d.rule) == ("deny", "allowlist") and "other:Glob" in d.reason
    assert engine.evaluate_closed(ev, unknown="deny").decision == "deny"
    assert engine.evaluate(engine.Event("file.read", {"path": "x"}, cwd="."), unknown="deny").decision == "allow"


def test_evaluate_closed_takes_rules():
    engine.CHECKS["t.boom"] = lambda e: 1 / 0
    try:
        rules = [{"id": "b", "plugin": "p", "on": ["shell"], "check": "t.boom", "decision": "deny", "covers": ""}]
        d = engine.evaluate_closed(engine.Event("shell", {"command": "x"}), rules=rules)
        assert d.decision == "deny" and "ZeroDivisionError" in d.reason
    finally:
        engine.CHECKS.pop("t.boom")


@pytest.mark.parametrize("rel", ["python/rak/policy/rules.json", "plugins/rak-team/_vendor/rak_policy/engine.py",
                                 ".rak/frozen/x.json", ".rak/gates/x.json", ".rak/discipline.json",
                                 "plugins/rak-team/hooks/git_guard.py", "plugins/rak-team/hooks/hooks.json",
                                 "python/rak/mcp_server.py", ".mcp.json", ".claude/settings.json",
                                 ".claude/settings.local.json", "sub/.rak/team.json",
                                 # cross-review of 53f7221: manifests, hook backends, git hooks, CI, the scanner
                                 ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                                 "plugins/rak-discipline/scripts/rak_discipline.py",
                                 "plugins/rak-cloud/scripts/rak_cloud.py", "scripts/hooks/pre-commit",
                                 ".github/workflows/ci.yml", "scripts/scan_private.py",
                                 # what else runs as a hook, CI or agent config, or switches a check off
                                 ".github/actions/setup/action.yml", ".husky/pre-commit", ".githooks/pre-push",
                                 ".pre-commit-config.yaml", "lefthook.yml", ".gitlab-ci.yml", ".circleci/config.yml",
                                 "azure-pipelines.yml", "Jenkinsfile", ".gemini/settings.json", ".codex/config.toml",
                                 ".rak-scan-allow", "plugins/rak-cloud/trees/lifecycle.json"])
def test_policy_files_are_not_writable(tmp_path, rel):
    for tool, args in (("file.write", {"content": ""}), ("file.edit", {"edits": []})):
        ev = engine.Event(tool, {"path": str(tmp_path / rel), **args}, cwd=str(tmp_path))
        d = engine.evaluate(ev, plugin="rak-policy")
        assert (d.decision, d.rule) == ("deny", "P1"), (tool, rel)
    ev = engine.Event("file.write", {"path": rel, "content": ""}, cwd=str(tmp_path))       # relative to cwd
    assert engine.evaluate(ev, plugin="rak-policy").rule == "P1"
    assert engine.evaluate(engine.Event("file.read", {"path": str(tmp_path / rel)}, cwd=str(tmp_path)),
                           plugin="rak-policy").decision == "allow"


@pytest.mark.parametrize("rel", ["notes.md", "src/policy.py", "rak/policy.md", "hooks.md", "docs/rules.json"])
def test_ordinary_files_are_writable(tmp_path, rel):
    ev = engine.Event("file.write", {"path": str(tmp_path / rel), "content": ""}, cwd=str(tmp_path))
    assert engine.evaluate(ev, plugin="rak-policy").decision == "allow"


def test_the_engine_itself_is_protected_wherever_it_lives(tmp_path):
    src = Path(engine.__file__).resolve().parent / "checks_git.py"
    ev = engine.Event("file.edit", {"path": str(src), "edits": []}, cwd=str(tmp_path))
    assert engine.evaluate(ev, plugin="rak-policy").rule == "P1"


def test_claude_code_ask_reply():
    from rak.policy.adapters import claude_code_ask
    out = json.loads(claude_code_ask(engine.Decision("ask", "X1", "why not"), "rak-team"))
    assert out == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                          "permissionDecisionReason": "rak-team (X1): why not"}}


HOOK_FILES = {"rak-discipline": REPO / "plugins/rak-discipline/hooks/guard.py",
              "rak-team": REPO / "plugins/rak-team/hooks/git_guard.py",
              "rak-cloud": REPO / "plugins/rak-cloud/hooks/tree_guard.py"}


@pytest.mark.parametrize("plugin", sorted(HOOK_FILES))
def test_hooks_answer_ask_with_permission_decision(plugin, monkeypatch, capsys):
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location(f"askhook_{plugin}", HOOK_FILES[plugin])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m.policy, "evaluate", lambda *a, **k: engine.Decision("ask", "X1", "why not"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"},
                                                             "cwd": str(REPO)})))
    with pytest.raises(SystemExit) as e:
        m.main()
    out = capsys.readouterr()
    assert e.value.code == 0, out.err
    assert json.loads(out.out)["hookSpecificOutput"]["permissionDecision"] == "ask"


# ---- maintainer 2026-11-01 (after the sandbox review of 2528365): nested names, spellings, and the sandbox's list

@pytest.mark.parametrize("rel", [
    "sub/.claude/settings.json", "sub/.github/workflows/x.yml", "a/b/.mcp.json", "pkg/.husky/pre-commit",
    # what the sandbox protects and P1 did not
    ".envrc", "sub/.envrc", ".vscode/tasks.json", "sub/.vscode/tasks.json", ".idea/workspace.xml",
    ".devcontainer/devcontainer.json", ".gitmodules", ".gitattributes", "sub/.gitattributes", ".git/config",
    # spellings Windows resolves to the real name (when the folder does not exist yet, realpath cannot help)
    ".claude./settings.json", ".claude /settings.json", ".Claude/settings.json", "CLAUDE~1/settings.json",
    ".envrc.", ".github./workflows/x.yml", "sub/.vscode./tasks.json"])
def test_policy_files_at_any_depth_and_in_any_spelling(tmp_path, rel):
    ev = engine.Event("file.write", {"path": str(tmp_path / rel), "content": ""}, cwd=str(tmp_path))
    d = engine.evaluate(ev, plugin="rak-policy")
    assert (d.decision, d.rule) == ("deny", "P1"), rel


@pytest.mark.parametrize("rel", ["docs/claude.md", "my.claude/x", "envrc.md", "src/vscode.py", "github.md",
                                 "sub/hooks/x.py", "scripts/build.py"])
def test_names_that_only_look_alike_stay_writable(tmp_path, rel):
    ev = engine.Event("file.write", {"path": str(tmp_path / rel), "content": ""}, cwd=str(tmp_path))
    assert engine.evaluate(ev, plugin="rak-policy").decision == "allow", rel


def test_protected_name_is_one_function_for_both_layers():
    """The sandbox's host.py judges names with the same function (templates/sandbox)."""
    from rak.policy.checks_policy import protected_name
    assert protected_name("sub/.claude/settings.json") and protected_name("GIT~1/config")
    assert protected_name("docs/notes.md") is None


# cross-review of 149894e: HFS+ ignores default-ignorable code points in names, and macOS normalizes Unicode, so
# these name .git or .claude there. protected_name puts each component in NFC and drops invisible characters first.
@pytest.mark.parametrize("rel", ["sub/.g‌it/config", ".﻿claude/settings.json", ".git͏/config",
                                 ".claude️/settings.json", ".en​vrc", "GIT‍~1/config",
                                 ".vscode󠄀/tasks.json"])
def test_policy_names_with_invisible_characters(tmp_path, rel):
    from rak.policy.checks_policy import protected_name
    assert protected_name(rel), repr(rel)
    ev = engine.Event("file.write", {"path": str(tmp_path / rel), "content": ""}, cwd=str(tmp_path))
    assert engine.evaluate(ev, plugin="rak-policy").rule == "P1", repr(rel)


@pytest.mark.parametrize("rel", ["café.md", "café.md", "資料/筆記.md", "emoji❤️.md"])
def test_ordinary_unicode_names_stay_writable(rel):
    from rak.policy.checks_policy import protected_name
    assert protected_name(rel) is None, repr(rel)


# re-review of 36894b9: a protected folder's name used for a file (a gitlink ".git" file, "gitdir: ...") counts too
@pytest.mark.parametrize("rel", ["sub/.git", "tools/.GIT", ".git", "sub/.claude", "pkg/.husky", "scripts/hooks"])
def test_protected_folder_names_count_as_files_too(rel):
    from rak.policy.checks_policy import protected_name
    assert protected_name(rel), rel
