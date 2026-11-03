#!/usr/bin/env python3
"""PreToolUse guard (Claude Code hook): no whole-tree staging or committing in a shared working tree.

When several sessions share one checkout they share one git index. `git add -A`, `git add .` and
`git commit -a` sweep up whatever the other sessions have changed or staged, and the resulting commit looks
like yours. This hook blocks, in Bash commands:
  git add  -A | --all | -u | --update | --no-ignore-removal   (unless limited by an explicit pathspec)
  git add  . | ./ | :/ | :(top) | *                            (whole-tree pathspecs)
  git commit -a | --all | any short-flag cluster containing a (-am, -av, ...)
Stage and commit named paths instead:  git add -- <files>;  git commit -m "..." -- <files>

Active in every git repository unless <repo>/.rak/team.json says {"shared_worktree": false} (for a repo only
one session ever uses). Exit 2 blocks; a crash blocks too (fail closed), and hooks.json sets onFailure: block for
a hook that times out or cannot start.
Limit: it reads command text. A script that runs git itself, or an alias, is not seen.

The rule itself is rule T1-T3 of the policy engine (python/rak/policy, vendored in _vendor/rak_policy); this file is
the Claude Code adapter: hook JSON in, the engine's decision out as an exit code and a message.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_vendor"))
import rak_policy as policy  # noqa: E402


def block(msg: str) -> None:
    print(f"rak-team blocked this git command: {msg}\n"
          "Several sessions share this index. Name your paths: git add -- <files>; git commit -m '...' -- <files>",
          file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        event = policy.claude_code_event(data, env={"CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR")})
        d = policy.evaluate(event, plugin="rak-team")
        if d.decision == "ask":
            print(policy.claude_code_ask(d, "rak-team"))
            sys.exit(0)
        if d.decision != "allow":
            block(d.reason)
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        print(f"rak-team git guard error ({type(e).__name__}: {e}); blocking. Fix the guard or .rak/team.json.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
