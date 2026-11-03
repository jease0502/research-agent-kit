#!/usr/bin/env python3
"""Copy the policy engine (python/rak/policy/) into every plugin that has hooks, as _vendor/rak_policy/.

python/rak/policy/ is the only source: edit there, run this, commit both. A plugin must work without
`pip install`, so it carries its own copy; python/tests/test_policy_vendor.py fails when a copy differs from the
source by a single byte, or when a plugin with hooks has none.

  python scripts/vendor_policy.py          write the copies
  python scripts/vendor_policy.py --check  exit 1 if any copy differs (what the test runs)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "python" / "rak" / "policy"
FILES = ("__init__.py", "engine.py", "adapters.py", "checks_discipline.py", "checks_git.py", "checks_policy.py", "checks_trees.py",
         "rules.json")


def targets() -> list[Path]:
    return sorted(p.parent.parent / "_vendor" / "rak_policy" for p in REPO.glob("plugins/*/hooks/hooks.json"))


def differences() -> list[str]:
    out = []
    for t in targets():
        for f in FILES:
            a, b = SRC / f, t / f
            if not b.is_file() or a.read_bytes() != b.read_bytes():
                out.append(f"{b.relative_to(REPO).as_posix()} differs from python/rak/policy/{f}")
        extra = {p.name for p in t.glob("*") if p.is_file()} - set(FILES) if t.is_dir() else set()
        out += [f"{(t / x).relative_to(REPO).as_posix()} is not in the source" for x in sorted(extra)]
    return out


def main() -> int:
    if "--check" in sys.argv[1:]:
        d = differences()
        print("\n".join(d) or "vendored policy copies match the source")
        return 1 if d else 0
    for t in targets():
        if t.exists():
            shutil.rmtree(t)
        t.mkdir(parents=True)
        for f in FILES:
            (t / f).write_bytes((SRC / f).read_bytes())
        print(f"wrote {t.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
