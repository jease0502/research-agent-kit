"""bt.py, the behaviour-tree executor, on its own: node semantics, validation, the hash pin, the trace."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bt  # noqa: E402

S, F, R = bt.SUCCESS, bt.FAILURE, bt.RUNNING


def leaf(name, call=None, t="Action"):
    d = {"type": t, "name": name}
    if call:
        d["call"] = call
    return d


def seq(name, *c):
    return {"type": "Sequence", "name": name, "children": list(c)}


def fb(name, *c):
    return {"type": "Fallback", "name": name, "children": list(c)}


class Semantics(unittest.TestCase):
    def setUp(self):
        self.log = []

    def reg(self, **results):
        def make(n, r):
            def f(bb):
                self.log.append(n)
                return r(bb) if callable(r) else r
            return f
        return {n: make(n, r) for n, r in results.items()}

    def test_sequence_stops_at_first_non_success(self):
        t = bt.Tree(seq("root", leaf("a"), leaf("b"), leaf("c")), self.reg(a=S, b=R, c=S))
        self.assertEqual(t.tick({}), R)
        self.assertEqual(self.log, ["a", "b"])
        self.assertEqual(t.trace[-1], {"tick": 1, "path": "root", "status": R, "reason": "at b"})

    def test_fallback_stops_at_first_non_failure(self):
        t = bt.Tree(fb("root", leaf("a"), leaf("b"), leaf("c")), self.reg(a=F, b=S, c=S))
        self.assertEqual(t.tick({}), S)
        self.assertEqual(self.log, ["a", "b"])
        t2 = bt.Tree(fb("root", leaf("a"), leaf("b")), self.reg(a=F, b=F))
        self.assertEqual(t2.tick({}), F)

    def test_condition_is_truthiness(self):
        t = bt.Tree(fb("root", leaf("c", t="Condition"), leaf("x")), self.reg(c=lambda bb: bb["v"], x=R))
        self.assertEqual(t.tick({"v": 1}), S)
        self.assertEqual(t.tick({"v": 0}), R)

    def test_reactive_every_tick_starts_at_the_root(self):
        t = bt.Tree(seq("root", leaf("a"), leaf("b")), self.reg(a=S, b=R))
        t.tick({}); t.tick({})
        self.assertEqual(self.log, ["a", "b", "a", "b"])
        self.assertEqual(t.n, 2)

    def test_retry_reticks_on_failure_within_one_tick(self):
        bb = {"i": 0, "n": 3}

        def attempt(bb):
            bb["i"] += 1
            return S if bb["i"] == 2 else F
        t = bt.Tree({"type": "Retry", "name": "r", "times": "$n", "child": leaf("x")}, {"x": attempt})
        self.assertEqual(t.tick(bb), S)
        self.assertEqual(bb["i"], 2)
        self.assertEqual(t.trace[-1]["reason"], "attempt 2 of 3")
        bb = {"i": 10, "n": 3}
        self.assertEqual(t.tick(bb), F)
        self.assertEqual(bb["i"], 13)

    def test_retry_passes_running_through(self):
        t = bt.Tree({"type": "Retry", "name": "r", "times": 5, "child": leaf("x")}, self.reg(x=R))
        self.assertEqual(t.tick({}), R)
        self.assertEqual(self.log, ["x"])

    def test_timeout_with_since_on_the_blackboard(self):
        now = [100.0]
        t = bt.Tree({"type": "Timeout", "name": "t", "seconds": "$s", "since": "$at", "child": leaf("x")},
                    self.reg(x=R), clock=lambda: now[0])
        bb = {"s": 60, "at": 100.0}
        self.assertEqual(t.tick(bb), R)
        now[0] = 159.0
        self.assertEqual(t.tick(bb), R)
        now[0] = 160.0
        self.assertEqual(t.tick(bb), F)
        self.assertEqual(self.log, ["x", "x"])              # the child is not ticked once timed out
        self.assertIn("timed out", t.trace[-1]["reason"])

    def test_exception_is_recorded_and_reraised(self):
        def boom(bb):
            raise ValueError("guard refused")
        t = bt.Tree(fb("root", leaf("a"), leaf("b")), {"a": boom, "b": lambda bb: S})
        with self.assertRaises(ValueError):
            t.tick({})
        self.assertEqual(t.trace, [{"tick": 1, "path": "root/a", "status": "ERROR", "reason": "ValueError: guard refused"}])

    def test_bad_status_raises(self):
        t = bt.Tree(seq("root", leaf("a")), {"a": lambda bb: "OK"})
        with self.assertRaises(bt.TreeError):
            t.tick({})

    def test_leaf_at_finds_the_waiting_leaf(self):
        t = bt.Tree(seq("root", leaf("a"), fb("f", leaf("c", t="Condition"), leaf("w"))),
                    self.reg(a=S, c=False, w=(R, "waiting for x")))
        t.tick({})
        self.assertEqual(bt.leaf_at(t.trace), {"tick": 1, "path": "root/f/w", "status": R, "reason": "waiting for x"})


class Validation(unittest.TestCase):
    def bad(self, spec, reg=None):
        with self.assertRaises(bt.TreeError):
            bt.Tree(spec, reg if reg is not None else {"a": lambda bb: S})

    def test_rejects_malformed_trees(self):
        self.bad({"type": "Parallel", "name": "p", "children": []})
        self.bad(leaf("nope"))                                            # not registered
        self.bad(seq("s"))                                                # no children
        self.bad(seq("s", leaf("a"), leaf("a")))                          # duplicate names: paths must be unique
        self.bad({"type": "Action", "name": "a", "retries": 3})           # unknown key
        self.bad({"type": "Retry", "name": "r", "child": leaf("a")})      # missing times
        self.bad({"type": "Action", "name": "a/b", "call": "a"})          # "/" would break paths


class Pin(unittest.TestCase):
    def test_load_refuses_a_changed_tree_and_ignores_formatting(self):
        spec = {"main": seq("root", leaf("a"))}
        h = bt.canonical_sha256(spec["main"])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.json"
            f.write_text(json.dumps(spec, indent=4).replace("\n", "\r\n"), encoding="utf-8")   # CRLF checkout
            bt.load_tree(f, "main", {"a": lambda bb: S}, h)
            spec["main"]["children"].append(leaf("a", t="Condition") | {"name": "skip_check", "call": "a"})
            f.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(bt.TreeError):
                bt.load_tree(f, "main", {"a": lambda bb: S}, h)


if __name__ == "__main__":
    unittest.main()
