"""The policy engine: a tool-call event in, a decision out. Agent-independent; standard library only.

    event    = Event(tool="shell", args={"command": "git add -A"}, cwd="/repo", env={...})
    decision = evaluate(event, plugin="rak-team")      # Decision("deny", "T1-T3", "...") or Decision("allow")

Rules are data (rules.json: id, plugin, the tools it applies to, the check it calls, the decision); checks are code
(the CHECKS registry). The rule file is pinned: load_rules() refuses one whose canonical hash is not RULES_SHA256.
Rules are evaluated in file order and the first deny wins, which keeps the order the hooks used to check in.
No rule applies -> allow: these rules sit on top of the host's own permissions. A check that raises is not a
decision: evaluate() lets the exception through so each adapter blocks with its own message (fail closed), and
evaluate_closed() turns it into a deny for callers without one (the MCP server).
A tool outside TOOLS is allowed by default, which suits a hook (it sees only the tools its matcher names). The MCP
server passes unknown="deny": there the tool list is an allowlist, so a tool added without a rule cannot run
unchecked.

Tool names are the engine's, not an agent's: shell {command}, file.read {path}, file.write {path, content},
file.edit {path, edits: [{old_string, new_string, replace_all}]}, notebook.edit {path}.
docs/policy-engine.md has the inventory and the design.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import checks_discipline, checks_git, checks_policy, checks_trees

RULES_FILE = Path(__file__).resolve().parent / "rules.json"
RULES_SHA256 = "77fe52d53919dfe41c0f4f6fcea6882751357ae167233c85a3e13203d7313dd3"
TOOLS = {"shell", "file.read", "file.write", "file.edit", "notebook.edit"}
DECISIONS = {"deny", "ask"}
CHECKS = {
    "discipline.launch": checks_discipline.launch,
    "discipline.verdict": checks_discipline.verdict,
    "discipline.results_shell": checks_discipline.results_shell,
    "discipline.results_edit": checks_discipline.results_edit,
    "git.whole_tree": checks_git.git_whole_tree,
    "trees.file": checks_trees.tree_file,
    "trees.shell": checks_trees.tree_shell,
    "policy.protected": checks_policy.protected_file,
}


class PolicyError(Exception):
    pass


@dataclass
class Event:
    tool: str
    args: dict
    cwd: str | None = None
    env: dict = field(default_factory=dict)            # only what checks may read, set by the adapter
    native_tool: str = ""                               # the agent's own name, for messages
    backends: dict = field(default_factory=dict)        # e.g. {"discipline": <rak_discipline module>}


@dataclass
class Decision:
    decision: str                                       # "allow" | "deny" | "ask"
    rule: str = ""
    reason: str = ""


def canonical_sha256(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_rules(path: Path = RULES_FILE, sha256: str | None = None) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    want = RULES_SHA256 if sha256 is None else sha256
    got = canonical_sha256(data)
    if got != want:
        raise PolicyError(f"{path} has hash {got[:12]}..., expected {want[:12]}...: the rules are not to be edited by "
                          "the agent; a deliberate change updates RULES_SHA256 in the same commit")
    rules = data["rules"]
    ids = [r.get("id") for r in rules]
    if len(set(ids)) != len(ids):
        raise PolicyError("rule ids must be unique")
    for r in rules:
        if set(r) != {"id", "plugin", "on", "check", "decision", "covers"}:
            raise PolicyError(f"rule {r.get('id')}: keys must be id, plugin, on, check, decision, covers")
        if r["check"] not in CHECKS or r["decision"] not in DECISIONS or not set(r["on"]) <= TOOLS or not r["on"]:
            raise PolicyError(f"rule {r['id']}: unknown check, decision or tool")
    return rules


def evaluate(event: Event, plugin: str | None = None, rules: list[dict] | None = None,
             unknown: str = "allow") -> Decision:
    """The first rule (in file order) that applies to the event and returns a reason decides; else allow.
    A tool outside TOOLS gets `unknown` ("allow" for hooks, "deny" for the MCP server). Exceptions from a check
    propagate."""
    if event.tool not in TOOLS:
        if unknown == "allow":
            return Decision("allow")
        return Decision("deny", "allowlist", f"tool {event.tool!r} is not one the policy knows ({sorted(TOOLS)})")
    for r in rules if rules is not None else load_rules():
        if (plugin is None or r["plugin"] == plugin) and event.tool in r["on"]:
            why = CHECKS[r["check"]](event)
            if why:
                return Decision(r["decision"], r["id"], why)
    return Decision("allow")


def evaluate_closed(event: Event, plugin: str | None = None, rules: list[dict] | None = None,
                    unknown: str = "allow") -> Decision:
    """evaluate(), with any error turned into a deny."""
    try:
        return evaluate(event, plugin, rules, unknown)
    except Exception as e:
        return Decision("deny", "error", f"policy error ({type(e).__name__}: {e}); blocking")
