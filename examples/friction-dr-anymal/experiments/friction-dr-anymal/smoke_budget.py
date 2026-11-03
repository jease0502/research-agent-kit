#!/usr/bin/env python3
"""Prereg §6 stop rule: project the whole run from the timing smoke; exit 1 if it crosses the stop line.

  python smoke_budget.py --smoke runs/train/control-9100 --setup-hours 0.4 --out budget.json

No Isaac needed. The VM job stops before any main training when this fails; the measurement goes into an
erratum to prereg §6 either way.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
import protocol as P  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", required=True)
    ap.add_argument("--setup-hours", required=True, type=float)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t = json.loads((Path(a.smoke) / "timing.json").read_text(encoding="utf-8"))
    if t.get("iterations") != P.SMOKE_ITERATIONS:
        raise core.ProtocolError(f"smoke ran {t.get('iterations')} iterations, registered {P.SMOKE_ITERATIONS}")
    proj = core.projected_hours(a.setup_hours, t["learn_seconds"], t["startup_seconds"])
    core.write_once(a.out, {**proj, "smoke": t, **core.provenance()})
    print(f"projected {proj['total_h']:.2f} L4-h (stop line {proj['stop_h']}): {'OVER - stop and re-plan' if proj['over'] else 'ok'}")
    return 1 if proj["over"] else 0


if __name__ == "__main__":
    sys.exit(main())
