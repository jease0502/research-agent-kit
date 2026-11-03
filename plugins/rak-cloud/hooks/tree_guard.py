#!/usr/bin/env python3
"""PreToolUse guard (Claude Code hook): the agent does not edit rak-cloud's lifecycle trees.

The job lifecycle (create, wait, pull, verify, delete) is a behaviour tree in <plugin>/trees/, run by code. The
spending decisions in it (which zones, when to delete, when to give up) are the owner's, not the agent's. This
hook blocks Edit / Write / MultiEdit / NotebookEdit on any path under <plugin>/trees/, and Bash command segments
that name a tree file unless they start with a read-only command. rak_cloud.py also pins each tree's hash, so an
edit that gets past this hook stops the run instead of changing it.
A deliberate change to a tree is made by a person (or with this plugin disabled), with the pin updated.
Exit 2 blocks; a crash blocks too (fail closed).
Limit: Bash is matched on command text. A script that writes the file itself is not seen (the pin still is).

The rules are C1 and C2 of the policy engine (python/rak/policy, vendored in _vendor/rak_policy); this file is the
Claude Code adapter.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_vendor"))
import rak_policy as policy  # noqa: E402


def block(msg: str) -> None:
    print(f"rak-cloud blocked this: {msg}\nThe lifecycle tree is the owner's spending policy and is not edited by "
          "the agent. Describe the change you want; a person makes it and updates the pin in rak_cloud.py.",
          file=sys.stderr)
    sys.exit(2)


def plugin_root() -> str:
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent)


def main() -> None:
    try:
        event = policy.claude_code_event(json.load(sys.stdin), env={"PLUGIN_ROOT": plugin_root()})
        d = policy.evaluate(event, plugin="rak-cloud")
        if d.decision == "ask":
            print(policy.claude_code_ask(d, "rak-cloud"))
            sys.exit(0)
        if d.decision != "allow":
            block(d.reason)
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        print(f"rak-cloud tree guard error ({type(e).__name__}: {e}); blocking.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
