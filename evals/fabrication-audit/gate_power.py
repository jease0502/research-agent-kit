#!/usr/bin/env python3
"""How well the positive-control gates tell a working scorer from a loosened one (prereg §3).

    python gate_power.py 0 40                      # seeds 0-39: what the thresholds were chosen from
    python gate_power.py 1000 1100 --check         # unseen seeds: pass counts at the registered thresholds

For each seed, controls.evidence() is computed with the real scorer, with a scorer whose tolerance is 3x and 10x
too wide for every format, and with one 10x too wide for a single format only. The single-format version widens
the tolerance inside `matches` and leaves the printed precision alone, so the "not scorable" class does not
change (lowering the parsed decimals instead would move plants out of the denominator and hide the effect).
CPU only; about a minute per 40 seeds.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import controls as C  # noqa: E402
import score as S  # noqa: E402
import verdict as V  # noqa: E402

REAL_PARSE, REAL_MATCHES = S.parse_number, S.matches


class Tok(float):
    """A parsed value that remembers its token, so a loosened `matches` can act on one format only."""
    tok = ""


def tagging_parse(tok):
    value, dec, pct = REAL_PARSE(tok)
    v = Tok(value)
    v.tok = tok
    return v, dec, pct


def wider(k):
    def m(v, dec, pct, pool):
        tol = k * 0.5 * 10 ** (-dec) + 1e-12
        cands = [(abs(v), tol)] + ([(abs(v) / 100, tol / 100)] if pct else [])
        return any(abs(c - p) <= t for c, t in cands for p in pool)
    return m


def wider_for(fmt, k=10):
    def m(v, dec, pct, pool):
        if C.token_format(getattr(v, "tok", "")) != fmt:
            return REAL_MATCHES(v, dec, pct, pool)
        return wider(k)(float(v), dec, pct, pool)
    return m


def run(label, keys, seeds, thresholds):
    rates = {k: [] for k in keys}
    for sd in seeds:
        C.SEED = sd
        ev = C.evidence()
        for k in keys:
            rates[k].append(ev[k])
    for k, xs in rates.items():
        xs = sorted(x for x in xs if x is not None)
        line = f"{label:20s} {k:32s} min {xs[0]:.3f} median {statistics.median(xs):.3f} max {xs[-1]:.3f}"
        if k in thresholds:
            line += f"  passes {sum(x >= thresholds[k] for x in xs)}/{len(xs)} at {thresholds[k]}"
        print(line, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("seed_from", type=int)
    ap.add_argument("seed_to", type=int)
    ap.add_argument("--check", action="store_true", help="print pass counts at the thresholds in verdict.GATES")
    ap.add_argument("--single-k", type=int, nargs="+", default=[10],
                    help="how many times too loose the single-format scorers are (default 10)")
    a = ap.parse_args(argv)
    seeds = range(a.seed_from, a.seed_to)
    thr = {key: lo for key, lo, _ in V.GATES.values() if key.startswith("pos_ctrl")} if a.check else {}
    gated = ["pos_ctrl_planted_flag_rate"] + [f"pos_ctrl_flag_rate_{f}" for f in C.FORMATS]
    run("real", gated + [f"realistic_flag_rate_{f}" for f in C.FORMATS] + ["near_miss_1_2_flag_rate"], seeds, thr)
    for k in (3, 10):
        S.matches = wider(k)
        run(f"{k}x all formats", gated, seeds, thr)
        S.matches = REAL_MATCHES
    for k in a.single_k:
        for f in C.FORMATS:
            S.parse_number, S.matches = tagging_parse, wider_for(f, k)
            run(f"{k}x {f} only", [f"pos_ctrl_flag_rate_{f}", "pos_ctrl_planted_flag_rate"], seeds, thr)
            S.parse_number, S.matches = REAL_PARSE, REAL_MATCHES
    return 0


if __name__ == "__main__":
    sys.exit(main())
