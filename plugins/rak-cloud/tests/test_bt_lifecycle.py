"""The job lifecycle as behaviour trees (trees/lifecycle.json run by bt.py).

1. Every failure the lifecycle knows about ends in the branch meant for it, and the trace names the node.
2. Differential: the tree-driven create and waiter against the pre-tree implementation (legacy_rak_cloud.py, a
   frozen copy of rak_cloud.py at 47e424a) on randomized scenarios: the same printed lines, return values,
   exceptions, gcloud calls and bookkeeping, step by step.
3. The tree is pinned: an edited tree file stops the run, and the plugin's hook refuses edits to trees/.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
os.environ.setdefault("FAKE_GCLOUD_DIR", tempfile.gettempdir())   # fake_gcloud reads it on import; InProc sets its own
import bt  # noqa: E402
import fake_gcloud  # noqa: E402
import legacy_rak_cloud as lrc  # noqa: E402
import rak_cloud as rc  # noqa: E402
import test_cloud as tc  # noqa: E402

PLUGIN = HERE.parent


def leaf_paths(lines):
    return [json.loads(x) for x in lines]


class BranchEnv(tc.Env):
    """A recorded VM, its bucket folder and a waiter on a test clock."""
    NAME = "rak-w"

    def setUp(self):
        super().setUp()
        self.now = 1_000_000.0
        (self.fake / "instances.json").write_text(json.dumps({self.NAME: {"zone": "z-a", "status": "RUNNING"}}))
        rc.record_instance(self.root, self.NAME, "z-a")
        d = json.loads(rc.instances_file(self.root).read_text()); d[self.NAME]["created"] = self.now
        rc.instances_file(self.root).write_text(json.dumps(d))
        self.out = self.fake / "gcs/fake-bkt/rak" / self.NAME / "out"; self.out.mkdir(parents=True)
        self.w = rc.Waiter(self.cfg, self.g, self.root, self.NAME, clock=lambda: self.now, out=self.lines.append)

    job_outputs = tc.WaiterTests.job_outputs

    def at(self):
        return bt.leaf_at(self.w.tree.trace)

    def trace_file(self, name=None):
        return leaf_paths(rc.trace_file(self.root, name or self.NAME).read_text(encoding="utf-8").splitlines())

    def kw(self, k):
        return [l for l in self.lines if l.startswith(k)]


class Branches(BranchEnv):
    """One test per failure: the right branch, and a trace that points at the node."""

    # -- create

    def test_stockout_trace_shows_each_zone_attempt(self):
        self.knob(stockout_zones=["z-a"])
        self.assertEqual(rc.create(self.cfg, self.g, self.root, "rak-c", "gs://j/", yes=True, out=self.lines.append), "z-b")
        recs = [(r["path"], r["status"], r.get("reason", "")) for r in self.trace_file("rak-c")]
        self.assertEqual(recs[0], ("create/precheck", "SUCCESS", ""))
        self.assertEqual(recs[1][:2], ("create/zones/create_in_next_zone", "FAILURE"))
        self.assertIn("z-a: ", recs[1][2]); self.assertIn("ZONE_RESOURCE_POOL_EXHAUSTED", recs[1][2])
        self.assertEqual(recs[2], ("create/zones/create_in_next_zone", "SUCCESS", "z-b"))
        self.assertEqual(recs[3], ("create/zones", "SUCCESS", "attempt 2 of 2"))

    def test_stockout_everywhere_fails_at_the_zones_node(self):
        self.knob(stockout_zones=["z-a", "z-b"])
        with self.assertRaisesRegex(rc.CloudError, "every zone failed"):
            rc.create(self.cfg, self.g, self.root, "rak-c", "gs://j/", yes=True, out=self.lines.append)
        recs = self.trace_file("rak-c")
        self.assertEqual((recs[-2]["path"], recs[-2]["status"], recs[-2]["reason"]), ("create/zones", "FAILURE", "2 attempts failed"))

    def test_failed_precheck_stops_before_any_zone(self):
        self.knob(auth_ok=False)
        with self.assertRaisesRegex(rc.CloudError, "precheck failed"):
            rc.create(self.cfg, self.g, self.root, "rak-c", "gs://j/", yes=True, out=self.lines.append)
        self.assertEqual([(r["path"], r["status"]) for r in self.trace_file("rak-c")],
                         [("create/precheck", "FAILURE"), ("create", "FAILURE")])

    def test_guard_exception_is_not_a_branch_failure(self):
        """create_command refuses a name without the prefix: the whole create stops (ERROR), it does not try the
        next zone as it would after a stockout."""
        with self.assertRaisesRegex(rc.CloudError, "must start with"):
            rc.create(self.cfg, self.g, self.root, "other-x", "gs://j/", yes=True, out=self.lines.append)
        recs = self.trace_file("other-x")
        self.assertEqual([(r["path"], r["status"]) for r in recs],
                         [("create/precheck", "SUCCESS"), ("create/zones/create_in_next_zone", "ERROR")])

    def test_dry_run_writes_no_trace(self):
        rc.create(self.cfg, self.g, self.root, "rak-c", "gs://j/", yes=False, out=self.lines.append)
        self.assertFalse(rc.trace_file(self.root, "rak-c").exists())

    # -- wait

    def test_preempted_goes_to_salvage(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        (self.fake / "instances.json").write_text("{}")
        self.assertEqual(self.w.poll(), "gone_unverified")          # was "gone" before 2b (deliberate change)
        self.assertEqual(self.at(), None)                           # the tree ended: nothing is waiting
        r = [x for x in self.w.tree.trace if x["path"] == "wait/outcome/vm_gone/salvage_outputs"][0]
        self.assertEqual(r["status"], "SUCCESS"); self.assertIn("INCOMPLETE", r["reason"])

    def test_missing_file_waits_in_pull_and_verify(self):
        self.job_outputs(); self.knob(rsync_drop=["model.pt"])
        self.assertIsNone(self.w.poll())
        a = self.at()
        self.assertEqual((a["path"], a["status"]), ("wait/outcome/finished/pull_and_verify", "RUNNING"))
        self.assertIn("missing model.pt", a["reason"])
        self.assertFalse(any(x["path"].endswith("/delete_vm") for x in self.w.tree.trace))
        self.knob(rsync_drop=[])                                    # next tick: the retry is the next tick
        self.assertEqual(self.w.poll(), "done")
        self.assertEqual(self.w.bb["verified"], ["eval/summary.json", "model.pt"])

    def test_expired_credentials_wait_in_report_unknown_never_gone(self):
        self.job_outputs(); self.knob(auth_ok=False)
        (self.fake / "instances.json").write_text("{}")             # even if the VM really is gone
        for _ in range(3):
            self.assertIsNone(self.w.poll()); self.now += 600
        a = self.at()
        self.assertEqual((a["path"], a["status"]), ("wait/vm_known/report_unknown", "RUNNING"))
        self.assertIn("not treated as gone", a["reason"])
        self.assertFalse(any(x["path"].startswith("wait/outcome") for x in self.w.tree.trace))
        self.assertFalse(any(c[:3] == ["compute", "instances", "delete"] for c in self.calls()))

    def test_budget_stop_times_out_into_give_up(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.now += 13 * 3600; self.assertIsNone(self.w.poll())
        a = self.at()
        self.assertEqual((a["path"], a["status"]), ("wait/outcome/stop_requested/stop_or_give_up/stop_wait/await_stop", "RUNNING"))
        self.now += 25 * 60
        self.assertEqual(self.w.poll(), "stop_unconfirmed")
        t = {x["path"]: x for x in self.w.tree.trace}
        self.assertEqual(t["wait/outcome/stop_requested/stop_or_give_up/stop_wait"]["status"], "FAILURE")
        self.assertEqual(t["wait/outcome/stop_requested/stop_or_give_up/give_up_stop"]["status"], "SUCCESS")

    def test_delete_check_failed_waits_in_delete_vm(self):
        self.job_outputs(); self.knob(disk_left=True)
        self.assertIsNone(self.w.poll())
        a = self.at()
        self.assertEqual((a["path"], a["status"]),
                         ("wait/outcome/finished/delete_or_give_up/deleted/delete_vm", "RUNNING"))

    def test_running_job_waits_in_keep_waiting_and_trace_is_appended(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.w.poll(); self.w.poll()
        self.assertEqual(self.at()["path"], "wait/outcome/keep_waiting")
        recs = self.trace_file()
        self.assertEqual({r["tick"] for r in recs}, {1, 2})
        self.assertTrue(all(set(r) >= {"t", "tick", "path", "status"} for r in recs))


# ---------------------------------------------------------------- differential

class InProc:
    """The fake gcloud called in-process (the subprocess version is too slow for hundreds of scenarios)."""

    def __init__(self, fake_dir: Path):
        self.dir = fake_dir

    def __call__(self, *args, timeout=None, input=None):
        if json.loads((self.dir / "config.json").read_text()).get("gcloud_missing"):
            raise FileNotFoundError(2, "No such file or directory", "gcloud")   # what subprocess raises
        fake_gcloud.D = self.dir
        out, err = io.StringIO(), io.StringIO()
        old_argv, old_in = sys.argv, sys.stdin
        sys.argv, sys.stdin = ["gcloud", *args], io.StringIO(input or "")
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = fake_gcloud.main()
        finally:
            sys.argv, sys.stdin = old_argv, old_in
        return rc.Result(code, out.getvalue(), err.getvalue())


class Side:
    """One implementation in its own project and fake-cloud folder."""

    def __init__(self, mod, base: Path, cfg: dict):
        self.mod, self.base = mod, base
        self.root = base / "proj"; (self.root / ".rak").mkdir(parents=True)
        self.fake = base / "fake"; (self.fake / "gcs/fake-bkt/rak").mkdir(parents=True)
        self.cfg = dict(copy.deepcopy(cfg), local_dir=str(base / "pulled"))
        self.g = InProc(self.fake)
        self.lines, self.now = [], 1_000_000.0

    def knobs(self, **kw):
        (self.fake / "config.json").write_text(json.dumps({"images": {"isaac": 250}, "logs": [], **kw}))

    def norm(self, s: str) -> str:
        b = str(self.base)
        return s.replace(b.replace("\\", "\\\\"), "<T>").replace(b, "<T>").replace(b.replace("\\", "/"), "<T>")

    def out_lines(self):
        return [self.norm(" ".join(x.split(" ")[:1] + x.split(" ")[2:])) for x in self.lines]   # drop the timestamp

    def calls(self):
        f = self.fake / "calls.jsonl"
        return [[self.norm(a) for a in json.loads(x)] for x in f.read_text().splitlines()] if f.exists() else []

    def instances(self):
        f = rc.instances_file(self.root)
        return json.loads(f.read_text()) if f.exists() else None


VM_STATES = ["keep", "keep", "keep", "RUNNING", "TERMINATED", "GONE", "STOPPED", "SUSPENDED", "STOPPING",
             "PROVISIONING", "STAGING", "REPAIRING"]
OUTPUTS = ["keep", "keep", "keep", "good", "good_bin", "partial", "empty", "garbage", "tamper", "midrun", "none"]


def scenario_steps(rng: random.Random):
    late = rng.random() < 0.3      # near or past a budget line at the first poll: those branches get exercised
    sticky = rng.random() < 0.2    # a delete that keeps failing: the DELETE_ATTEMPTS limit gets reached
    for k in range(rng.randint(1, 10)):
        yield {
            "status": rng.choice([None, "RUNNING_TRAIN", "RUNNING_TRAIN", "DONE", "STOPPED_SYNCED", "FAIL_OOM"]),
            "outputs": rng.choice(OUTPUTS),
            "vm": rng.choice(VM_STATES),
            "knobs": {"auth_ok": rng.random() > 0.15, "rsync_drop": ["model.pt"] if rng.random() < 0.2 else [],
                      "disk_left": rng.random() < 0.15, "delete_fails": rng.random() < (0.9 if sticky else 0.1),
                      "net_fail": rng.random() < 0.05, "gcloud_missing": rng.random() < 0.02},
            "fault": rng.choices([None, "corrupt_instances", "disk_error"], [0.96, 0.02, 0.02])[0],
            "advance": rng.choice([8 * 3600, 12 * 3600, 13 * 3600]) if late and k == 0 else
            rng.choice([0, 60, 25 * 60, 30 * 60, 31 * 60, 2 * 3600, 5 * 3600]),   # 25 and 30 min: the stop-wait and stall edges
        }


FILES = {"model.pt": b"weights", "eval/summary.json": b'{"s": 1}', "log.txt": b"done\n"}


def write_manifest(out: Path, names, mode="  "):
    (out / "MANIFEST.sha256").write_text("".join(f"{rc.sha256_file(out / n)}{mode}./{n}\n" for n in names))


def apply_step(side: Side, name: str, step: dict):
    out = side.fake / "gcs/fake-bkt/rak" / name / "out"
    out.mkdir(parents=True, exist_ok=True)
    o = step["outputs"]
    if o != "keep":
        for n in [*FILES, "MANIFEST.sha256"]:
            (out / n).unlink(missing_ok=True)
    if o in ("good", "good_bin", "partial", "tamper", "midrun"):
        for n, data in FILES.items():
            (out / n).parent.mkdir(parents=True, exist_ok=True)
            (out / n).write_bytes(data)
        if o != "midrun":                       # a job cut off half way: some outputs, no manifest
            write_manifest(out, FILES, " *" if o == "good_bin" else "  ")
        if o == "partial":
            (out / "log.txt").unlink()
        if o == "tamper":
            (out / "model.pt").write_bytes(b"changed")
    elif o == "empty":
        (out / "MANIFEST.sha256").write_text("")
    elif o == "garbage":
        (out / "model.pt").write_bytes(b"weights")
        (out / "MANIFEST.sha256").write_text(f"{rc.sha256_file(out / 'model.pt')}  ./model.pt\nnot a manifest line\n")
    if step["status"] is None:
        (out / "status.txt").unlink(missing_ok=True)
    else:
        (out / "status.txt").write_text(step["status"] + "\n")
    f = side.fake / "instances.json"
    x = json.loads(f.read_text()) if f.exists() else {}
    if name in x and step["vm"] == "GONE":
        del x[name]
    elif name in x and step["vm"] != "keep":
        x[name]["status"] = step["vm"]
    f.write_text(json.dumps(x))
    side.knobs(**step["knobs"])
    if step["fault"] == "corrupt_instances":
        rc.instances_file(side.root).write_text("{not json")
    elif step["fault"] == "disk_error":
        local = Path(side.cfg["local_dir"]) / name
        if local.is_dir():
            shutil.rmtree(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text("a file where the pull folder should be")
    side.now += step["advance"]


def poll(side: Side, w):
    try:
        return w.poll()
    except Exception as e:                      # compared by type and message, paths normalized
        return ("raised", type(e).__name__, side.norm(str(e)))


def without(lines, *kws):
    return [l for l in lines if not l.startswith(kws)]


def instances_or_none(side: Side):
    try:
        return side.instances()
    except json.JSONDecodeError:
        return "corrupt"


class Differential(unittest.TestCase):
    NAME = "rak-d"
    N = 400

    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="rakbt-"))

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def sides(self, i):
        return [Side(m, self.t / f"{i}-{k}", tc.CFG) for k, m in (("old", lrc), ("new", rc))]

    def test_waiter_matches_the_pre_tree_implementation(self):
        """Same lines, returns, exceptions, calls and bookkeeping at every step, except the two deliberate
        changes (maintainer, after cross-review of 534dfdd), which are checked against the old behaviour instead:
          2a  where the old waiter retried an unconfirmed delete forever, the new one stops at the
              DELETE_ATTEMPTS-th failure: old returned None, with the same lines minus DELETE_GAVE_UP and END;
          2b  where the old waiter ended "gone" with INCOMPLETE outputs, the new one ends "gone_unverified", with
              the same lines plus OUTPUTS_UNVERIFIED."""
        rng = random.Random(20261031)
        endings, edges = {}, {"stop_wait": 0, "stall": 0, "report_at": 0, "stop_at": 0}
        cfg = tc.CFG
        for i in range(self.N):
            steps = list(scenario_steps(rng))
            sides = self.sides(i)
            waiters = []
            for s in sides:
                s.knobs()
                (s.fake / "instances.json").write_text(json.dumps({self.NAME: {"zone": "z-a", "status": "RUNNING"}}))
                s.mod.record_instance(s.root, self.NAME, "z-a")
                d = json.loads(rc.instances_file(s.root).read_text()); d[self.NAME]["created"] = s.now
                rc.instances_file(s.root).write_text(json.dumps(d))
                waiters.append(s.mod.Waiter(s.cfg, s.g, s.root, self.NAME, clock=lambda s=s: s.now, out=s.lines.append))
            for j, step in enumerate(steps):
                res = []
                for s, w in zip(sides, waiters):
                    apply_step(s, self.NAME, step)
                    if s.mod is rc:             # which edges this poll lands on exactly
                        bb, now = w.bb, s.now
                        edges["stop_wait"] += bool(bb["stopping"] and now - bb["stop_sent_at"] == bb["stop_wait_s"])
                        edges["stall"] += bool(bb["last_seen"] and now - bb["last_change"] == cfg["stall_min"] * 60)
                        cost = (now - bb["created"]) / 3600 * cfg["price_per_vm_hour"]
                        edges["report_at"] += cost == cfg["report_at_usd"]
                        edges["stop_at"] += cost == cfg["stop_at_usd"]
                    res.append(poll(s, w))
                ctx = f"scenario {i} step {j}: {step}"
                old, new = sides
                # deliberate (cross-review of 8e0c5ee): END for "gone" now says what the verification rested on; these
                # scenarios have no REQUIRED.txt, so it is always the manifest-only suffix
                new.lines[:] = [l.replace(" (manifest only; required list unknown)", "") for l in new.lines]
                self.assertEqual(old.calls(), new.calls(), ctx)
                self.assertEqual(instances_or_none(old), instances_or_none(new), ctx)
                if res[1] == "delete_unverified":
                    self.assertIsNone(res[0], ctx)
                    self.assertEqual(old.out_lines(), without(new.out_lines(), "DELETE_GAVE_UP", "END"), ctx)
                    self.assertEqual(sum(l.startswith("DELETE_CHECK_FAILED") for l in old.out_lines()),
                                     rc.DELETE_ATTEMPTS, ctx)
                elif res[1] == "gone_unverified":
                    self.assertEqual(res[0], "gone", ctx)
                    self.assertEqual(old.out_lines(), without(new.out_lines(), "OUTPUTS_UNVERIFIED"), ctx)
                    self.assertIn("INCOMPLETE", old.out_lines()[-1], ctx)
                else:
                    self.assertEqual(res[0], res[1], ctx)
                    self.assertEqual(old.out_lines(), new.out_lines(), ctx)
                    if res[1] == "gone":
                        self.assertIn("outputs verified", new.out_lines()[-1], ctx)
                if res[1] is not None:
                    key = res[1] if isinstance(res[1], str) else f"raised {res[1][1]}"
                    endings[key] = endings.get(key, 0) + 1
                    break
        # the scenarios must reach every ending and land on every edge, or the comparison says little
        self.assertTrue({"done", "gone", "gone_unverified", "stop_unconfirmed", "delete_unverified",
                         "raised FileNotFoundError", "raised JSONDecodeError", "raised FileExistsError"} <= set(endings),
                        endings)
        self.assertTrue(all(edges.values()), edges)

    def test_create_matches_the_pre_tree_implementation(self):
        rng = random.Random(7)
        seen = set()
        for i in range(60):
            zones = rng.choice([["z-a", "z-b"], ["z-a", "z-b"], ["z-a"], []])     # [] only reachable without load_config
            stock = [z for z in ("z-a", "z-b") if rng.random() < 0.5]
            yes = rng.random() < 0.7
            name = rng.choice(["rak-c", "rak-c", "other-x"])
            knobs = {"stockout_zones": stock, "auth_ok": rng.random() > 0.1, "sa_exists": rng.random() > 0.1}
            disk = rng.choice([300, 300, 100])
            res = []
            for s in self.sides(i):
                s.knobs(**knobs)
                try:
                    r = ("ok", s.mod.create(dict(s.cfg, disk_gb=disk, zones=zones), s.g, s.root, name, "gs://j/", yes,
                                            out=s.lines.append))
                except s.mod.CloudError as e:
                    r = ("err", str(e))
                inst = s.instances()
                for v in (inst or {}).values():
                    v.pop("created")
                res.append((r, s.out_lines(), s.calls(), inst))
            self.assertEqual(res[0], res[1], f"create scenario {i}: {knobs} yes={yes} name={name} disk={disk}")
            seen.add(res[0][0][1] if res[0][0][0] == "ok" else res[0][0][1].split("\n")[0])
        self.assertTrue({"z-a", "z-b", None, "every zone failed", "precheck failed:"} <= seen, seen)


# ---------------------------------------------------------------- the tree is not the agent's to edit

class Pinned(unittest.TestCase):
    def test_edited_tree_stops_the_waiter_and_create(self):
        spec = json.loads(rc.TREE_FILE.read_text(encoding="utf-8"))
        outcome = spec["wait"]["children"][3]["children"]
        outcome.insert(0, {"type": "Action", "name": "skip", "call": "keep_waiting"})
        spec["create"]["children"] = spec["create"]["children"][1:]           # drop the precheck
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lifecycle.json"; f.write_text(json.dumps(spec), encoding="utf-8")
            old = rc.TREE_FILE; rc.TREE_FILE = f
            try:
                for key in ("wait", "create"):
                    with self.assertRaisesRegex(bt.TreeError, "not to be edited"):
                        rc.lifecycle_tree(key, {})
            finally:
                rc.TREE_FILE = old

    def test_hook_refuses_edits_to_the_tree_folder(self):
        hook = PLUGIN / "hooks" / "tree_guard.py"
        cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        cmds = [h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertTrue(any("tree_guard.py" in c for c in cmds))
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(PLUGIN))

        def run(tool, inp):
            return subprocess.run([sys.executable, str(hook)], input=json.dumps({"tool_name": tool, "tool_input": inp}),
                                  capture_output=True, text=True, env=env)
        tree = str(PLUGIN / "trees" / "lifecycle.json")
        for tool, inp in (("Edit", {"file_path": tree}), ("Write", {"file_path": tree}),
                          ("MultiEdit", {"file_path": tree}), ("NotebookEdit", {"notebook_path": tree}),
                          ("Write", {"file_path": str(PLUGIN / "trees" / ".." / "trees" / "new.json")}),
                          ("Edit", {"file_path": tree.upper() if os.name == "nt" else tree}),
                          ("Bash", {"command": f"sed -i s/precheck/x/ '{tree}'"}),
                          ("Bash", {"command": "cd plugins/rak-cloud && python -c \"open('trees/lifecycle.json','w')\""})):
            r = run(tool, inp)
            self.assertEqual(r.returncode, 2, (tool, inp, r.stderr))
            self.assertIn("tree", r.stderr)
        for tool, inp in (("Edit", {"file_path": str(PLUGIN / "README.md")}), ("Read", {"file_path": tree}),
                          ("Bash", {"command": "python scripts/rak_cloud.py wait rak-x"})):
            self.assertEqual(run(tool, inp).returncode, 0, (tool, inp))


if __name__ == "__main__":
    unittest.main()
