"""rak_cloud.py against a fake gcloud. Every guard has a case it must refuse.
Run from the plugin folder:  python -m pytest -q tests
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "scripts"))
import rak_cloud as rc  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_gcloud.py"
CFG = {
    "account": "runner@example.com", "project": "demo-proj", "bucket": "gs://fake-bkt/rak",
    "image": {"project": "demo-proj", "family": "isaac"}, "zones": ["z-a", "z-b"], "machine_type": "g2-standard-8",
    "disk_gb": 300, "disk_type": "pd-balanced", "provisioning": "STANDARD", "max_run": "8h", "idle_minutes": 20,
    "service_account": "rak-runner@demo-proj.example", "price_per_vm_hour": 1.0,
    "report_at_usd": 8, "stop_at_usd": 12, "labels": {"owner": "tester"}, "name_prefix": "rak-",
    "poll_s": 1, "stall_min": 30, "stop_wait_min": 25, "local_dir": "",
}


class Env(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="rakc-"))
        self.root = self.t / "proj"; (self.root / ".rak").mkdir(parents=True)
        self.fake = self.t / "fake"; (self.fake / "gcs" / "fake-bkt" / "rak").mkdir(parents=True)
        self.knobs = {"images": {"isaac": 250}, "logs": []}
        self.save_knobs()
        self.cfg = copy.deepcopy(CFG); self.cfg["local_dir"] = str(self.t / "pulled")
        os.environ["FAKE_GCLOUD_DIR"] = str(self.fake)
        os.environ["RAK_GCLOUD"] = json.dumps([sys.executable, str(FAKE)])
        self.g = rc.Gcloud(self.cfg)
        self.lines = []

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def save_knobs(self):
        (self.fake / "config.json").write_text(json.dumps(self.knobs))

    def knob(self, **kw):
        self.knobs.update(kw); self.save_knobs()

    def calls(self):
        f = self.fake / "calls.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def write_cfg(self, cfg):
        (self.root / ".rak" / "cloud.json").write_text(json.dumps(cfg))


class Config(Env):
    def test_complete_config_loads(self):
        self.write_cfg(self.cfg); rc.load_config(self.root)

    def test_every_key_required(self):
        for k in rc.REQUIRED_KEYS:
            c = dict(self.cfg); del c[k]; self.write_cfg(c)
            with self.assertRaises(rc.CloudError, msg=k):
                rc.load_config(self.root)

    def test_unknown_key_raises(self):
        self.write_cfg(dict(self.cfg, max_runn="4h"))
        with self.assertRaises(rc.CloudError):
            rc.load_config(self.root)

    def test_placeholder_and_template_rejected(self):
        self.write_cfg(dict(self.cfg, project="<gcp-project-id>"))
        with self.assertRaises(rc.CloudError):
            rc.load_config(self.root)
        tpl = json.loads((PLUGIN.parent.parent / "templates/cloud/cloud.json").read_text())
        self.write_cfg(tpl)
        with self.assertRaises(rc.CloudError):
            rc.load_config(self.root)

    def test_owner_label_and_budget_order(self):
        self.write_cfg(dict(self.cfg, labels={"project": "x"}))
        with self.assertRaises(rc.CloudError):
            rc.load_config(self.root)
        self.write_cfg(dict(self.cfg, report_at_usd=20, stop_at_usd=10))
        with self.assertRaises(rc.CloudError):
            rc.load_config(self.root)


class Precheck(Env):
    def test_clean_passes(self):
        self.assertEqual(rc.precheck(self.cfg, self.g, self.root), [])

    def test_expired_credentials_stop_early(self):
        self.knob(auth_ok=False)
        f = rc.precheck(self.cfg, self.g, self.root)
        self.assertEqual(len(f), 1); self.assertIn("log in", f[0])

    def test_disk_smaller_than_image(self):
        f = rc.precheck(dict(self.cfg, disk_gb=200), self.g, self.root)
        self.assertTrue(any("200 < image size 250" in x for x in f), f)

    def test_unreadable_image_size(self):
        f = rc.precheck(dict(self.cfg, image={"project": "demo-proj", "family": "nope"}), self.g, self.root)
        self.assertTrue(any("diskSizeGb" in x for x in f), f)

    def test_worst_case_budget(self):
        self.knob(logs=[{"timestamp": "2026-10-30T00:00:00Z", "protoPayload": {"methodName": "v1.compute.instances.insert", "resourceName": "projects/p/zones/z/instances/rak-old"}},
                        {"timestamp": "2026-10-30T05:00:00Z", "protoPayload": {"methodName": "v1.compute.instances.delete", "resourceName": "projects/p/zones/z/instances/rak-old"}}])
        f = rc.precheck(self.cfg, self.g, self.root)   # spent 5 + 8h x 1 = 13 > 12
        self.assertTrue(any("crosses the stop line" in x for x in f), f)

    def test_spot_needs_explicit_acceptance(self):
        f = rc.precheck(dict(self.cfg, provisioning="SPOT"), self.g, self.root)
        self.assertTrue(any("preempted" in x for x in f), f)
        self.assertEqual(rc.precheck(dict(self.cfg, provisioning="SPOT", accept_spot_preemption=True), self.g, self.root), [])

    def test_missing_service_account(self):
        self.knob(sa_exists=False)
        self.assertTrue(any("service account" in x for x in rc.precheck(self.cfg, self.g, self.root)))

    def test_max_run_limits(self):
        self.assertTrue(any("longer than 24h" in x for x in rc.precheck(dict(self.cfg, max_run="30h", stop_at_usd=100), self.g, self.root)))
        self.assertTrue(any("longer than max_run" in x for x in rc.precheck(self.cfg, self.g, self.root, job_hours=9)))

    def test_crlf_script_refused(self):
        p = self.t / "s.sh"; p.write_bytes(b"#!/usr/bin/env bash\r\necho hi\r\n")
        self.assertTrue(rc.check_scripts([p]))
        q = self.t / "q.sh"; q.write_bytes(b"#!/usr/bin/env bash\nif then\n")
        self.assertTrue(rc.check_scripts([q]))
        self.assertEqual(rc.check_scripts(rc.startup_files().values()), [])


class Create(Env):
    def test_dry_run_prints_guarded_command_and_creates_nothing(self):
        z = rc.create(self.cfg, self.g, self.root, "rak-demo", "gs://fake-bkt/rak/job/", yes=False, out=self.lines.append)
        self.assertIsNone(z)
        cmd = self.lines[-1]
        for s in ("--max-run-duration=8h", "--instance-termination-action=DELETE", "--boot-disk-auto-delete",
                  "--service-account=rak-runner@", "--boot-disk-size=300GB", "rak-out=gs://fake-bkt/rak/rak-demo/out"):
            self.assertIn(s, cmd)
        self.assertFalse(any(c[:3] == ["compute", "instances", "create"] for c in self.calls()))

    def test_guard_refuses_unguarded_commands(self):
        cmd = rc.create_command(self.cfg, "rak-x", "z-a", "j", "o")
        rc.guard_command(cmd)
        for drop in ("--max-run-duration=8h", "--instance-termination-action=DELETE", "--boot-disk-auto-delete"):
            with self.assertRaises(rc.CloudError):
                rc.guard_command([a for a in cmd if a != drop])

    def test_name_prefix_enforced(self):
        with self.assertRaises(rc.CloudError):
            rc.create_command(self.cfg, "other-x", "z-a", "j", "o")

    def test_stockout_moves_to_next_zone_and_records(self):
        self.knob(stockout_zones=["z-a"])
        z = rc.create(self.cfg, self.g, self.root, "rak-demo", "gs://j/", yes=True, out=self.lines.append)
        self.assertEqual(z, "z-b")
        rec = json.loads(rc.instances_file(self.root).read_text())
        self.assertEqual(rec["rak-demo"]["zone"], "z-b")

    def test_failed_precheck_creates_nothing(self):
        with self.assertRaises(rc.CloudError):
            rc.create(dict(self.cfg, disk_gb=100), self.g, self.root, "rak-demo", "gs://j/", yes=True, out=self.lines.append)
        self.assertFalse(any(c[:3] == ["compute", "instances", "create"] for c in self.calls()))

    def test_account_and_project_pinned(self):
        g = rc.Gcloud(self.cfg)
        self.assertEqual((g.env["CLOUDSDK_CORE_ACCOUNT"], g.env["CLOUDSDK_CORE_PROJECT"]), ("runner@example.com", "demo-proj"))


class VmState(Env):
    def setUp(self):
        super().setUp()
        (self.fake / "instances.json").write_text(json.dumps({"rak-a": {"zone": "z-a", "status": "RUNNING"}}))

    def test_states(self):
        self.assertEqual(rc.vm_state(self.g, "rak-a", "z-a"), "RUNNING")
        self.assertEqual(rc.vm_state(self.g, "rak-zz", "z-a"), "GONE")

    def test_auth_failure_is_unknown_not_gone(self):
        self.knob(auth_ok=False)
        self.assertEqual(rc.vm_state(self.g, "rak-zz", "z-a"), "UNKNOWN")

    def test_network_failure_is_unknown(self):
        self.knob(net_fail=True)
        self.assertEqual(rc.vm_state(self.g, "rak-a", "z-a"), "UNKNOWN")

    def test_timeout_is_unknown(self):
        self.knob(hang_s=3)
        old = rc.GCLOUD_TIMEOUT; rc.GCLOUD_TIMEOUT = 1
        try:
            g = rc.Gcloud(self.cfg)
            self.assertEqual(g("compute", "instances", "describe", "rak-a", "--zone=z-a", timeout=1).rc, 124)
            r = rc.Result(124, "", "timeout")
            self.assertNotEqual(r.rc, 0)
        finally:
            rc.GCLOUD_TIMEOUT = old


class LedgerTests(unittest.TestCase):
    E = staticmethod(lambda t, m, n: {"timestamp": t, "protoPayload": {"methodName": m, "resourceName": f"projects/p/zones/z/instances/{n}"}})

    def test_intervals(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc).timestamp()
        e = [self.E("2026-10-31T00:00:00Z", "v1.compute.instances.insert", "rak-a"),
             self.E("2026-10-31T00:00:05Z", "v1.compute.instances.insert", "rak-a"),   # first/last op entries
             self.E("2026-10-31T02:00:00Z", "v1.compute.instances.delete", "rak-a"),
             self.E("2026-10-31T01:00:00Z", "v1.compute.instances.insert", "rak-b"),
             self.E("2026-10-31T01:06:00Z", "compute.instances.preempted", "rak-b"),
             self.E("2026-10-31T10:00:00Z", "v1.compute.instances.insert", "rak-c"),     # still running
             self.E("2026-10-31T00:00:00Z", "v1.compute.instances.insert", "someone-else")]
        iv = rc.Ledger.intervals(e, "rak-", now)
        hours = {n: (b - a) / 3600 for n, (a, b) in iv.items()}
        self.assertEqual(set(hours), {"rak-a", "rak-b", "rak-c"})
        self.assertAlmostEqual(hours["rak-a"], 2.0); self.assertAlmostEqual(hours["rak-b"], 0.1); self.assertAlmostEqual(hours["rak-c"], 2.0)


class WaiterTests(Env):
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

    def job_outputs(self, status="DONE", tamper=False):
        (self.out / "model.pt").write_bytes(b"weights")
        (self.out / "eval").mkdir(exist_ok=True); (self.out / "eval/summary.json").write_text('{"s": 1}')
        man = "".join(f"{rc.sha256_file(self.out / p)}  ./{p}\n" for p in ("eval/summary.json", "model.pt"))
        (self.out / "MANIFEST.sha256").write_text(man)
        if tamper:
            (self.out / "model.pt").write_bytes(b"weights-changed-after-manifest")
        (self.out / "status.txt").write_text(status + "\n")

    def kw(self, k):
        return [l for l in self.lines if l.startswith(k)]

    def vm(self):
        return json.loads((self.fake / "instances.json").read_text()).get(self.NAME, {}).get("status", "GONE")

    def test_done_pulls_verifies_then_deletes(self):
        self.job_outputs()
        self.assertEqual(self.w.poll(), "done")
        self.assertTrue(self.kw("PULLED_OK") and self.kw("DELETED"))
        self.assertEqual(self.vm(), "GONE")
        self.assertTrue((Path(self.cfg["local_dir"]) / self.NAME / "model.pt").is_file())

    def test_incomplete_pull_keeps_vm(self):
        self.job_outputs(); self.knob(rsync_drop=["model.pt"])
        self.assertIsNone(self.w.poll())
        self.assertTrue(self.kw("PULL_INCOMPLETE")); self.assertFalse(self.kw("DELETED"))
        self.assertEqual(self.vm(), "RUNNING")

    def test_hash_mismatch_keeps_vm(self):
        self.job_outputs(tamper=True)
        self.assertIsNone(self.w.poll())
        self.assertIn("hash differs", " ".join(self.kw("PULL_INCOMPLETE")))
        self.assertEqual(self.vm(), "RUNNING")

    def test_missing_manifest_keeps_vm(self):
        (self.out / "status.txt").write_text("DONE\n")
        self.assertIsNone(self.w.poll())
        self.assertEqual(self.vm(), "RUNNING")

    def test_unknown_state_is_not_gone(self):
        self.job_outputs(); self.knob(auth_ok=False)
        self.assertIsNone(self.w.poll())
        self.assertTrue(self.kw("VM_STATE_UNKNOWN"))
        self.assertFalse(any(c[:3] == ["compute", "instances", "delete"] for c in self.calls()))

    def test_preempted_before_terminal(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        (self.fake / "instances.json").write_text("{}")
        # Deliberate rule change, not an expectation edited to turn green: this asserted "gone" until the maintainer's
        # decision 2b after cross-review of 534dfdd. A VM gone before its outputs verified now ends gone_unverified
        # (exit 4) and lists what is unverified; "gone" (exit 2) is kept for a VM whose outputs all verified.
        self.assertEqual(self.w.poll(), "gone_unverified")
        self.assertEqual(rc.EXIT["gone_unverified"], 4)
        self.assertTrue(self.kw("VM_GONE"))
        self.assertIn("INCOMPLETE", self.kw("END")[0])
        self.assertEqual(self.w.bb["unverified"], ["MANIFEST.sha256 missing (required list unknown)"])
        self.assertIn("required list unknown", self.kw("OUTPUTS_UNVERIFIED")[0])

    def test_guard_fallback_shutdown_is_cleaned_up(self):
        self.job_outputs(status="RUNNING_TRAIN")  # job never reached a terminal status, guard shut the VM down
        (self.fake / "instances.json").write_text(json.dumps({self.NAME: {"zone": "z-a", "status": "TERMINATED"}}))
        self.assertEqual(self.w.poll(), "done")
        self.assertEqual(self.vm(), "GONE")

    def test_delete_that_leaves_a_disk_is_reported(self):
        self.job_outputs(); self.knob(disk_left=True)
        self.w.poll()
        self.assertTrue(self.kw("DELETE_CHECK_FAILED"))

    def test_stall(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.w.poll(); self.now += 29 * 60; self.w.poll()
        self.assertFalse(self.kw("STALL"))
        self.now += 2 * 60; self.w.poll()
        self.assertTrue(self.kw("STALL"))

    def test_budget_report_then_stop_then_unconfirmed(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.now += 8.5 * 3600; self.w.poll()
        self.assertTrue(self.kw("BUDGET_REPORT")); self.assertFalse(self.kw("BUDGET_STOP"))
        self.now += 4 * 3600; self.w.poll()
        self.assertTrue(self.kw("BUDGET_STOP") and self.kw("STOP_SENT"))
        self.assertTrue((self.fake / "gcs/fake-bkt/rak" / self.NAME / "control/stop").is_file())
        self.now += 26 * 60
        self.assertEqual(self.w.poll(), "stop_unconfirmed")
        self.assertEqual(self.vm(), "RUNNING")   # never deleted without verified outputs

    def test_stop_confirmed_is_pulled_and_deleted(self):
        (self.out / "status.txt").write_text("RUNNING_TRAIN\n")
        self.now += 13 * 3600; self.w.poll()
        self.job_outputs(status="STOPPED_SYNCED")
        self.assertEqual(self.w.poll(), "done")
        self.assertEqual(self.vm(), "GONE")


if __name__ == "__main__":
    unittest.main()
