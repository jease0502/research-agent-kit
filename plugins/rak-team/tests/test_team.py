"""rak-team scripts: the shared task list under concurrency, its rules, the session digest, and the
Telegram bridge's message filtering (no network: the Bot API is replaced)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "skills"
sys.path.insert(0, str(SKILLS / "handoff" / "scripts"))
sys.path.insert(0, str(SKILLS / "notify" / "scripts"))
import session_digest as SD  # noqa: E402
import tasks as T  # noqa: E402
import tg  # noqa: E402

TASKS = SKILLS / "handoff" / "scripts" / "tasks.py"


@pytest.fixture
def board(tmp_path):
    assert T.main(["--dir", str(tmp_path), "init"]) == 0
    return tmp_path


def run(d, *args):
    return T.main(["--dir", str(d), *args])


def tasks_of(d):
    return {t["id"]: t for t in json.loads((d / "tasks.json").read_text(encoding="utf-8"))["tasks"]}


def test_lifecycle_and_progress_log(board):
    assert run(board, "add", "train arm A") == 0
    assert run(board, "add", "write results", "--depends", "T1") == 0
    assert run(board, "claim", "T2", "--who", "w1") == 1            # dependency not done
    assert run(board, "claim", "T1", "--who", "w1") == 0
    assert run(board, "claim", "T1", "--who", "w2") == 1            # held by someone else
    assert run(board, "done", "T1", "--who", "w1") == 1             # no evidence
    assert run(board, "done", "T1", "--who", "w2", "--evidence", "x") == 1   # not the owner
    assert run(board, "done", "T1", "--who", "w1", "--evidence", "commit abc; out/a.json") == 0
    assert run(board, "claim", "T2", "--who", "w2") == 0
    t = tasks_of(board)
    assert t["T1"]["status"] == "done" and t["T1"]["evidence"].startswith("commit abc")
    log = (board / "progress.md").read_text(encoding="utf-8")
    assert "[w1] T1 done: commit abc; out/a.json" in log and "[w2] T2 claimed" in log


def test_block_release_drop(board):
    run(board, "add", "x")
    run(board, "claim", "T1", "--who", "w1")
    assert run(board, "block", "T1", "--who", "w1") == 1            # needs --why
    assert run(board, "block", "T1", "--who", "w1", "--why", "needs a decision") == 0
    assert run(board, "release", "T1", "--who", "w2") == 1
    assert run(board, "release", "T1", "--who", "w1") == 0
    assert tasks_of(board)["T1"]["status"] == "open"
    assert run(board, "drop", "T1", "--who", "lead") == 1           # needs --why
    assert run(board, "drop", "T1", "--who", "lead", "--why", "superseded by T9") == 0
    assert tasks_of(board)["T1"]["status"] == "dropped"


def test_done_task_cannot_be_dropped_or_reclaimed(board):
    run(board, "add", "x")
    run(board, "claim", "T1", "--who", "w1")
    run(board, "done", "T1", "--who", "w1", "--evidence", "e")
    assert run(board, "drop", "T1", "--who", "lead", "--why", "w") == 1
    assert run(board, "claim", "T1", "--who", "w2") == 1


def test_concurrent_claims_have_exactly_one_winner(board):
    run(board, "add", "contested")
    procs = [subprocess.Popen([sys.executable, str(TASKS), "--dir", str(board), "claim", "T1", "--who", f"w{i}"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
    codes = [p.wait(timeout=60) for p in procs]
    assert codes.count(0) == 1, codes
    t = tasks_of(board)["T1"]
    assert t["status"] == "claimed" and t["owner"] in {f"w{i}" for i in range(8)}
    assert not (board / "tasks.json.lock").exists()


def test_concurrent_adds_lose_nothing(board):
    procs = [subprocess.Popen([sys.executable, str(TASKS), "--dir", str(board), "add", f"task {i}", "--id", f"A{i}"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(10)]
    assert [p.wait(timeout=60) for p in procs] == [0] * 10
    assert set(tasks_of(board)) == {f"A{i}" for i in range(10)}
    lines = [ln for ln in (board / "progress.md").read_text(encoding="utf-8").splitlines() if " added: " in ln]
    assert len(lines) == 10


def test_stale_lock_is_ignored(board, monkeypatch):
    import os
    import time
    lock = board / "tasks.json.lock"
    lock.write_text("dead", encoding="utf-8")
    old = time.time() - T.STALE_AFTER - 5
    os.utime(lock, (old, old))
    assert run(board, "add", "after a crash") == 0


def test_live_lock_times_out(board, monkeypatch):
    (board / "tasks.json.lock").write_text("alive", encoding="utf-8")
    monkeypatch.setattr(T, "LOCK_TIMEOUT", 0.3)
    assert run(board, "add", "blocked") == 1


def test_resume(board, capsys):
    run(board, "add", "open one")
    run(board, "add", "finished")
    run(board, "claim", "T2", "--who", "w1")
    run(board, "done", "T2", "--who", "w1", "--evidence", "e")
    capsys.readouterr()
    run(board, "resume")
    out = capsys.readouterr().out
    head = out.split("## Last")[0]
    assert "open one" in head and "finished" not in head
    assert "T2 done: e" in out


def test_init_refuses_overwrite(board):
    assert run(board, "init") == 1


def test_session_digest(tmp_path):
    f = tmp_path / "s.jsonl"
    rows = [
        {"type": "user", "timestamp": "t1", "message": {"role": "user", "content": "please train arm A"}},
        {"type": "user", "timestamp": "t2", "message": {"role": "user", "content": "<system-reminder>x"}},
        {"type": "assistant", "timestamp": "t3",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "arm A gate passed"},
                                                       {"type": "tool_use", "name": "Bash"}]}},
        "not json",
    ]
    f.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows), encoding="utf-8")
    out = SD.digest(str(f))
    assert "please train arm A" in out and "arm A gate passed" in out
    assert "system-reminder" not in out


# ── Telegram bridge filtering ──

def msg(uid, chat_id, chat_type, text, sender=None):
    return {"update_id": uid, "message": {"message_id": uid, "date": 0, "text": text,
                                          "chat": {"id": chat_id, "type": chat_type},
                                          "from": {"id": sender if sender is not None else chat_id,
                                                   "username": f"u{sender or chat_id}"}}}


NOW = 1_000_000.0


def paired_env_with_code(ttl_min=15):
    env = {"TG_BOT_TOKEN": "x"}
    code = tg.new_pairing(env, ttl_min, now=NOW)
    return env, code


def test_stranger_who_writes_first_is_not_paired():
    env, code = paired_env_with_code()
    lines, off, changed = tg.collect(env, [msg(1, 222, "private", "hi, I found your bot"),
                                           msg(2, 111, "private", code),
                                           msg(3, 222, "private", "me again")], now=NOW + 60)
    assert env["TG_CHAT_ID"] == "111" and changed and off == 4
    assert [t for _, t in lines] == ["[paired] this chat (111) is now the user"]   # the stranger is never printed
    assert "TG_PAIR_SHA256" not in env and "TG_PAIR_EXPIRES" not in env


def test_code_is_one_time():
    env, code = paired_env_with_code()
    tg.collect(env, [msg(1, 111, "private", code)], now=NOW + 1)
    tg.collect(env, [msg(2, 222, "private", code)], now=NOW + 2)              # leaked or replayed code
    assert env["TG_CHAT_ID"] == "111"


def test_wrong_or_expired_code_or_group_does_not_pair():
    env, code = paired_env_with_code(ttl_min=15)
    tg.collect(env, [msg(1, 111, "private", "ABCD-EFGH")], now=NOW + 1)
    tg.collect(env, [msg(2, -5, "group", code, sender=111)], now=NOW + 2)      # code posted in a group
    assert "TG_CHAT_ID" not in env
    tg.collect(env, [msg(3, 111, "private", code)], now=NOW + 15 * 60 + 1)     # too late
    assert "TG_CHAT_ID" not in env
    assert tg.pairing_state(env, now=NOW + 15 * 60 + 1).startswith("code expired")


def test_code_format_tolerated_and_not_stored_in_clear():
    env, code = paired_env_with_code()
    assert code.replace("-", "") not in "".join(env.values())
    tg.collect(env, [msg(1, 111, "private", "  " + code.lower().replace("-", " ") + "\n")], now=NOW + 1)
    assert env["TG_CHAT_ID"] == "111"


def test_new_pairing_forgets_user_and_group():
    env = {"TG_BOT_TOKEN": "x", "TG_CHAT_ID": "111", "TG_GROUP_ID": "-5"}
    tg.new_pairing(env, now=NOW)
    assert "TG_CHAT_ID" not in env and "TG_GROUP_ID" not in env and "TG_PAIR_SHA256" in env


def test_cli_setup_prints_code_and_stores_hash(tmp_path):
    r = subprocess.run([sys.executable, str(SKILLS / "notify" / "scripts" / "tg.py"), "setup", "123:abc", "--ttl-min", "5"],
                       capture_output=True, text=True, env={**__import__("os").environ, "TG_HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    code = [l for l in r.stdout.splitlines() if l.startswith("PAIRING CODE:")][0].split()[2]
    stored = (tmp_path / "tg.env").read_text()
    assert "TG_PAIR_SHA256=" + tg.code_hash(code) in stored and code not in stored and "TG_CHAT_ID" not in stored


def test_bridge_group_set_by_user_only():
    env = {"TG_BOT_TOKEN": "x", "TG_CHAT_ID": "111"}
    lines, _, _ = tg.collect(env, [msg(1, -5, "group", "from someone else", sender=333)])
    assert "TG_GROUP_ID" not in env and lines == []            # a stranger cannot pick the group
    lines, _, _ = tg.collect(env, [msg(2, -5, "group", "from the user", sender=111),
                                   msg(3, -5, "group", "teammate", sender=333),
                                   msg(4, -9, "group", "other group", sender=111)])
    assert env["TG_GROUP_ID"] == "-5"
    assert [t for _, t in lines] == ["[group] u111: from the user", "[group] u333: teammate"]
