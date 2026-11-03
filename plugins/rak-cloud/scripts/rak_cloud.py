#!/usr/bin/env python3
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
sys.path.insert(0, str(HERE))
import bt  # noqa: E402

TEMPLATES = HERE.parent.parent.parent / "templates" / "cloud"
# The job lifecycle is a behaviour tree in trees/lifecycle.json, run by bt.py. The agent does not edit it (the
# plugin's hook refuses edits to trees/); these pins make an edit that slips past the hook stop the run instead.
# A deliberate change to the tree updates the pin in the same commit, with a test for the new branch.
TREE_FILE = HERE.parent / "trees" / "lifecycle.json"
TREE_SHA256 = {
    "create": "9c9b302d368277ba9cfb70bd4fac58288a3aca32c213f9ca68fb4f39d6c754d9",
    "wait": "3f74a54c3a76efb2af42ea5ca9f338c9372c87aac7415d7b49de1051fbfaf20f",
}

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
DELETE_ATTEMPTS = 3                               # unconfirmed deletes before the waiter stops and asks for a person
# exit codes of `wait`, by end reason. 2 is also argparse's usage error (known overlap, to be settled before release).
# stop_unconfirmed was 2 until the maintainer's decision after 8e0c5ee: it means the VM is still running and billing.
EXIT = {"done": 0, "gone": 2, "delete_unverified": 3, "gone_unverified": 4, "stop_unconfirmed": 5}


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


def trace_file(root: Path, name: str) -> Path:
    return root / ".rak" / "cloud" / "trace" / f"{name}.jsonl"


def write_trace_or_say(f: Path, records: list[dict], say, **extra) -> None:
    """A trace that cannot be written is reported, never fatal: the job and the VM matter more than the record
    of them, and inside a `finally` an exception here would replace the tick's own."""
    try:
        bt.write_trace(f, records, **extra)
    except OSError as e:
        say(f"{type(e).__name__}: {e}")


def lifecycle_tree(key: str, registry: dict, clock=time.time) -> bt.Tree:
    return bt.load_tree(TREE_FILE, key, registry, TREE_SHA256[key], clock)


def create(cfg: dict, g: Gcloud, root: Path, name: str, job_url: str, yes: bool, out=print) -> str | None:
    """Runs the "create" tree once: precheck, then one attempt per zone in order (without --yes, a dry run of
    the first zone only). Returns the zone, or None for a dry run."""
    out_url = f"{cfg['bucket'].rstrip('/')}/{name}/out"
    bb = {"name": name, "zones": list(cfg["zones"]), "n_zones": len(cfg["zones"]), "zone_i": 0, "zone": None,
          "error": "every zone failed"}

    def precheck_leaf(bb):
        fails = precheck(cfg, g, root)
        if fails:
            bb["error"] = "precheck failed:\n  - " + "\n  - ".join(fails)
            return bt.FAILURE, f"{len(fails)} failure(s)"
        return bt.SUCCESS

    def create_in_next_zone(bb):
        zone = bb["zones"][bb["zone_i"]]
        bb["zone_i"] += 1
        cmd = create_command(cfg, name, zone, job_url, out_url)
        guard_command(cmd)
        if not yes:
            out("DRY RUN (nothing created; --yes to create). First zone's command:")
            out("gcloud " + " ".join(cmd))
            return bt.SUCCESS, f"dry run {zone}"
        r = g(*cmd, timeout=600)
        if r.rc == 0:
            record_instance(root, name, zone)
            out(f"CREATED {name} {zone}")
            bb["zone"] = zone
            return bt.SUCCESS, zone
        last = r.err.strip().splitlines()[-1] if r.err.strip() else r.rc
        out(f"CREATE_FAIL {zone}: {last}")
        return bt.FAILURE, f"{zone}: {str(last)[:160]}"

    tree = lifecycle_tree("create", {"precheck": precheck_leaf, "create_in_next_zone": create_in_next_zone})
    try:
        status = tree.tick(bb)
    finally:
        if yes:   # a dry run leaves no files behind
            write_trace_or_say(trace_file(root, name), tree.trace, lambda e: out(f"TRACE_WRITE_FAILED {name} {e}"),
                               t=time.time())
    if status != bt.SUCCESS:
        raise CloudError(bb["error"])
    return bb["zone"]


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


MANIFEST_MISSING = "MANIFEST.sha256 missing: the job did not finish writing its outputs, or the pull is incomplete"


def manifest_line(ln: str) -> tuple[str, str] | None:
    """(sha256, relative path) of one sha256sum line, or None if it is not one."""
    m = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", ln.strip())   # text mode "  " or binary mode " *"
    if not m:
        return None
    rel = m.group(2)
    return m.group(1), rel[2:] if rel.startswith("./") else rel


def manifest_entries(text: str) -> list[tuple[str, str]]:
    return [e for e in (manifest_line(ln) for ln in text.splitlines() if ln.strip()) if e]


def verify_pull(local: Path) -> list[str]:
    """Every file listed in MANIFEST.sha256 (written by vm_job.sh at its end) must be here with the same hash."""
    man = local / "MANIFEST.sha256"
    if not man.is_file():
        return [MANIFEST_MISSING]
    problems = []
    lines = [ln for ln in man.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        problems.append("MANIFEST.sha256 is empty")
    for ln in lines:
        e = manifest_line(ln)
        if not e:
            problems.append(f"unreadable manifest line: {ln[:80]!r}")
            continue
        h, rel = e
        p = local / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif sha256_file(p) != h:
            problems.append(f"hash differs {rel}")
    return problems


REQUIRED_HEADER = "# rak-required v1"


def read_required(local: Path) -> tuple[str, list[str], str]:
    """(state, declared output paths, source) from REQUIRED.txt (vm_job.sh writes it before the first step).
    state "ok"; "unknown" when it is missing or its header is not one this version knows (not guessed at: the
    caller falls back to the manifest alone); "invalid" when a path is absolute or has "..", which vm_job refuses
    to write, so the file was changed or damaged (cross-review of 8e0c5ee)."""
    f = local / "REQUIRED.txt"
    if not f.is_file():
        return "unknown", [], "REQUIRED.txt missing"
    lines = f.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != REQUIRED_HEADER:
        return "unknown", [], f"REQUIRED.txt header {(lines[0] if lines else '')[:40]!r} not recognized"
    paths = [ln.strip() for ln in lines[1:] if ln.strip()]
    bad = [p for p in paths if p.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", p) or ".." in re.split(r"[\\/]", p)]
    if bad:
        return "invalid", [], f"REQUIRED.txt invalid: absolute or '..' path {bad[0][:80]!r}"
    return "ok", [p.removeprefix("./") for p in paths], "REQUIRED.txt"


def required_met(p: str, listed: set[str]) -> bool:
    """A declared output is met by the manifest entry of that name, or, for a directory ("train" or "train/"), by
    at least one entry under it: vm_job accepts a non-empty directory as an output, and the manifest lists files."""
    q = p.rstrip("/")
    return q in listed or any(e.startswith(q + "/") for e in listed)


def required_problems(local: Path, required: list[str], manifest_problems: list[str]) -> list[str]:
    """Everything not verified, judged by the required list with the manifest's hashes: the manifest's own problems,
    plus every required path the manifest does not vouch for. All of them, not the first few."""
    man = local / "MANIFEST.sha256"
    if not man.is_file():
        def here(p):
            x = local / p.rstrip("/")
            return x.is_file() or (x.is_dir() and any(y.is_file() for y in x.rglob("*")))
        return ["MANIFEST.sha256 missing"] + [
            f"required, here but no hash to check: {p}" if here(p) else f"required, missing: {p}" for p in required]
    listed = {rel for _, rel in manifest_entries(man.read_text(encoding="utf-8"))}
    return list(manifest_problems) + [f"required, not in the manifest: {p}" for p in required if not required_met(p, listed)]


def delete_and_verify(g: Gcloud, name: str, zone: str) -> bool:
    g("compute", "instances", "delete", name, f"--zone={zone}", "--quiet", timeout=600)
    gone = vm_state(g, name, zone) == "GONE"
    r = g("compute", "disks", "list", f"--filter=name={name}", "--format=value(name)")
    return gone and r.rc == 0 and not r.out.strip()


# ---------------------------------------------------------------- waiter

class Waiter:
    """One VM. poll() is one tick of the "wait" tree; the CLI calls it every poll_s seconds.

    Prints one keyword per line (PROGRESS, STALL, VM_STATE_UNKNOWN, VM_GONE, BUDGET_REPORT, BUDGET_STOP,
    STOP_SENT, STOP_UNCONFIRMED, PULL_INCOMPLETE, PULLED_OK, DELETED, DELETE_CHECK_FAILED, DELETE_GAVE_UP,
    OUTPUTS_UNVERIFIED, REQUIRED_MISSING, TRACE_WRITE_FAILED, END) so a monitor can grep it. The VM is deleted only after the pull
    is verified; a VM whose outputs cannot be verified is left running (its max-run still applies) and reported.
    A delete that cannot be confirmed is tried DELETE_ATTEMPTS times, then the waiter stops (delete_unverified).
    A VM that is gone ends "gone" only if every file in its manifest is verified here, else "gone_unverified".

    The decisions are the tree in trees/lifecycle.json; the leaves below are the only code it calls, and the
    blackboard (self.bb) is the only state kept between ticks. Each tick appends its trace (node path, status,
    reason) to .rak/cloud/trace/<name>.jsonl; bt.leaf_at() on the last tick says where the waiter is.
    """

    def __init__(self, cfg, g, root, name, clock=time.time, out=print):
        self.cfg, self.g, self.root, self.name, self.clock, self.out = cfg, g, root, name, clock, out
        inst = json.loads(instances_file(root).read_text(encoding="utf-8"))[name]
        self.bb = {
            "name": name, "zone": inst["zone"], "created": inst["created"],
            "prefix": f"{cfg['bucket'].rstrip('/')}/{name}", "local": str(Path(cfg["local_dir"]) / name),
            "status": None, "vm": None, "last_seen": None, "last_change": clock(),
            "reported": False, "stopping": False, "stop_sent_at": None, "stop_wait_s": cfg["stop_wait_min"] * 60,
            "verified": [], "unverified": [], "delete_attempts": 0, "end": None,
        }
        self.tree = lifecycle_tree("wait", {
            "observe": self._observe, "vm_state_known": lambda bb: bb["vm"] != "UNKNOWN",
            "report_unknown": self._report_unknown, "budget": self._budget,
            "vm_is_gone": lambda bb: bb["vm"] == "GONE", "salvage_outputs": self._salvage_outputs,
            "job_ended_or_vm_stopped": self._ended_or_stopped, "pull_and_verify": self._pull_and_verify,
            "outputs_verified": lambda bb: not bb["unverified"], "report_gone": self._report_gone,
            "report_gone_unverified": self._report_gone_unverified,
            "delete_vm": self._delete_vm, "report_done": self._report_done, "give_up_delete": self._give_up_delete,
            "stop_sent": lambda bb: bb["stopping"], "await_stop": lambda bb: (bt.RUNNING, "stop sent, waiting"),
            "give_up_stop": self._give_up_stop, "keep_waiting": lambda bb: (bt.RUNNING, f"status={bb['status']}"),
        }, clock)

    # names the tests and older callers use
    zone = property(lambda self: self.bb["zone"])
    created = property(lambda self: self.bb["created"])
    prefix = property(lambda self: self.bb["prefix"])
    local = property(lambda self: Path(self.bb["local"]))

    def say(self, kw, msg=""):
        self.out(f"{kw} {dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {self.name} {msg}".rstrip())

    def cost(self) -> float:
        return (self.clock() - self.created) / 3600 * self.cfg["price_per_vm_hour"]

    def status(self) -> str:
        r = self.g("storage", "cat", f"{self.prefix}/out/status.txt")
        return r.out.strip() if r.rc == 0 else "none"

    def _mark_ended(self):
        self._record("ended", self.clock())

    def _record(self, key, value):
        f = instances_file(self.root)
        d = json.loads(f.read_text(encoding="utf-8"))
        d[self.name][key] = value
        f.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8", newline="\n")

    def _rsync(self):
        self.local.mkdir(parents=True, exist_ok=True)
        self.g("storage", "rsync", "-r", f"{self.prefix}/out", str(self.local), timeout=1800)

    # ------------------------------------------------------------ leaves

    def _observe(self, bb):
        st, vm = self.status(), vm_state(self.g, self.name, self.zone)
        bb["status"], bb["vm"] = st, vm
        if (st, vm) != bb["last_seen"]:
            self.say("PROGRESS", f"vm={vm} status={st}")
            bb["last_seen"], bb["last_change"] = (st, vm), self.clock()
        elif self.clock() - bb["last_change"] >= self.cfg["stall_min"] * 60:
            self.say("STALL", f"no change for {self.cfg['stall_min']} min (vm={vm} status={st})")
            bb["last_change"] = self.clock()
        return bt.SUCCESS, f"vm={vm} status={st}"

    def _report_unknown(self, bb):
        self.say("VM_STATE_UNKNOWN", "cannot ask GCP (credentials? network?); NOT treated as gone")
        return bt.RUNNING, "vm state UNKNOWN: query failed, not treated as gone"

    def _budget(self, bb):
        c = self.cost()
        if not bb["reported"] and c >= self.cfg["report_at_usd"]:
            self.say("BUDGET_REPORT", f"US${c:.2f} (conservative)"); bb["reported"] = True
        if not bb["stopping"] and c >= self.cfg["stop_at_usd"]:
            self.say("BUDGET_STOP", f"US${c:.2f} >= {self.cfg['stop_at_usd']}")
            r = self.g("storage", "cp", "-", f"{self.prefix}/control/stop", input=f"stop {self.clock()}\n")  # job polls for it
            self.say("STOP_SENT" if r.rc == 0 else "STOP_SEND_FAILED")
            bb["stopping"], bb["stop_sent_at"] = True, self.clock()
        return bt.SUCCESS, f"US${c:.2f}"

    @staticmethod
    def _terminal(st: str) -> bool:
        return st in TERMINAL or st.startswith("FAIL_")

    def _salvage_outputs(self, bb):
        if not self._terminal(bb["status"]):
            self.say("VM_GONE", f"before a terminal status (status={bb['status']}): preempted, max-run, or deleted elsewhere")
        self._mark_ended()
        self._rsync()
        problems = verify_pull(self.local)
        bb["salvage_problems"] = problems
        state, bb["required"], bb["required_source"] = read_required(self.local)
        if state == "unknown":
            # manifest-only rule: every manifest entry must verify; no manifest means nothing says what was required
            bb["unverified"] = ["MANIFEST.sha256 missing (required list unknown)" if x == MANIFEST_MISSING else x
                                for x in problems]
        elif state == "invalid":
            bb["unverified"] = [bb["required_source"], *problems]
        else:
            bb["unverified"] = required_problems(self.local, bb["required"], problems)
        bb["verified_by"] = ("REQUIRED.txt and manifest" if state == "ok" else
                             "manifest only; required list unknown")
        why = "; ".join(bb["unverified"][:2])
        return bt.SUCCESS, (f"outputs verified ({bb['required_source']})" if not bb["unverified"] else
                            f"outputs INCOMPLETE ({bb['required_source']}): {why}")

    def _report_gone(self, bb):
        self.say("END", f"VM gone; outputs verified ({bb['verified_by']})")
        bb["end"] = "gone"
        return bt.SUCCESS

    def _report_gone_unverified(self, bb):
        self.say("OUTPUTS_UNVERIFIED", f"{len(bb['unverified'])}: " + "; ".join(bb["unverified"]))
        self.say("END", "VM gone; outputs INCOMPLETE: " + "; ".join((bb["salvage_problems"] or bb["unverified"])[:2]))
        bb["end"] = "gone_unverified"
        return bt.SUCCESS, "; ".join(bb["unverified"])

    def _ended_or_stopped(self, bb):
        return self._terminal(bb["status"]) or bb["vm"] in ("TERMINATED", "STOPPED", "SUSPENDED")

    def _pull_and_verify(self, bb):
        self._rsync()
        left = self.g("storage", "rsync", "-r", "--dry-run", f"{self.prefix}/out", str(self.local), timeout=600)
        problems = verify_pull(self.local)
        if left.rc != 0 or "Would copy" in left.out + left.err:
            problems.insert(0, "objects in the bucket still differ from the local copy")
        if problems:
            self.say("PULL_INCOMPLETE", "; ".join(problems[:3]) + " -- VM kept, retrying")
            return bt.RUNNING, "; ".join(problems[:3])
        text = (self.local / "MANIFEST.sha256").read_text(encoding="utf-8")
        lines = text.splitlines()
        bb["verified"] = [rel for _, rel in manifest_entries(text)]
        self.say("PULLED_OK", f"{len(lines)} files verified against MANIFEST.sha256")
        # not a gate (a failed job lacks its declared outputs by design), but the record of what the deleted VM
        # did not produce: the line, the trace and instances.json (maintainer, after 8e0c5ee)
        state, required, source = read_required(self.local)
        missing = ([source] if state == "invalid" else
                   [p for p in required if not required_met(p, set(bb["verified"]))] if state == "ok" else [])
        if missing:
            self.say("REQUIRED_MISSING", f"{len(missing)} declared output(s) not produced: " + "; ".join(missing))
            self._record("required_missing", missing)
            return bt.SUCCESS, f"{len(lines)} files verified; REQUIRED_MISSING: " + "; ".join(missing)
        return bt.SUCCESS, f"{len(lines)} files verified"

    def _delete_vm(self, bb):
        ok = delete_and_verify(self.g, self.name, self.zone)
        self._mark_ended()
        self.say("DELETED" if ok else "DELETE_CHECK_FAILED", "(VM and disk gone)" if ok else "-- check by hand")
        if ok:
            return bt.SUCCESS, "VM and disk gone"
        bb["delete_attempts"] += 1
        why = f"VM or disk still listed after delete (attempt {bb['delete_attempts']} of {DELETE_ATTEMPTS})"
        return (bt.RUNNING if bb["delete_attempts"] < DELETE_ATTEMPTS else bt.FAILURE), why

    def _give_up_delete(self, bb):
        self.say("DELETE_GAVE_UP", f"{DELETE_ATTEMPTS} deletes not confirmed (VM or disk still listed); outputs are "
                 "verified locally; delete and check by hand")
        self.say("END", "delete_unverified")
        bb["end"] = "delete_unverified"
        return bt.SUCCESS, f"{DELETE_ATTEMPTS} unconfirmed deletes"

    def _report_done(self, bb):
        self.say("END", f"status={bb['status']}")
        bb["end"] = "done"
        return bt.SUCCESS

    def _give_up_stop(self, bb):
        self.say("STOP_UNCONFIRMED", f"status={bb['status']} -- VM LEFT RUNNING (not synced or not verified); handle by hand")
        bb["end"] = "stop_unconfirmed"
        return bt.SUCCESS, "stop not confirmed in time; VM left running"

    # ------------------------------------------------------------ tick

    def poll(self) -> str | None:
        """Returns None while running, else an END reason."""
        try:
            status = self.tree.tick(self.bb)
        finally:
            write_trace_or_say(trace_file(self.root, self.name), self.tree.trace,
                               lambda e: self.say("TRACE_WRITE_FAILED", e), t=self.clock())
        if status == bt.FAILURE:
            raise CloudError(f"wait tree failed: {bt.leaf_at(self.tree.trace)}")   # the tree ends in a RUNNING leaf
        return self.bb["end"] if status == bt.SUCCESS else None


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
            return EXIT[reason]
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
