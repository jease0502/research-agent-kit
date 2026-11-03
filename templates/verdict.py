#!/usr/bin/env python3
"""Verdict script for prereg `__PREREG_ID__`. Written and committed BEFORE any result exists.

  python verdict.py gate  --evidence gate_results.json   # positive / negative controls -> .rak/gates/<id>.json
  python verdict.py judge --results results.json         # refuses unless the gate is PASS

Rules this skeleton enforces (keep them when you fill it in):
  * Compare raw values. Never round before comparing; round only when printing.
  * Every threshold lives in GATES / CRITERIA below. This file is hashed at freeze time; editing it
    afterwards makes `judge` refuse. A wrong threshold is corrected in an erratum, not here.
  * Unknown CLI flags and unknown keys in the input JSON raise. A silently ignored flag or a renamed
    metric means you are judging something you did not register.
  * Each criterion is PASS / FAIL / UNDETERMINED (missing data, run crashed, n too small).
    UNDETERMINED is never reported as PASS or FAIL.
  * The output carries the hashes of the prereg, this script and the input, so a verdict can be traced
    to exactly what was registered and what was read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

PREREG_ID = "__PREREG_ID__"

# ---- registered before the data: fill in, commit, then freeze ----
# name: (metric key in the evidence json, lower bound or None, upper bound or None)
GATES = {
    # "positive_control_recovers_known_value": ("pos_ctrl_rel_err", None, 0.05),
    # "negative_control_shows_no_effect":      ("neg_ctrl_effect", -0.02, 0.02),
    # "control_arm_reproduces_last_round":     ("ctrl_arm_delta", -0.03, 0.03),
}
# name: (metric key in the results json, comparison, threshold, min_n)
CRITERIA = {
    # "treatment_beats_control": ("treatment_minus_control", ">=", 0.05, 5),
}
EXPECTED_RESULT_KEYS: set[str] = set()      # every key the results json may contain; others raise
EXPECTED_EVIDENCE_KEYS: set[str] = set()
# -------------------------------------------------------------------

OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def root() -> Path:
    p = Path.cwd().resolve()
    for d in [p, *p.parents]:
        if (d / ".rak").is_dir():
            return d
    raise SystemExit("no .rak/ directory above the current directory")


def frozen(r: Path) -> dict:
    f = r / ".rak" / "frozen" / f"{PREREG_ID}.json"
    if not f.is_file():
        raise SystemExit(f"prereg {PREREG_ID} is not frozen")
    rec = json.loads(f.read_text(encoding="utf-8"))
    if sha(r / rec["prereg"]) != rec["prereg_sha256"]:
        raise SystemExit(f"{rec['prereg']} changed after freezing (frozen at {rec['commit'][:10]})")
    if sha(Path(__file__).resolve()) != rec["verdict_sha256"]:
        raise SystemExit("this verdict script changed after freezing; judge with the frozen version")
    # the scorer, thresholds and tables listed under `frozen_files:` in the prereg (gate and judge both refuse)
    for frel, h in (rec.get("frozen_files") or {}).items():
        p = r / frel
        if not p.is_file() or sha(p) != h:
            raise SystemExit(f"{frel} (frozen with the prereg) is missing or changed after freezing; not reading anything")
    # whole folders under `frozen_trees:` (e.g. the plugin that is the treatment): no file added, removed or changed
    for drel, files in (rec.get("frozen_trees") or {}).items():
        d = r / drel
        now = {}
        for p in sorted(d.rglob("*")) if d.is_dir() else []:
            rel = p.relative_to(d)
            if p.is_file() and not set(rel.parts) & {"__pycache__", ".pytest_cache", ".git"} \
                    and not p.name.endswith((".pyc", ".pyo")):
                now[rel.as_posix()] = sha(p)
        if now != files:
            changed = sorted(set(now) ^ set(files)) + sorted(k for k in set(now) & set(files) if now[k] != files[k])
            raise SystemExit(f"{drel}/ (frozen with the prereg) changed after freezing ({', '.join(changed[:5])}); "
                             "not reading anything")
    return rec


def load_strict(path: str, expected: set[str]) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(data) - expected
    if unknown:
        raise SystemExit(f"{path}: keys not registered: {sorted(unknown)}")
    return data


def cmd_gate(evidence: str) -> int:
    r = root(); rec = frozen(r)
    if not GATES:
        raise SystemExit("GATES is empty: register at least one positive control")
    ev = load_strict(evidence, EXPECTED_EVIDENCE_KEYS)
    checks = {}
    for name, (key, lo, hi) in GATES.items():
        v = ev.get(key)
        ok = v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)   # raw values
        checks[name] = {"value": v, "lo": lo, "hi": hi, "passed": bool(ok)}
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {v!r} in [{lo}, {hi}]")
    status = "PASS" if all(c["passed"] for c in checks.values()) else "FAIL"
    out = {"id": PREREG_ID, "status": status, "prereg_sha256": rec["prereg_sha256"],
           "verdict_sha256": rec["verdict_sha256"], "evidence_sha256": sha(Path(evidence)), "checks": checks,
           "written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    g = r / ".rak" / "gates" / f"{PREREG_ID}.json"
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"GATE {status} -> {g}")
    return 0 if status == "PASS" else 1


def cmd_judge(results: str, out: str | None) -> int:
    r = root(); rec = frozen(r)
    g = r / ".rak" / "gates" / f"{PREREG_ID}.json"
    gate = json.loads(g.read_text(encoding="utf-8")) if g.is_file() else {}
    if gate.get("status") != "PASS" or gate.get("prereg_sha256") != rec["prereg_sha256"] \
            or gate.get("verdict_sha256") != rec["verdict_sha256"]:
        raise SystemExit(f"GATE_FAIL: gate is {gate.get('status', 'NONE')} (or recorded against other files); not reading results")
    res = load_strict(results, EXPECTED_RESULT_KEYS)
    verdicts = {}
    for name, (key, op, thr, min_n) in CRITERIA.items():
        v, n = res.get(key), res.get(f"{key}__n")
        if v is None or (min_n and (n is None or n < min_n)):
            verdicts[name] = {"verdict": "UNDETERMINED", "value": v, "n": n}
        else:
            verdicts[name] = {"verdict": "PASS" if OPS[op](v, thr) else "FAIL", "value": v, "n": n, "rule": f"{op} {thr}"}
        print(f"{verdicts[name]['verdict']:12s} {name}: {v!r} {op} {thr} (n={n})")
    rec_out = {"id": PREREG_ID, "verdicts": verdicts, "prereg_sha256": rec["prereg_sha256"],
               "verdict_sha256": rec["verdict_sha256"], "results_sha256": sha(Path(results)),
               "judged_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if out:
        p = Path(out)
        if p.exists():
            raise SystemExit(f"{out} exists; verdict files are written once")
        p.write_text(json.dumps(rec_out, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("gate"); p.add_argument("--evidence", required=True)
    p = sub.add_parser("judge"); p.add_argument("--results", required=True); p.add_argument("--out")
    a = ap.parse_args()  # argparse raises on unknown flags
    return cmd_gate(a.evidence) if a.cmd == "gate" else cmd_judge(a.results, a.out)


if __name__ == "__main__":
    sys.exit(main())
