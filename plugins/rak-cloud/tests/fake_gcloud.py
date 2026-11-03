#!/usr/bin/env python3
"""A fake gcloud for tests. State lives in $FAKE_GCLOUD_DIR:
  config.json     knobs: auth_ok, net_fail, hang_s, images {family: size}, stockout_zones, sa_exists, delete_fails,
                  disk_left, rsync_drop [substrings never copied], logs [audit entries]
  instances.json  {name: {zone, status}}
  gcs/            gs://bucket/path -> gcs/bucket/path
  calls.jsonl     one line per call (argv)
Only the subcommands rak-cloud uses are implemented; anything else exits 2 so a new call cannot pass silently.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

D = Path(os.environ["FAKE_GCLOUD_DIR"])


def cfg():
    f = D / "config.json"
    return json.loads(f.read_text()) if f.exists() else {}


def insts():
    f = D / "instances.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_insts(x):
    (D / "instances.json").write_text(json.dumps(x))


def local(p):
    return D / "gcs" / p[5:] if p.startswith("gs://") else Path(p)


def flags(args):
    pos, fl = [], {}
    for a in args:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            fl[k] = v if v else True
        elif a.startswith("-") and a != "-":
            fl[a[1:]] = True
        else:
            pos.append(a)
    return pos, fl


def files_under(p: Path):
    if p.is_file():
        return [(p, "")]
    return [(f, f.relative_to(p).as_posix()) for f in sorted(p.rglob("*")) if f.is_file()] if p.is_dir() else []


def main():
    a = sys.argv[1:]
    with open(D / "calls.jsonl", "a") as f:
        f.write(json.dumps(a) + "\n")
    c = cfg()
    if c.get("hang_s"):
        time.sleep(c["hang_s"])
    if c.get("net_fail"):
        print("ERROR: gcloud crashed (ConnectionError): timed out", file=sys.stderr); return 1
    if a[:2] == ["auth", "print-access-token"]:
        if c.get("auth_ok", True):
            print("ya29.fake"); return 0
        print("ERROR: There was a problem refreshing your current auth tokens: Reauthentication failed.", file=sys.stderr); return 1
    if not c.get("auth_ok", True):
        print("ERROR: (gcloud) There was a problem refreshing your current auth tokens: Reauthentication failed.", file=sys.stderr); return 1
    pos, fl = flags(a)
    if pos[:1] == ["storage"]:
        op = pos[1]
        if op == "ls":
            p = local(pos[2])
            if p.exists():
                return 0
            print("ERROR: One or more URLs matched no objects.", file=sys.stderr); return 1
        if op == "cat":
            p = local(pos[2])
            if not p.is_file():
                print("ERROR: No URLs matched", file=sys.stderr); return 1
            sys.stdout.write(p.read_text()); return 0
        if op == "cp":
            src, dst = pos[2], local(pos[3])
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src == "-":
                dst.write_text(sys.stdin.read())
            else:
                s = local(src)
                if not s.exists():
                    return 1
                shutil.copy(s, dst)
            return 0
        if op == "rsync":
            src, dst = local(pos[2]), local(pos[3])
            drop = c.get("rsync_drop", [])
            for f, rel in files_under(src):
                t = dst / rel
                differ = not t.is_file() or t.read_bytes() != f.read_bytes()
                if not differ:
                    continue
                if fl.get("dry-run"):
                    print(f"Would copy {f} to {t}"); continue
                if any(s in rel for s in drop):
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, t)
            return 0
    if pos[:2] == ["compute", "images"]:
        size = c.get("images", {}).get(pos[3])
        if size is None:
            print("ERROR: not found", file=sys.stderr); return 1
        print(size); return 0
    if pos[:2] == ["compute", "instances"]:
        op, name, zone = pos[2], pos[3], fl.get("zone")
        x = insts()
        if op == "create":
            if zone in c.get("stockout_zones", []):
                print(f"ERROR: The zone '{zone}' does not have enough resources (ZONE_RESOURCE_POOL_EXHAUSTED)", file=sys.stderr); return 1
            x[name] = {"zone": zone, "status": "RUNNING", "argv": a}; save_insts(x); return 0
        if op == "describe":
            if name in x and x[name]["zone"] == zone:
                print(x[name]["status"]); return 0
            print(f"ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n - The resource 'projects/p/zones/{zone}/instances/{name}' was not found", file=sys.stderr)
            return 1
        if op == "delete":
            if c.get("delete_fails"):
                print("ERROR: Required 'compute.instances.delete' permission", file=sys.stderr); return 1
            x.pop(name, None); save_insts(x); return 0
    if pos[:3] == ["compute", "disks", "list"]:
        if c.get("disk_left"):
            print(fl.get("filter", "").split("=", 1)[-1])
        return 0
    if pos[:2] == ["iam", "service-accounts"] and pos[2] == "describe":
        if c.get("sa_exists", True):
            print(pos[3]); return 0
        print("ERROR: NOT_FOUND", file=sys.stderr); return 1
    if pos[:2] == ["logging", "read"]:
        print(json.dumps(c.get("logs", []))); return 0
    print(f"fake gcloud: unsupported call {a}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
