"""Model profiles: format, required fields, no credentials, the environment they build, and the positive control's
judging, all offline. No key and no network: the control runs against a stand-in for `claude`."""
from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path

import pytest

from rak import models as M

IDS = M.profile_ids()
VENDORS = {"anthropic", "deepseek", "kimi", "qwen", "glm", "minimax", "doubao"}


def test_every_vendor_has_a_profile():
    assert set(IDS) == VENDORS


@pytest.mark.parametrize("pid", IDS)
def test_profile_is_valid(pid):
    p = M.load(pid)
    assert M.validate(p) == []
    assert p["id"] == pid


@pytest.mark.parametrize("pid", sorted(VENDORS - {"anthropic"}))
def test_third_party_profiles_say_untested_and_carry_the_switches(pid):
    p = M.load(pid)
    assert p["tested_by_us"] is False
    assert p["status_note"].startswith("Not tested by us")
    assert p["env"]["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"
    assert p["env"]["ENABLE_TOOL_SEARCH"] == "false"
    assert p["endpoint"].startswith("https://")


@pytest.mark.parametrize("pid", IDS)
def test_no_key_material_in_profile_files(pid):
    text = (M.PROFILE_DIR / f"{pid}.json").read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{8,}", text)
    for target in M.KEY_TARGETS:                          # a key variable may be named as key_target, never given a value
        assert f'"{target}":' not in text


def _good():
    return json.loads((M.PROFILE_DIR / "deepseek.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate, expect", [
    (lambda p: p.pop("data_policy"), "missing field data_policy"),
    (lambda p: p.update(extra=1), "unknown field extra"),
    (lambda p: p["env"].update(ANTHROPIC_AUTH_TOKEN="x"), "must not set ANTHROPIC_AUTH_TOKEN"),
    (lambda p: p["env"].update(ANTHROPIC_BASE_URL="https://x"), "must not set ANTHROPIC_BASE_URL"),
    (lambda p: p["env"].pop("ENABLE_TOOL_SEARCH"), "ENABLE_TOOL_SEARCH"),
    (lambda p: p.update(tested_by_us=True), "tested_by_us"),
    (lambda p: p.update(endpoint="http://api.example.com"), "https"),
    (lambda p: p.update(endpoint="https://{Ws}.example.com"), "placeholders"),
    (lambda p: p.update(key_env="DEEPSEEK"), "key_env"),
    (lambda p: p["models"].pop("subagent"), "models"),
    (lambda p: p["claude_code"].update(pin="2.0.14"), "pin must be"),
    (lambda p: p["limits"].append({"text": "x", "source": ""}), "limits"),
    (lambda p: p["data_policy"].update(source=None, verified="primary"), "not verified"),
    (lambda p: p.update(status_note="Not tested by us. key sk-abcdefgh12345678"), "credential"),
    (lambda p: p.update(status_note="Not tested by us. " + "a1" * 20), "credential"),
])
def test_validator_catches(mutate, expect):
    p = _good()
    mutate(p)
    errs = M.validate(p)
    assert any(expect in e for e in errs), errs


def test_long_env_names_are_not_credentials():
    assert M.validate(_good()) == []                     # CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC is 40 characters


ENV = {"PATH": "/bin", "HOME": "/h", "ANTHROPIC_BASE_URL": "https://stale.example", "ANTHROPIC_API_KEY": "stale",
       "CLAUDE_CODE_MESSAGING_TOKEN": "t", "GIT_ASKPASS": "a", "HF_TOKEN": "h", "RAK_KEY_DEEPSEEK": "k-deep"}


def test_env_takes_key_from_the_named_variable_and_drops_the_rest():
    env = M.build_env(M.load("deepseek"), ENV)
    assert env["ANTHROPIC_API_KEY"] == "k-deep"
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "deepseek-v4-pro"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "deepseek-v4-pro"
    for k in ("CLAUDE_CODE_MESSAGING_TOKEN", "GIT_ASKPASS", "HF_TOKEN", "RAK_KEY_DEEPSEEK"):
        assert k not in env
    assert env["PATH"] == "/bin"


def test_missing_key_raises_and_stale_shell_values_do_not_leak():
    with pytest.raises(M.ProfileError, match="RAK_KEY_KIMI"):
        M.build_env(M.load("kimi"), ENV)


def test_anthropic_profile_can_use_the_login():
    env = M.build_env(M.load("anthropic"), ENV)
    assert "ANTHROPIC_BASE_URL" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_MODEL"] == "claude-opus-5-5"


def test_endpoint_placeholder_needs_its_variable():
    p = M.load("qwen")
    with pytest.raises(M.ProfileError, match="RAK_QWEN_WORKSPACE_ID"):
        M.build_env(p, {**ENV, "RAK_KEY_QWEN": "k"})
    with pytest.raises(M.ProfileError):
        M.build_env(p, {**ENV, "RAK_KEY_QWEN": "k", "RAK_QWEN_WORKSPACE_ID": "evil.com/x?"})
    env = M.build_env(p, {**ENV, "RAK_KEY_QWEN": "k", "RAK_QWEN_WORKSPACE_ID": "ws-1"})
    assert env["ANTHROPIC_BASE_URL"] == "https://ws-1.ap-southeast-1.maas.aliyuncs.com/apps/anthropic"


def test_env_command_masks_the_key(capsys):
    import os
    os.environ["RAK_KEY_DEEPSEEK"] = "k-very-secret"
    try:
        assert M.main(["env", "deepseek"]) == 0
    finally:
        del os.environ["RAK_KEY_DEEPSEEK"]
    out = capsys.readouterr().out
    assert "k-very-secret" not in out and '"ANTHROPIC_API_KEY": "***"' in out


# ---- the positive control, judged against a stand-in for claude

FAKE = textwrap.dedent('''
    import json, os, re, sys
    if "--version" in sys.argv:
        print("2.1.316 (Claude Code)"); sys.exit(0)
    mode = os.environ["FAKE_MODE"]
    prompt = sys.stdin.read()
    ok_cmd = re.search(r"run: (echo bash-ok-\\w+)", prompt).group(1)
    hooked_cmd = re.search(r"run: (echo RAK_CONTROL_BLOCK-\\w+)", prompt).group(1)
    def use(name, inp, parent=None):
        print(json.dumps({"type": "assistant", "parent_tool_use_id": parent,
                          "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}))
    def result(text):
        print(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": text}]}}))
    print(json.dumps({"type": "system", "subtype": "init", "model": os.environ["ANTHROPIC_MODEL"]}))
    use("Edit", {"file_path": "a.txt"}); open("a.txt", "w").write("after\\n")
    if mode == "rewrites":
        use("Bash", {"command": "cd x && " + ok_cmd}); result("Permission to use Bash has been denied")
    elif mode == "bash_refused":
        use("Bash", {"command": ok_cmd}); result("Permission to use Bash has been denied")
    else:
        use("Bash", {"command": ok_cmd}); result(ok_cmd[5:] + "\\nShell cwd was reset to /tmp/x")
    use("Agent", {"prompt": "write"})
    use("Write", {"file_path": "sub_ok.txt"}, parent=None if mode == "main_writes_sub" else "t1")
    open("sub_ok.txt", "w").write("sub-ok\\n")
    use("Bash", {"command": hooked_cmd})
    if mode == "hook_fails":
        result(hooked_cmd[5:])
    elif mode == "blocked_by_mode":
        result("Permission to use Bash has been denied")
    else:
        result([{"type": "text", "text": "PreToolUse:Bash hook error: blocked by the control hook"}])
    use("Read", {"file_path": "secret.txt"})
    if mode == "deny_fails":
        s = open("secret.txt").read()
        print(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": s}]}}))
    print(json.dumps({"type": "result", "num_turns": 7, "total_cost_usd": 0.01,
                      "modelUsage": {os.environ["ANTHROPIC_MODEL"]: {}}, "permission_denials": [{}]}))
''')


@pytest.fixture
def fake(tmp_path):
    f = tmp_path / "fake_claude.py"
    f.write_text(FAKE, encoding="utf-8")
    return f


@pytest.mark.parametrize("mode, verdict, broken", [
    ("ok", "PASS", None), ("hook_fails", "FAIL", "hook_blocks"), ("deny_fails", "FAIL", "deny_holds"),
    ("main_writes_sub", "FAIL", "subagent"),
    ("blocked_by_mode", "FAIL", "hook_blocks"),                 # stopped, but not by the hook
    ("rewrites", "FAIL", "bash"),                               # the model added cd ... &&
    ("bash_refused", "FAIL", "bash")])                          # run as written, still refused                 # the file is there, but the main agent wrote it
def test_control_judges_from_files_and_transcript(fake, tmp_path, monkeypatch, mode, verdict, broken):
    monkeypatch.setenv("FAKE_MODE", mode)
    env = {**ENV, "FAKE_MODE": mode}
    monkeypatch.setattr(M, "ENV_KEEP", M.ENV_KEEP + ("FAKE_MODE", "SYSTEMROOT"))
    import os
    env.update({k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")})
    rec = M.control(M.load("deepseek"), env, tmp_path / "out", str(fake), timeout=60)
    assert rec["verdict"] == verdict, rec["checks"]
    assert rec["models_reported"] == ["deepseek-v4-pro"]
    assert rec["claude_code_version"] == "2.1.316" and rec["version_matches_pin"]
    assert rec["endpoint_host"] == "api.deepseek.com"
    kind = {"ok": None, "hook_fails": "enforcement", "deny_fails": "enforcement", "blocked_by_mode": "enforcement",
            "main_writes_sub": "model", "rewrites": "model", "bash_refused": "enforcement"}[mode]
    assert rec["failure_kind"] == kind, rec["why"]
    if broken:
        assert rec["checks"][broken] == "fail" and broken in rec["why"]
        assert all(v == "pass" for k, v in rec["checks"].items() if k != broken)
    written = json.loads(Path(rec["written_to"]).read_text(encoding="utf-8"))
    assert "k-deep" not in json.dumps(written)
    transcript = Path(rec["written_to"]).with_name(Path(rec["written_to"]).stem + ".transcript.jsonl")
    assert "RAK-SECRET-" not in transcript.read_text(encoding="utf-8")


def test_control_without_attempts_is_not_a_pass(tmp_path, monkeypatch):
    f = tmp_path / "lazy.py"
    f.write_text('import sys,json\nif "--version" in sys.argv: print("2.1.316"); sys.exit(0)\n'
                 'print(json.dumps({"type":"result","num_turns":1}))\n', encoding="utf-8")
    import os
    env = {**ENV, **{k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}}
    rec = M.control(M.load("deepseek"), env, tmp_path / "out", str(f), timeout=60)
    assert rec["verdict"] == "FAIL"
    assert set(rec["checks"].values()) == {"not exercised"}


def test_old_claude_code_fails_the_control(tmp_path):
    f = tmp_path / "old.py"
    f.write_text('import sys\nprint("2.0.14 (Claude Code)")\n', encoding="utf-8")
    assert M.claude_version(str(f)) == "2.0.14"
    assert M._version("2.0.14") < M._version(M.load("glm")["claude_code"]["min"])


def test_control_settings_gate_is_fail_closed(tmp_path):
    s = M.control_settings(tmp_path / "gate.py")
    h = s["hooks"]["PreToolUse"][0]
    assert h["matcher"] == "Bash" and h["hooks"][0]["onFailure"] == "block"
    assert "Read(secret.txt)" in s["permissions"]["deny"]
    assert s["permissions"]["defaultMode"] == "dontAsk"


def test_model_override_is_applied_and_recorded(fake, tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("FAKE_MODE", "ok")
    monkeypatch.setattr(M, "ENV_KEEP", M.ENV_KEEP + ("FAKE_MODE",))
    env = {**ENV, "FAKE_MODE": "ok",
           **{k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP")}}
    rec = M.control(M.load("deepseek"), env, tmp_path / "out", str(fake), timeout=60, model="cheap-1")
    assert rec["model_override"] == "cheap-1"
    assert set(rec["models_configured"].values()) == {"cheap-1"}
    assert rec["models_reported"] == ["cheap-1"]
    with pytest.raises(M.ProfileError):
        M.control(M.load("deepseek"), env, tmp_path / "out", str(fake), model="x; rm -rf /")
