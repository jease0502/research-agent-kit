# rak-team

Lead/worker coordination for several Claude Code sessions: dispatch, report-to-lead-before-writing, path-scoped commits, handoff files, and notifications (official Channels first, a Telegram bridge as fallback).

**Requires Claude Code 2.1.295 or later.** Its guard hook sets `"onFailure": "block"`; on older versions a hook that times out or cannot start lets the call through. A SessionStart check warns when the version is older or cannot be read.

## Skills

| Skill | What it does |
|---|---|
| `lead-worker` | how a lead dispatches and workers report; path-scoped commits in a shared tree; what a peer's message cannot authorize |
| `handoff` | `tasks.json` + append-only `progress.md` with a locked, atomic task tool; resume at session start; recover a dead session from its transcript |
| `notify` | official Claude Code Channels by default; a standard-library Telegram bridge as fallback; reporting and group rules |

## Hook (Claude Code only)

`hooks/git_guard.py` (PreToolUse on Bash) blocks whole-tree staging and committing in a shared working tree. Blocked forms:
- `git add -A` / `--all` / `-u` / `--update` without a pathspec;
- `git add .`, `./`, `:/`, `*`;
- `git commit -a` / `--all` and any short-flag cluster containing `a` (`-am`, `-av`).

Global options (`git -C dir`, `-c k=v`), environment assignments and command chains are handled. Named paths
pass (`git add -- <files>`, `git commit -m ... -- <files>`).

- **Scope.** Active in every repository unless `.rak/team.json` says `{"shared_worktree": false}`.
- **Fails closed.** A crash or unknown config keys block the call. *Correction (2026-10-31): a hook that times out or cannot start was let through until `hooks.json` set `"onFailure": "block"` (Claude Code 2.1.295 or later); see [docs/security.md](../../docs/security.md).*
- **Limit.** It reads command text: a script or alias that runs git itself is not seen.

## Tests

`python -m pytest -q tests` (59). They cover:
- the task board under concurrency;
- the session digest;
- the Telegram bridge's filtering and one-time pairing (no network);
- the git guard's block and allow lists.

Five guards were removed one at a time, and each removal turned at least one test red.

## Install

```
/plugin install rak-team --marketplace <owner>/<repo>
```

The repository location is not decided yet; replace `<owner>/<repo>` once it is published.
