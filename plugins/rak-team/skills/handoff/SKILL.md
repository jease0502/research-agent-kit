---
name: handoff
description: Keep a shared task list (tasks.json) and an append-only progress log (progress.md) so work survives session restarts, crashes and handovers between sessions; resume from them at the start of a session, and recover a dead session's state from its transcript. Use at session start, when taking over another session's work, before a session ends, or when several sessions share a project.
---

# handoff

Sessions end: context runs out, the machine reboots, a session crashes, work changes hands. Whatever existed only in a session's context is gone. This skill keeps the state in two files in the repository:

| File | What it is | Who writes it |
|---|---|---|
| `tasks.json` | the task list: id, title, status, owner, dependencies, notes, evidence | only `scripts/tasks.py`, under a lock, replaced atomically |
| `progress.md` | one line per change, never rewritten | `scripts/tasks.py` appends to it; people may add lines at the end |

Statuses: `open` → `claimed` → `done`. A claimed task can also become `blocked` (with a reason) or go back to `open` with `release`. A task that will not be done is `dropped` with a reason. Nothing is deleted.

## Session start: resume first

```bash
python <skill>/scripts/tasks.py resume          # unfinished tasks + the last 20 progress lines
```

Read it **before** doing anything else. In particular:

- do not start work that a `claimed` task already covers;
- do not re-decide something the progress log records as decided.

## While working

```bash
python <skill>/scripts/tasks.py claim T7 --who <your-name>
python <skill>/scripts/tasks.py note  T7 --who <your-name> --text "gate passed on 3/3 seeds; training"
python <skill>/scripts/tasks.py done  T7 --who <your-name> --evidence "commit abc123; results/T7/verdict.json"
python <skill>/scripts/tasks.py block T7 --who <your-name> --why "needs the user's decision on the budget"
```

What the tool enforces:

- **`done` requires `--evidence`.** Give a commit, a result file or a log path. "Done" without a pointer is a claim, not a result. The next session must be able to open the evidence without asking you.
- **One owner per task.** Claiming a task someone else holds fails. If the owner is gone, they or the lead must `release` it first. Do not edit the JSON by hand to take it over.
- **Dependencies are respected.** A task whose dependencies are not `done` cannot be claimed.
- Name yourself consistently (`--who`) with the name other sessions use to address you.

Write a `note` whenever something would be expensive to rediscover: a decision and who made it (the user's words, quoted, with the time), a dead end, a number, where an output lives.

## Before the session ends

1. Every task you hold must be one of:
   - `done`, with evidence;
   - `blocked`, with the reason;
   - released with `release`, plus a `note` saying how far you got.
2. Commit `tasks.json` and `progress.md` **with explicit paths**: `git commit -m "…" -- tasks.json progress.md`. Other sessions may have staged files in the shared index, and a bare `git commit` would send theirs too.

## Recovering a session that died without a handoff

```bash
python <skill>/scripts/session_digest.py ~/.claude/projects/<project>/<session-id>.jsonl 6
```

It prints the session's first and last user messages and its last assistant messages, with timestamps. From that, write the missing `note`s, then `release` the tasks it held, so they can be claimed again. Transcripts contain everything that session saw, so read the digest before pasting it anywhere.

## Notes

- `tasks.py init` creates both files. Put them at the repository root, or pass `--dir`.
- A lock file `tasks.json.lock` exists only during a write. If a crash leaves one behind, it is ignored after two minutes.
- `progress.md` is a log. To correct a line, append a new line that says what was wrong; do not edit the old one. The same rule holds for results: corrections are added, never rewritten.
