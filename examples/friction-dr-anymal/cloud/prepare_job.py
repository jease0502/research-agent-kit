#!/usr/bin/env python3
"""Build the job folder for one cloud run of this example (local; uploads nothing).

  python cloud/prepare_job.py --repo <git root> --out <job dir> --vm-name rak-fdr-1 --bucket gs://<bucket>/<prefix>

Refuses unless the example is committed and clean and its prereg is frozen at HEAD with matching hashes:
the VM runs exactly the frozen commit, checked again on the VM (sha256 of the archive + COMMIT inside it).
Prints the gcloud commands that upload the job and create the VM; running them is a separate, approved step.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

EXAMPLE_REL = "examples/friction-dr-anymal"
PREREG_ID = "friction-dr-anymal"


class PrepareError(Exception):
    pass


def git(repo: Path, *args: str, binary=False):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise PrepareError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout if binary else r.stdout.decode()


def sha_lf(b: bytes) -> str:
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


def prepare(repo: Path, out: Path, vm_job: Path) -> dict:
    if git(repo, "status", "--porcelain", "--", EXAMPLE_REL).strip():
        raise PrepareError(f"{EXAMPLE_REL} has uncommitted changes; the VM must run a commit, not a working tree")
    commit = git(repo, "rev-parse", "HEAD").strip()
    rec_path = f"{EXAMPLE_REL}/.rak/frozen/{PREREG_ID}.json"
    try:
        rec = json.loads(git(repo, "show", f"HEAD:{rec_path}"))
    except PrepareError:
        raise PrepareError(f"prereg {PREREG_ID} is not frozen at HEAD ({rec_path} missing); freeze before running") from None
    for key, hkey in (("prereg", "prereg_sha256"), ("verdict_script", "verdict_sha256")):
        blob = git(repo, "show", f"HEAD:{EXAMPLE_REL}/{rec[key]}", binary=True)
        if sha_lf(blob) != rec[hkey]:
            raise PrepareError(f"{rec[key]} at HEAD does not match its frozen hash")
    for frel, h in (rec.get("frozen_files") or {}).items():   # scorer, protocol, aggregation frozen with the prereg
        try:
            blob = git(repo, "show", f"HEAD:{EXAMPLE_REL}/{frel}", binary=True)
        except PrepareError:
            raise PrepareError(f"{frel} (frozen with the prereg) is missing at HEAD") from None
        if sha_lf(blob) != h:
            raise PrepareError(f"{frel} (frozen with the prereg) at HEAD does not match its frozen hash")
    for drel, files in (rec.get("frozen_trees") or {}).items():   # whole folders, file by file, at HEAD
        base = f"{EXAMPLE_REL}/{drel}"
        listed = [p for p in git(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", base).splitlines() if p]
        now = {}
        for p in listed:
            rel = p[len(base) + 1:]
            parts = rel.split("/")
            if {"__pycache__", ".pytest_cache", ".git"} & set(parts) or rel.endswith((".pyc", ".pyo")):
                continue
            now[rel] = sha_lf(git(repo, "show", f"HEAD:{p}", binary=True))
        if now != files:
            diff = sorted(set(now) ^ set(files)) + sorted(k for k in set(now) & set(files) if now[k] != files[k])
            raise PrepareError(f"{drel}/ (frozen with the prereg) differs at HEAD: {', '.join(diff[:5])}")
    if out.exists() and any(out.iterdir()):
        raise PrepareError(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    # archive of the example at HEAD, plus COMMIT
    raw = git(repo, "archive", "--format=tar", f"HEAD:{EXAMPLE_REL}", binary=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(raw)) as src, tarfile.open(fileobj=buf, mode="w:gz") as dst:
        for m in src.getmembers():
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
        info = tarfile.TarInfo("COMMIT"); data = (commit + "\n").encode(); info.size = len(data)
        dst.addfile(info, io.BytesIO(data))
    (out / "code.tgz").write_bytes(buf.getvalue())
    digest = hashlib.sha256(buf.getvalue()).hexdigest()
    (out / "code.sha256").write_text(f"{digest}  code.tgz\n", encoding="utf-8", newline="\n")
    tmpl = (repo / EXAMPLE_REL / "cloud/steps.sh.tmpl").read_text(encoding="utf-8")
    if tmpl.count("@@COMMIT@@") != 1:
        raise PrepareError("steps.sh.tmpl must contain @@COMMIT@@ exactly once")
    (out / "steps.sh").write_text(tmpl.replace("@@COMMIT@@", commit), encoding="utf-8", newline="\n")
    shutil.copyfile(vm_job, out / "vm_job.sh")
    for f in ("steps.sh", "vm_job.sh"):
        b = (out / f).read_bytes()
        if b"\r" in b:
            raise PrepareError(f"{f} contains CR bytes")
        r = subprocess.run(["bash", "-n"], input=b, capture_output=True)
        if r.returncode != 0:
            raise PrepareError(f"{f}: bash -n failed: {r.stderr.decode(errors='replace')[:200]}")
    return {"commit": commit, "code_sha256": digest, "out": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--vm-name", required=True)
    ap.add_argument("--bucket", required=True, help="the bucket value of .rak/cloud.json")
    ap.add_argument("--vm-job", help="defaults to <repo>/templates/cloud/vm_job.sh")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        info = prepare(repo, Path(a.out).resolve(), Path(a.vm_job) if a.vm_job else repo / "templates/cloud/vm_job.sh")
    except PrepareError as e:
        print(f"prepare_job: {e}", file=sys.stderr)
        return 1
    base = f"{a.bucket.rstrip('/')}/{a.vm_name}"
    print(f"commit {info['commit']}  code.tgz sha256 {info['code_sha256']}")
    print("# upload (not run by this script):")
    print(f"gcloud storage cp {a.out}/code.tgz {a.out}/code.sha256 {base}/code/")
    print(f"gcloud storage cp {a.out}/vm_job.sh {a.out}/steps.sh {base}/job/")
    print("# then, with the approved budget:")
    print(f"python <rak-cloud>/scripts/rak_cloud.py create {a.vm_name} --job {base}/job/          # dry run first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
