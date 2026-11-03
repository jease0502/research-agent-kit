#!/usr/bin/env python3
"""A small behaviour-tree executor: declarative tree file, tick model, structured trace. Standard library only.

Tree file (JSON). Every node has "type" and "name"; the path of a node is the names from the root joined by "/".
  {"type": "Sequence", "name": ..., "children": [...]}   children in order until one is not SUCCESS
  {"type": "Fallback", "name": ..., "children": [...]}   children in order until one is not FAILURE
  {"type": "Condition", "name": ..., "call": optional}   a registered function; truthy -> SUCCESS, else FAILURE
  {"type": "Action", "name": ..., "call": optional}      a registered function returning a status
  {"type": "Retry", "name": ..., "times": N, "child": {...}}
        ticks the child again on FAILURE, up to N attempts in the same tick (for synchronous actions such as
        "create in the next zone"); RUNNING and SUCCESS pass through
  {"type": "Timeout", "name": ..., "seconds": S, "since": T, "child": {...}}
        FAILURE without ticking the child once S seconds have passed since T (a blackboard time); otherwise the
        child's status. "since" is required while this is a pilot: a Timeout that keeps its own start time
        restarts after it fires and is never halted when its branch stops being ticked (cross-review of 534dfdd)
"call" names the registered function (default: "name"). Numbers may be "$key" to read the blackboard.

Every tick is reactive: it starts at the root, and state that must survive between ticks lives on the blackboard,
not in the nodes. A leaf returns a status, or (status, reason).
Exceptions are not statuses: they are recorded in the trace as ERROR and re-raised, so a guard that raises stops
the whole tree instead of being read as "this branch failed, try the next one".

The tree is data the agent must not change: load_tree() refuses a tree whose canonical hash differs from the
one the caller pins, and the plugin's hook refuses edits to the tree folder.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

SUCCESS, FAILURE, RUNNING = "SUCCESS", "FAILURE", "RUNNING"
STATUSES = (SUCCESS, FAILURE, RUNNING)
_KEYS = {
    "Sequence": {"children"}, "Fallback": {"children"}, "Condition": {"call"}, "Action": {"call"},
    "Retry": {"times", "child"}, "Timeout": {"seconds", "since", "child"},
}
_REQUIRED = {"Sequence": {"children"}, "Fallback": {"children"}, "Retry": {"times", "child"},
             "Timeout": {"seconds", "since", "child"}}


class TreeError(Exception):
    pass


def canonical_sha256(spec) -> str:
    """Hash of the tree as data (sorted keys, no whitespace): line endings and formatting do not change it."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class Tree:
    def __init__(self, spec: dict, registry: dict[str, Callable], clock: Callable[[], float] = time.time):
        self.spec, self.registry, self.clock = spec, registry, clock
        self.n = 0                        # ticks so far
        self.trace: list[dict] = []       # records of the last tick
        self._check(spec, "")

    # ------------------------------------------------------------ validation

    def _check(self, node, parent: str) -> None:
        if not isinstance(node, dict) or node.get("type") not in _KEYS or not isinstance(node.get("name"), str) \
                or not node["name"] or "/" in node["name"]:
            raise TreeError(f"bad node under {parent or '<root>'}: {str(node)[:80]}")
        path = f"{parent}/{node['name']}" if parent else node["name"]
        extra = set(node) - {"type", "name"} - _KEYS[node["type"]]
        missing = _REQUIRED.get(node["type"], set()) - set(node)
        if extra or missing:
            raise TreeError(f"{path}: unknown keys {sorted(extra)} / missing keys {sorted(missing)}")
        if node["type"] in ("Condition", "Action"):
            if node.get("call", node["name"]) not in self.registry:
                raise TreeError(f"{path}: no registered function {node.get('call', node['name'])!r}")
        elif node["type"] in ("Sequence", "Fallback"):
            names = [c.get("name") for c in node["children"]] if isinstance(node["children"], list) else None
            if not names or len(set(names)) != len(names):
                raise TreeError(f"{path}: children must be a non-empty list with distinct names")
            for c in node["children"]:
                self._check(c, path)
        else:
            self._check(node["child"], path)

    # ------------------------------------------------------------ ticking

    def tick(self, bb: dict) -> str:
        self.n += 1
        self.trace = []
        return self._tick(self.spec, "", bb)

    def _num(self, v, bb: dict) -> float:
        if isinstance(v, str) and v.startswith("$"):
            v = bb[v[1:]]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TreeError(f"not a number: {v!r}")
        return v

    def _record(self, path: str, status: str, reason: str = "") -> str:
        rec = {"tick": self.n, "path": path, "status": status}
        if reason:
            rec["reason"] = reason
        self.trace.append(rec)
        return status

    def _tick(self, node: dict, parent: str, bb: dict) -> str:
        path = f"{parent}/{node['name']}" if parent else node["name"]
        t = node["type"]
        if t in ("Condition", "Action"):
            try:
                r = self.registry[node.get("call", node["name"])](bb)
            except Exception as e:
                self._record(path, "ERROR", f"{type(e).__name__}: {e}")
                raise
            reason = ""
            if isinstance(r, tuple):
                r, reason = r
            if t == "Condition":
                r = SUCCESS if r else FAILURE
            elif r not in STATUSES:
                raise TreeError(f"{path} returned {r!r}, not a status")
            return self._record(path, r, reason)
        if t in ("Sequence", "Fallback"):
            stop_on = FAILURE if t == "Sequence" else SUCCESS
            for c in node["children"]:
                s = self._tick(c, path, bb)
                if s in (stop_on, RUNNING):
                    return self._record(path, s, f"at {c['name']}")
            return self._record(path, SUCCESS if t == "Sequence" else FAILURE, "all children")
        if t == "Retry":
            times = int(self._num(node["times"], bb))
            for i in range(times):
                s = self._tick(node["child"], path, bb)
                if s != FAILURE:
                    return self._record(path, s, f"attempt {i + 1} of {times}")
            return self._record(path, FAILURE, f"{times} attempts failed")
        # Timeout
        secs = self._num(node["seconds"], bb)
        elapsed = self.clock() - self._num(node["since"], bb)
        if elapsed >= secs:
            return self._record(path, FAILURE, f"timed out: {elapsed:.0f}s >= {secs:.0f}s")
        s = self._tick(node["child"], path, bb)
        return self._record(path, s, f"{elapsed:.0f}s of {secs:.0f}s")


def load_tree(path: Path, key: str, registry: dict[str, Callable], sha256: str,
              clock: Callable[[], float] = time.time) -> Tree:
    """Tree `key` of the JSON file at `path`, refused unless its canonical hash is `sha256`."""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if key not in spec:
        raise TreeError(f"{path} has no tree {key!r}")
    got = canonical_sha256(spec[key])
    if got != sha256:
        raise TreeError(f"tree {key!r} in {path} has hash {got[:12]}..., expected {sha256[:12]}...: "
                        "the tree is not to be edited by the agent; a deliberate change updates the pinned hash")
    return Tree(spec[key], registry, clock)


def write_trace(f: Path, records: list[dict], **extra) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps({**extra, **r}, ensure_ascii=False) + "\n")


def leaf_at(records: list[dict]) -> dict | None:
    """The deepest leaf of a tick that did not succeed: where the tree is waiting or stuck. None when the tick
    succeeded at the root (the tree is done; a Condition that failed on the way is not a place it waits)."""
    if records and records[-1]["path"].count("/") == 0 and records[-1]["status"] == SUCCESS:
        return None
    leaves = [r for r in records if "/" in r["path"] and r["status"] != SUCCESS]
    leaves = [r for r in leaves if not any(o["path"].startswith(r["path"] + "/") for o in records)]
    return leaves[-1] if leaves else None
