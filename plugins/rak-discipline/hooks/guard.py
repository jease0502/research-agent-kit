#!/usr/bin/env python3
"""PreToolUse guard for rak-discipline (Claude Code hook). Exit 2 blocks the tool call.

Rules (only active when the project has .rak/discipline.json):
  1. A Bash command matching `experiment_patterns` must carry RAK_PREREG=<id>, and <id> must be
     frozen with its prereg and verdict script unchanged since freezing.
  2. A Bash command matching `verdict_patterns` (reading results) is blocked unless the gate for
     its RAK_PREREG id is PASS (and recorded against the frozen files).
  3. Edit / MultiEdit / Write on a file matching `results_globs` is blocked if any committed line
     (HEAD version, frontmatter exempt) would be removed or rewritten. Bash commands that name such
     a file together with an in-place editing / deleting construct are blocked too.

This is a second line of defence. The verdict script enforces rule 2 itself, and the git pre-commit
hook enforces rule 3 on whatever reached the index. See README "Limits" for what this cannot catch.
If the hook itself crashes it blocks (exit 2) rather than letting the call through; hooks.json sets
onFailure: block for a hook that times out or cannot start.

The rules are D1-D6 of the policy engine (python/rak/policy, vendored in _vendor/rak_policy); this file is the
Claude Code adapter. What "frozen", "gate" and "append-only" mean stays in scripts/rak_discipline.py, which the
adapter hands to the engine as the discipline backend.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))
sys.path.insert(0, str(PLUGIN / "_vendor"))
import rak_discipline as rd  # noqa: E402
import rak_policy as policy  # noqa: E402


def block(msg: str) -> None:
    print(f"rak-discipline blocked this call: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        event = policy.claude_code_event(data, env={"CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR")},
                                         backends={"discipline": rd})
        d = policy.evaluate(event, plugin="rak-discipline")
        if d.decision == "ask":
            print(policy.claude_code_ask(d, "rak-discipline"))
            sys.exit(0)
        if d.decision != "allow":
            block(d.reason)
    except SystemExit:
        raise
    except Exception as e:  # fail closed: a broken guard must not wave calls through
        block(f"guard error ({type(e).__name__}: {e}); fix the guard or .rak/discipline.json, do not disable it")


if __name__ == "__main__":
    main()
