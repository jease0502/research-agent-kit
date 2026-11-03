# rak-discipline

```
/plugin install rak-discipline --marketplace <owner>/<repo>
```

Rules for running experiments that hold up, written as code where possible:

```
collision-search -> prereg -> freeze -> gate (controls) -> run -> verdict -> results doc -> erratum -> lesson
```

| Skill | What it does |
|---|---|
| `collision-search` | Search prior work by mechanism, decide what collides, reposition instead of abandoning |
| `prereg` | Write the question, arms, seeds, gate, criteria, predictions, budget and limits; freeze them |
| `gate` | Positive control, negative control, control reproduction, do-nothing baseline, before reading results |
| `verdict` | The registered reading rule as a frozen script: raw comparisons, three states, hashes, write-once |
| `erratum` | Correct by appending; the original sentence stays |
| `lesson` | Turn a closed line (including failures) into a lesson whose numbers come from logs by script |

Templates: `templates/prereg.md`, `verdict.py`, `erratum.md`, `lesson.md`, `build_logs.py`, `discipline.json`.

**Requires Claude Code 2.1.295 or later.** Its guard hook sets `"onFailure": "block"`; on older versions a hook that times out or cannot start lets the call through. A SessionStart check warns when the version is older or cannot be read.

## Enforcement

Opt in per project by creating `.rak/discipline.json` (copy `templates/discipline.json`). Without it
the hook does nothing.

| Rule | Primary enforcement | Second line |
|---|---|---|
| 1. No experiment launch without a frozen prereg | PreToolUse hook on Bash: commands matching `experiment_patterns` need `RAK_PREREG=<id>` with the prereg, the verdict script and every `frozen_files:` entry and every file under `frozen_trees:` unchanged since freezing | Call `verify_frozen` at the top of training entry points; the verdict script re-checks all frozen files before `gate` and `judge` |
| 2. No reading results until the gate passes | The frozen verdict script refuses `judge` unless `.rak/gates/<id>.json` is `PASS` and bound to the frozen hashes | PreToolUse hook blocks `verdict_patterns` commands while the gate is not PASS |
| 3. Committed results are append-only | git pre-commit check (`rak_discipline.py install-git-hook`): committed body lines must survive in order | PreToolUse hook on Edit/MultiEdit/Write, and on Bash commands that edit/delete a results file in place |

The hook fails closed: a crash or a config with unknown keys blocks the call instead of letting it through.
*Correction (2026-10-31): a hook that times out or cannot start was let through until `hooks.json` set `"onFailure": "block"`, which needs Claude Code 2.1.295 or later. See [docs/security.md](../../docs/security.md).*

Tests (`python -m unittest discover -s tests -v` from this folder): 51 cases (47 for the guards, including 8 for `frozen_files` and 6 for `frozen_trees`, each rule
with block and allow cases plus the known gaps below; 4 for the lesson number extractor). The suite was checked against deliberately broken guards
(edit rule disabled, freeze check disabled, verdict ignoring the gate): each break made tests fail.

## Limits (read before relying on it)

- Claude Code documents hook `if`-style filtering as best effort; hard rules belong in the permission
  system. This hook matches **command text**. It does not see what a script does once it runs.
  - Rule 1 misses launches whose text does not match a pattern (a renamed script, a wrapper, `python -c`).
  - Rule 3's Bash check misses writes from inside a program (the test suite shows a `python -c` rewrite
    passing the hook and being rejected by the pre-commit check).
- Git hooks can be skipped with `--no-verify`. Run the same check in CI on push for a hard guarantee.
- Freezing proves the files did not change after the freeze commit, not that the freeze came before the data.
- The hook needs `python` on PATH (Windows installs often have `python` but not `python3`).
- Hooks are Claude Code specific. Skills follow the agentskills.io format and are usable in other agents,
  where the CLI and verdict-script checks still apply but nothing blocks tool calls.

## State

`.rak/frozen/<id>.json` and `.rak/gates/<id>.json` are part of the record. Commit them.
