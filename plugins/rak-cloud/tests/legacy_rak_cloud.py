#!/usr/bin/env python3
# FROZEN REFERENCE: rak_cloud.py as of 47e424a, before the lifecycle moved to behaviour trees. Used only by
# tests/test_bt_lifecycle.py to check that the tree-driven create and waiter behave the same. Do not edit.
"""rak-cloud: GCP GPU job lifecycle with the spending decisions kept outside the agent.

  rak_cloud.py precheck               checks that must pass before any VM is created
  rak_cloud.py create NAME [--yes]    dry run by default: prints the exact gcloud command
  rak_cloud.py wait NAME              waiter: status / VM state / stall / budget; pull, verify, delete
  rak_cloud.py state NAME             RUNNING | TERMINATED | ... | GONE | UNKNOWN
  rak_cloud.py ledger [--since DATE]  cost from the audit log (instance insert -> delete/preempt)
  rak_cloud.py delete NAME            delete VM + disk, then verify both are gone

Configuration: <project>/.rak/cloud.json (template: templates/cloud/cloud.json). Every key is required and
there are no defaults: account, project, bucket, image, zones and prices differ per user, and a default that
happens to work on one machine is how resources end up in someone else's project.

Standard library only. gcloud is called with a timeout on every call, with the account and project pinned
through CLOUDSDK_CORE_* in the child environment (a background script must not follow whatever account the
user last logged in with). RAK_GCLOUD (a JSON list) replaces the gcloud command - the tests use it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent.parent.parent / "templates" / "cloud"

REQUIRED_KEYS = {
    "account": str, "project": str, "bucket": str, "image": dict, "zones": list, "machine_type": str,
    "disk_gb": int, "disk_type": str, "provisioning": str, "max_run": str, "idle_minutes": int,
    "service_account": str, "price_per_vm_hour": (int, float), "report_at_usd": (int, float),
    "stop_at_usd": (int, float), "labels": dict, "name_prefix": str, "poll_s": int, "stall_min": int,
    "stop_wait_min": int, "local_dir": str,
}
OPTIONAL_KEYS = {"accept_spot_preemption": bool}
TERMINAL_OK = {"DONE"}
TERMINAL = {"DONE", "STOPPED_SYNCED"}           # plus anything starting with FAIL_
GCLOUD_TIMEOUT = 120


class CloudError(Exception):
    pass


# ---------------------------------------------------------------- config

def load_config(root: Path) -> dict:
    f = root / ".rak" / "cloud.json"
    if not f.is_file():
        raise CloudError(f"{f} not found; copy templates/cloud/cloud.json and fill every key")
    cfg = json.loads(f.read_text(encoding="utf-8"))
    unknown = set(cfg) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS)
    if unknown:
        raise CloudError(f"unknown keys in cloud.json: {sorted(unknown)} (a typo must not silently disable a guard)")
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise CloudError(f"cloud.json is missing required keys (no defaults): {missing}")
    for k, t in REQUIRED_KEYS.items():
        if not isinstance(cfg[k], t) or (isinstance(cfg[k], bool) and t is not bool):
            raise CloudError(f"cloud.json: {k} has the wrong type")
        if isinstance(cfg[k], str) and (not cfg[k] or "<" in cfg[k]):
            raise CloudError(f"cloud.json: {k} is empty or still a placeholder")
    if not cfg["bucket"].startswith("gs://"):
        raise CloudError("bucket must be a gs:// URL")
    if set(cfg["image"]) - {"family", "name", "project"} or "project" not in cfg["image"] \
            or ("family" in cfg["image"]) == ("name" in cfg["image"]):
        raise CloudError('image must be {"project": ..., "family": ...} or {"project": ..., "name": ...}')
    if cfg["provisioning"] not in ("STANDARD", "SPOT"):
        raise CloudError("provisioning must be STANDARD or SPOT")
    if not cfg["zones"]:
        raise CloudError("zones is empty")
    if "owner" not in cfg["labels"]:
        raise CloudError("labels must include owner (the audit trail of who created a VM)")
    if cfg["stop_at_usd"] < cfg["report_at_usd"]:
        raise CloudError("stop_at_usd must be >= report_at_usd")
    return cfg


def max_run_hours(s: str) -> float:
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if not m:
        raise CloudError(f"max_run {s!r} is not like 4h / 90m")
    return int(m.group(1)) * {"s": 1 / 3600, "m": 1 / 60, "h": 1, "d": 24}[m.group(2)]


# ---------------------------------------------------------------- gcloud

@dataclass
class Result:
    rc: int
    out: str
    err: str


class Gcloud:
    def __init__(self, cfg: dict):
        self.cmd = json.loads(os.environ["RAK_GCLOUD"]) if os.environ.get("RAK_GCLOUD") else ["gcloud"]
        self.env = dict(os.environ, CLOUDSDK_CORE_ACCOUNT=cfg["account"], CLOUDSDK_CORE_PROJECT=cfg["project"],
                        CLOUDSDK_CORE_DISABLE_PROMPTS="1")

    def __call__(self, *args: str, timeout: int = GCLOUD_TIMEOUT, input: str | None = None) -> Result:
        try:
            r = subprocess.run([*self.cmd, *args], capture_output=True, text=True, env=self.env, timeout=timeout,
                               encoding="utf-8", errors="replace", input=input if input is not None else "")
            return Result(r.returncode, r.stdout, r.stderr)
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timeout after {timeout}s: gcloud {' '.join(args[:3])}")


NOT_FOUND = re.compile(r"was not found|notFound|\b404\b", re.I)


def vm_state(g: Gcloud, name: str, zone: str) -> str:
    """GONE only when the API says the instance does not exist. Expired credentials, network errors and
    timeouts are UNKNOWN: treating "could not ask" as "gone" once let a guard delete the only copy of a log."""
    r = g("compute", "instances", "describe", name, f"--zone={zone}", "--format=value(status)")
    if r.rc == 0 and re.fullmatch(r"[A-Z_]+", r.out.strip()):
        return r.out.strip()
    if r.rc != 0 and NOT_FOUND.search(r.err):
        return "GONE"
    return "UNKNOWN"


# ---------------------------------------------------------------- startup pieces

def startup_files() -> dict[str, Path]:
    return {"startup-script": TEMPLATES / "startup.sh", "rak-idle-check": TEMPLATES / "idle_check.sh"}


def check_scripts(paths) -> list[str]:
    """Files sent to a Linux VM: no CR bytes (CRLF breaks bash and changes hashes), and bash -n clean."""
    errs = []
    for p in paths:
        b = Path(p).read_bytes()
        if b"\r" in b:
            errs.append(f"{p}: contains CR bytes (CRLF); the VM's bash will fail on it")
            continue
        r = subprocess.run(["bash", "-n"], input=b, capture_output=True)  # stdin: a Windows path would not survive bash
        r.stderr = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0:
            errs.append(f"{p}: bash -n failed: {r.stderr.strip()[:200]}")
    return errs


# ---------------------------------------------------------------- precheck

def image_args(cfg: dict) -> list[str]:
    im = cfg["image"]
    return ([f"--image-family={im['family']}"] if "family" in im else [f"--image={im['name']}"]) + [f"--image-project={im['project']}"]


def image_size_gb(g: Gcloud, cfg: dict) -> int:
    im = cfg["image"]
    args = (["compute", "images", "describe-from-family", im["family"]] if "family" in im
            else ["compute", "images", "describe", im["name"]])
    r = g(*args, f"--project={im['project']}", "--format=value(diskSizeGb)")
    v = r.out.strip()
    if r.rc != 0 or not v.isdigit():
        raise CloudError(f"cannot read the image's diskSizeGb (rc={r.rc}): {r.err.strip()[:200]}")
    return int(v)


def precheck(cfg: dict, g: Gcloud, root: Path, job_hours: float | None = None) -> list[str]:
    """Return failures (empty = OK). Each one is a reason a real create would fail or overspend."""
    fails = []
    if g("auth", "print-access-token").rc != 0:
        fails.append(f"credentials for {cfg['account']} are not valid; the user must log in again")
        return fails  # every later check would fail for the same reason
    if g("storage", "ls", cfg["bucket"]).rc != 0:
        fails.append(f"bucket {cfg['bucket']} is not readable with these credentials")
    try:
        size = image_size_gb(g, cfg)
        if cfg["disk_gb"] < size:
            fails.append(f"disk_gb {cfg['disk_gb']} < image size {size} GB (the create would fail in every zone)")
    except CloudError as e:
        fails.append(str(e))
    try:
        hours = max_run_hours(cfg["max_run"])
        if hours > 24:
            fails.append(f"max_run {cfg['max_run']} is longer than 24h; split the job")
        worst = Ledger(cfg, g, root).spent_usd() + hours * cfg["price_per_vm_hour"]
        if worst > cfg["stop_at_usd"]:
            fails.append(f"worst case US${worst:.2f} (spent so far + max_run x price) crosses the stop line US${cfg['stop_at_usd']}")
        if job_hours is not None and job_hours > hours:
            fails.append(f"estimated job {job_hours} h is longer than max_run {cfg['max_run']}")
    except CloudError as e:
        fails.append(str(e))
    if cfg["provisioning"] == "SPOT" and not cfg.get("accept_spot_preemption"):
        fails.append("SPOT can be preempted minutes after boot (seen in practice), and each preemption repeats setup; "
                     'set "accept_spot_preemption": true to accept that, or use STANDARD')
    if g("iam", "service-accounts", "describe", cfg["service_account"], "--format=value(email)").rc != 0:
        fails.append(f"service account {cfg['service_account']} does not exist or is not visible (run install_sa.sh)")
    fails += check_scripts(startup_files().values())
    return fails


# ---------------------------------------------------------------- create

def create_command(cfg: dict, name: str, zone: str, job_url: str, out_url: str) -> list[str]:
    if not name.startswith(cfg["name_prefix"]):
        raise CloudError(f"VM name {name} must start with {cfg['name_prefix']} (the service account may only delete those)")
    files = ",".join(f"{k}={v.as_posix()}" for k, v in startup_files().items())
    meta = f"rak-job={job_url},rak-out={out_url},rak-idle-minutes={cfg['idle_minutes']}"
    labels = ",".join(f"{k}={v}" for k, v in sorted(cfg["labels"].items()))
    return ["compute", "instances", "create", name, f"--zone={zone}", f"--machine-type={cfg['machine_type']}",
            f"--provisioning-model={cfg['provisioning']}", "--instance-termination-action=DELETE",
            f"--max-run-duration={cfg['max_run']}", *image_args(cfg), f"--boot-disk-size={cfg['disk_gb']}GB",
            f"--boot-disk-type={cfg['disk_type']}", "--boot-disk-auto-delete", "--maintenance-policy=TERMINATE",
            f"--service-account={cfg['service_account']}", "--scopes=https://www.googleapis.com/auth/cloud-platform",
            f"--metadata-from-file={files}", f"--metadata={meta}", f"--labels={labels}"]


def guard_command(cmd: list[str]) -> None:
    """Refuse a create command without a run-time limit that deletes. Called on every create."""
    if not any(a.startswith("--max-run-duration=") for a in cmd):
        raise CloudError("create without --max-run-duration refused")
    if "--instance-termination-action=DELETE" not in cmd:
        raise CloudError("create without --instance-termination-action=DELETE refused (STOP leaves a billed disk)")
    if "--boot-disk-auto-delete" not in cmd:
        raise CloudError("create without --boot-disk-auto-delete refused")


def instances_file(root: Path) -> Path:
    return root / ".rak" / "cloud" / "instances.json"


def record_instance(root: Path, name: str, zone: str) -> None:
    f = instances_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    d = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    d[name] = {"zone": zone, "created": time.time(), "ended": None}
    f.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8", newline="\n")


def create(cfg: dict, g: Gcloud, root: Path, name: str, job_url: str, yes: bool, out=print) -> str | None:
    fails = precheck(cfg, g, root)
    if fails:
        raise CloudError("precheck failed:\n  - " + "\n  - ".join(fails))
    out_url = f"{cfg['bucket'].rstrip('/')}/{name}/out"
    for zone in cfg["zones"]:
        cmd = create_command(cfg, name, zone, job_url, out_url)
        guard_command(cmd)
        if not yes:
            out("DRY RUN (nothing created; --yes to create). First zone's command:")
            out("gcloud " + " ".join(cmd))
            return None
        r = g(*cmd, timeout=600)
        if r.rc == 0:
            record_instance(root, name, zone)
            out(f"CREATED {name} {zone}")
            return zone
        out(f"CREATE_FAIL {zone}: {r.err.strip().splitlines()[-1] if r.err.strip() else r.rc}")
    raise CloudError("every zone failed")


# ---------------------------------------------------------------- ledger

class Ledger:
    """Spending from the audit log: each instance costs price_per_vm_hour from insert until delete or preemption
    (or now, if neither is logged). Conservative by design: a TERMINATED VM still bills its disk, so a stop does
    not end the interval."""

    def __init__(self, cfg: dict, g: Gcloud, root: Path):
        self.cfg, self.g, self.root = cfg, g, root

    def entries(self, since: str) -> list[dict]:
        flt = (f'resource.type="gce_instance" AND timestamp>="{since}" AND '
               f'(protoPayload.methodName:"instances.insert" OR protoPayload.methodName:"instances.delete" OR '
               f'protoPayload.methodName="compute.instances.preempted")')
        r = self.g("logging", "read", flt, "--format=json", "--limit=5000", timeout=180)
        if r.rc != 0:
            raise CloudError(f"cannot read the audit log: {r.err.strip()[:200]}")
        return json.loads(r.out or "[]")

    @staticmethod
    def intervals(entries: list[dict], prefix: str, now: float) -> dict[str, tuple[float, float]]:
        start, end = {}, {}
        for e in entries:
            pp = e.get("protoPayload", {})
            name = pp.get("resourceName", "").rsplit("/", 1)[-1]
            if not name.startswith(prefix):
                continue
            t = dt.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
            m = pp.get("methodName", "")
            if m.endswith("instances.insert"):
                start[name] = min(start.get(name, t), t)
            elif m.endswith("instances.delete") or m.endswith("instances.preempted"):
                end[name] = min(end.get(name, t), t)
        return {n: (s, end.get(n, now) if end.get(n, now) >= s else now) for n, s in start.items()}

    def spent_usd(self, since: str | None = None, now: float | None = None) -> float:
        since = since or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
        iv = self.intervals(self.entries(since), self.cfg["name_prefix"], now or time.time())
        return sum((e - s) / 3600 for s, e in iv.values()) * self.cfg["price_per_vm_hour"]


# ---------------------------------------------------------------- pull / verify / delete

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pull(local: Path) -> list[str]:
    """Every file listed in MANIFEST.sha256 (written by vm_job.sh at its end) must be here with the same hash."""
    man = local / "MANIFEST.sha256"
    if not man.is_file():
        return ["MANIFEST.sha256 missing: the job did not finish writing its outputs, or the pull is incomplete"]
    problems = []
    lines = [ln for ln in man.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        problems.append("MANIFEST.sha256 is empty")
    for ln in lines:
        m = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", ln.strip())   # text mode "  " or binary mode " *"
        if not m:
            problems.append(f"unreadable manifest line: {ln[:80]!r}")
            continue
        h, rel = m.group(1), m.group(2)
        rel = rel[2:] if rel.startswith("./") else rel
        p = local / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif sha256_file(p) != h:
            problems.append(f"hash differs {rel}")
    return problems


def delete_and_verify(g: Gcloud, name: str, zone: str) -> bool:
    g("compute", "instances", "delete", name, f"--zone={zone}", "--quiet", timeout=600)
    gone = vm_state(g, name, zone) == "GONE"
    r = g("compute", "disks", "list", f"--filter=name={name}", "--format=value(name)")
    return gone and r.rc == 0 and not r.out.strip()


# ---------------------------------------------------------------- waiter

class Waiter:
    """One VM. poll() is one step of the loop; the CLI calls it every poll_s seconds.

    Prints one keyword per line (PROGRESS, STALL, VM_STATE_UNKNOWN, VM_GONE, BUDGET_REPORT, BUDGET_STOP,
    STOP_SENT, STOP_UNCONFIRMED, PULL_INCOMPLETE, PULLED_OK, DELETED, DELETE_CHECK_FAILED, END) so a monitor
    can grep it. The VM is deleted only after the pull is verified; a VM whose outputs cannot be verified is
    left running (its max-run still applies) and reported.
    """

    def __init__(self, cfg, g, root, name, clock=time.time, out=print):
        self.cfg, self.g, self.root, self.name, self.clock, self.out = cfg, g, root, name, clock, out
        inst = json.loads(instances_file(root).read_text(encoding="utf-8"))[name]
        self.zone, self.created = inst["zone"], inst["created"]
        self.prefix = f"{cfg['bucket'].rstrip('/')}/{name}"
        self.local = Path(cfg["local_dir"]) / name
        self.last_seen, self.last_change = None, clock()
        self.reported = self.stopping = False
        self.stop_sent_at = None
        self.finished = None

    def say(self, kw, msg=""):
        self.out(f"{kw} {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {self.name} {msg}".rstrip())

    def cost(self) -> float:
        return (self.clock() - self.created) / 3600 * self.cfg["price_per_vm_hour"]

    def status(self) -> str:
        r = self.g("storage", "cat", f"{self.prefix}/out/status.txt")
        return r.out.strip() if r.rc == 0 else "none"

    def pull_verify_delete(self) -> bool:
        self.local.mkdir(parents=True, exist_ok=True)
        self.g("storage", "rsync", "-r", f"{self.prefix}/out", str(self.local), timeout=1800)
        left = self.g("storage", "rsync", "-r", "--dry-run", f"{self.prefix}/out", str(self.local), timeout=600)
        problems = verify_pull(self.local)
        if left.rc != 0 or "Would copy" in left.out + left.err:
            problems.insert(0, "objects in the bucket still differ from the local copy")
        if problems:
            self.say("PULL_INCOMPLETE", "; ".join(problems[:3]) + " -- VM kept, retrying")
            return False
        n = len((self.local / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines())
        self.say("PULLED_OK", f"{n} files verified against MANIFEST.sha256")
        ok = delete_and_verify(self.g, self.name, self.zone)
        self._mark_ended()
        self.say("DELETED" if ok else "DELETE_CHECK_FAILED", "(VM and disk gone)" if ok else "-- check by hand")
        return ok

    def _mark_ended(self):
        f = instances_file(self.root)
        d = json.loads(f.read_text(encoding="utf-8"))
        d[self.name]["ended"] = self.clock()
        f.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8", newline="\n")

    def poll(self) -> str | None:
        """Returns None while running, else an END reason."""
        st, vm = self.status(), vm_state(self.g, self.name, self.zone)
        seen = (st, vm)
        if seen != self.last_seen:
            self.say("PROGRESS", f"vm={vm} status={st}")
            self.last_seen, self.last_change = seen, self.clock()
        elif self.clock() - self.last_change >= self.cfg["stall_min"] * 60:
            self.say("STALL", f"no change for {self.cfg['stall_min']} min (vm={vm} status={st})")
            self.last_change = self.clock()
        if vm == "UNKNOWN":
            self.say("VM_STATE_UNKNOWN", "cannot ask GCP (credentials? network?); NOT treated as gone")
            return None
        c = self.cost()
        if not self.reported and c >= self.cfg["report_at_usd"]:
            self.say("BUDGET_REPORT", f"US${c:.2f} (conservative)"); self.reported = True
        if not self.stopping and c >= self.cfg["stop_at_usd"]:
            self.say("BUDGET_STOP", f"US${c:.2f} >= {self.cfg['stop_at_usd']}")
            r = self.g("storage", "cp", "-", f"{self.prefix}/control/stop", input=f"stop {self.clock()}\n")  # job polls for it
            self.say("STOP_SENT" if r.rc == 0 else "STOP_SEND_FAILED"); self.stopping, self.stop_sent_at = True, self.clock()
        terminal = st in TERMINAL or st.startswith("FAIL_")
        if vm == "GONE":
            if not terminal:
                self.say("VM_GONE", f"before a terminal status (status={st}): preempted, max-run, or deleted elsewhere")
            self._mark_ended()
            self.local.mkdir(parents=True, exist_ok=True)
            self.g("storage", "rsync", "-r", f"{self.prefix}/out", str(self.local), timeout=1800)
            problems = verify_pull(self.local)
            self.say("END", "VM gone; outputs " + ("verified" if not problems else "INCOMPLETE: " + "; ".join(problems[:2])))
            return "gone"
        if terminal or vm in ("TERMINATED", "STOPPED", "SUSPENDED"):
            if self.pull_verify_delete():
                self.say("END", f"status={st}")
                return "done"
            return None
        if self.stopping and self.clock() - self.stop_sent_at >= self.cfg["stop_wait_min"] * 60:
            self.say("STOP_UNCONFIRMED", f"status={st} -- VM LEFT RUNNING (not synced or not verified); handle by hand")
            return "stop_unconfirmed"
        return None


# ---------------------------------------------------------------- CLI

def project_root() -> Path:
    p = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / ".rak").is_dir():
            return d
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rak_cloud")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precheck"); p.add_argument("--job-hours", type=float)
    p = sub.add_parser("create"); p.add_argument("name"); p.add_argument("--job", required=True, help="gs:// URL of the job script"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("wait"); p.add_argument("name")
    p = sub.add_parser("state"); p.add_argument("name"); p.add_argument("--zone", required=True)
    p = sub.add_parser("ledger"); p.add_argument("--since")
    p = sub.add_parser("delete"); p.add_argument("name"); p.add_argument("--zone", required=True)
    a = ap.parse_args(argv)
    root = project_root()
    try:
        cfg = load_config(root)
        g = Gcloud(cfg)
        if a.cmd == "precheck":
            fails = precheck(cfg, g, root, a.job_hours)
            for f in fails:
                print("FAIL", f)
            print("PRECHECK", "FAILED" if fails else "OK")
            return 1 if fails else 0
        if a.cmd == "create":
            create(cfg, g, root, a.name, a.job, a.yes)
        elif a.cmd == "wait":
            w = Waiter(cfg, g, root, a.name)
            while (reason := w.poll()) is None:
                time.sleep(cfg["poll_s"])
            return 0 if reason == "done" else 2
        elif a.cmd == "state":
            print(vm_state(g, a.name, a.zone))
        elif a.cmd == "ledger":
            print(f"US${Ledger(cfg, g, root).spent_usd(a.since):.2f} (conservative: {cfg['price_per_vm_hour']}/VM-hour, insert -> delete/preempt)")
        elif a.cmd == "delete":
            ok = delete_and_verify(g, a.name, a.zone)
            print("DELETED" if ok else "DELETE_CHECK_FAILED")
            return 0 if ok else 1
    except CloudError as e:
        print(f"rak-cloud: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
