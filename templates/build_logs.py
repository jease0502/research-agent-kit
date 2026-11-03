#!/usr/bin/env python3
"""Extract the numbers a lesson cites from run logs, then render the lesson.

  python build_logs.py extract --logs handson/<lesson>/logs --out handson/<lesson>/numbers.json
  python build_logs.py render  --src lesson.src.md --numbers numbers.json --out lesson.md
  python build_logs.py check   --src lesson.src.md --numbers numbers.json

Pattern: one EXTRACTORS entry per number. Each says which log file and how to read it, so every
number in the lesson can be traced to one file and one rule. If a log is missing or a rule matches
nothing, extract raises: a lesson must not render with a stale or invented number.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# key: (log file relative to --logs, kind, spec, format)
#   kind "json": spec is a dotted path into the json        e.g. "verdicts.C1.value"
#   kind "regex": spec is a regex with one group, last match e.g. r"success_rate=([0-9.]+)"
EXTRACTORS: dict[str, tuple[str, str, str, str]] = {
    # "control_success":   ("control/summary.json", "json", "success_rate", "{:.2f}"),
    # "control_n":         ("control/summary.json", "json", "n", "{}"),
    # "verdict_C1":        ("verdict.json", "json", "verdicts.C1.verdict", "{}"),
}

PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def extract(logs: Path) -> dict:
    out = {}
    for key, (rel, kind, spec, fmt) in EXTRACTORS.items():
        f = logs / rel
        if not f.is_file():
            raise SystemExit(f"{key}: {f} does not exist")
        if kind == "json":
            v = json.loads(f.read_text(encoding="utf-8"))
            for part in spec.split("."):
                if not isinstance(v, dict) or part not in v:
                    raise SystemExit(f"{key}: {spec} not found in {f}")
                v = v[part]
        elif kind == "regex":
            m = re.findall(spec, f.read_text(encoding="utf-8", errors="replace"))
            if not m:
                raise SystemExit(f"{key}: /{spec}/ matched nothing in {f}")
            v = m[-1]
            v = float(v) if re.fullmatch(r"-?[0-9.]+(e-?[0-9]+)?", str(v)) else v
        else:
            raise SystemExit(f"{key}: unknown kind {kind!r}")
        out[key] = {"value": v, "text": fmt.format(v), "source": rel, "source_sha256": sha(f)}
    return out


def check(src: str, numbers: dict) -> list[str]:
    problems = [f"unknown key {{{{{k}}}}}" for k in PLACEHOLDER.findall(src) if k not in numbers]
    in_results = False
    for i, line in enumerate(src.splitlines(), 1):
        if line.startswith("## "):
            in_results = line.strip().lower() in ("## what happened",)
        if in_results and re.search(r"(?<![\w{.])\d+\.\d+(?![\w}])", PLACEHOLDER.sub("", line)):
            problems.append(f"line {i}: bare decimal in a results section; use a {{{{key}}}} placeholder")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract"); p.add_argument("--logs", required=True); p.add_argument("--out", required=True)
    for name in ("render", "check"):
        p = sub.add_parser(name); p.add_argument("--src", required=True); p.add_argument("--numbers", required=True)
        if name == "render":
            p.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "extract":
        nums = extract(Path(a.logs))
        Path(a.out).write_text(json.dumps(nums, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(nums)} numbers -> {a.out}")
        return 0
    src = Path(a.src).read_text(encoding="utf-8")
    nums = json.loads(Path(a.numbers).read_text(encoding="utf-8"))
    probs = check(src, nums)
    for pr in probs:
        print("PROBLEM", pr, file=sys.stderr)
    if a.cmd == "check":
        return 1 if probs else 0
    if any(p.startswith("unknown key") for p in probs):
        return 1
    Path(a.out).write_text(PLACEHOLDER.sub(lambda m: nums[m.group(1)]["text"], src), encoding="utf-8", newline="\n")
    print(f"rendered -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
