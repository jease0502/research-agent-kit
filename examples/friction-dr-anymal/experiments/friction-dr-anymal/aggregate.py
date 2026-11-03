#!/usr/bin/env python3
"""Per-policy evaluation summaries -> gate_evidence.json and results.json with exactly the registered keys.

  python aggregate.py --evals runs/eval --gate-out gate_evidence.json --results-out results.json

Each summary (written by evaluate.py) says which policy (arm, seed, or zero-action), which friction
(mu, or null for the task default path), and the episode outcome. This script never invents a value:
a missing evaluation leaves its key out (the verdict then reads it as UNDETERMINED or a failed gate),
and a summary that is not from the registered protocol raises.
Values are raw floats; nothing is rounded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
import protocol as P  # noqa: E402

REQUIRED = {"policy", "mu", "n_episodes", "success_rate", "command_violations", "protocol_sha256"}


def load(eval_dir: Path) -> dict:
    """Index summaries by (policy, mu). policy is ("control"|"treatment", seed) or ("zero", None)."""
    proto = core.sha256_file(Path(__file__).resolve().parent / "protocol.py")
    out = {}
    for f in sorted(eval_dir.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        missing = REQUIRED - set(s)
        if missing:
            raise core.ProtocolError(f"{f.name}: missing fields {sorted(missing)}")
        if s["protocol_sha256"] != proto:
            raise core.ProtocolError(f"{f.name}: produced under a different protocol.py")
        if s["n_episodes"] != P.episodes_per_policy():
            raise core.ProtocolError(f"{f.name}: {s['n_episodes']} episodes, registered {P.episodes_per_policy()}")
        if s["command_violations"] != 0:
            raise core.ProtocolError(f"{f.name}: command lock violated")
        pol = s["policy"]
        key = ((pol["arm"], pol.get("seed")), s["mu"])
        if key in out:
            raise core.ProtocolError(f"duplicate evaluation {key} ({f.name})")
        if pol["arm"] != "zero" and pol.get("seed") not in P.TRAIN_SEEDS:
            raise core.ProtocolError(f"{f.name}: seed {pol.get('seed')} is not a registered training seed")
        out[key] = s
    return out


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def gate_evidence(ev: dict) -> tuple[dict, list[str]]:
    g, notes = {}, []
    overrides = [s for (pol, mu), s in ev.items() if mu is not None and "materials" in s]
    if overrides:
        g["g1_robot_static_friction_max_abs_dev"] = max(s["materials"]["robot_static_max_abs_dev"] for s in overrides)
        g["g1_robot_dynamic_friction_max_abs_dev"] = max(s["materials"]["robot_dynamic_max_abs_dev"] for s in overrides)
        g["g1_ground_static_friction"] = max((s["materials"]["ground_static"] for s in overrides),
                                             key=lambda v: abs(v - P.GROUND_FRICTION))
    else:
        notes.append("G1: no override evaluation with a material read-back")
    ctrl = [("control", s) for s in P.TRAIN_SEEDS]
    drops = [ev[(c, P.NOMINAL_MU)]["success_rate"] - ev[(c, P.GATE_ICE_MU)]["success_rate"]
             for c in ctrl if (c, P.NOMINAL_MU) in ev and (c, P.GATE_ICE_MU) in ev]
    if len(drops) == len(ctrl):
        g["g2_mean_success_drop_mu005_vs_mu08"] = _mean(drops)
    else:
        notes.append(f"G2: {len(drops)}/{len(ctrl)} control seeds have both mu=0.8 and mu=0.05")
    diffs = [abs(ev[(c, P.NOMINAL_MU)]["success_rate"] - ev[(c, None)]["success_rate"])
             for c in ctrl if (c, P.NOMINAL_MU) in ev and (c, None) in ev]
    if len(diffs) == len(ctrl):
        g["g3_mean_abs_success_diff_override_vs_none"] = _mean(diffs)
    else:
        notes.append(f"G3: {len(diffs)}/{len(ctrl)} control seeds have both override and default path at 0.8")
    nominal = [ev[(c, None)]["success_rate"] for c in ctrl if (c, None) in ev]
    if len(nominal) == len(ctrl):
        g["g4_control_mean_success_mu08"] = _mean(nominal)
    else:
        notes.append(f"G4: {len(nominal)}/{len(ctrl)} control seeds evaluated on the default path")
    if (("zero", None), None) in ev:
        g["g5_zero_action_success_mu08"] = ev[(("zero", None), None)]["success_rate"]
    else:
        notes.append("G5: zero-action evaluation missing")
    return g, notes


def results(ev: dict) -> dict:
    r = {}
    def per_seed(arm, mu):
        return {s: ev[((arm, s), mu)]["success_rate"] for s in P.TRAIN_SEEDS if ((arm, s), mu) in ev}
    c03, t03 = per_seed("control", 0.3), per_seed("treatment", 0.3)
    c08, t08 = per_seed("control", 0.8), per_seed("treatment", 0.8)
    if c03 and t03:
        r["c1_mean_success_diff_mu03"] = _mean(list(t03.values())) - _mean(list(c03.values()))
        r["c1_mean_success_diff_mu03__n"] = min(len(c03), len(t03))
    pairs = [s for s in P.TRAIN_SEEDS if s in c03 and s in t03]
    if pairs:
        r["c1b_seed_pairs_treatment_better_mu03"] = sum(t03[s] > c03[s] for s in pairs)
        r["c1b_seed_pairs_treatment_better_mu03__n"] = len(pairs)
    if c08 and t08:
        r["c2_mean_success_diff_mu08"] = _mean(list(t08.values())) - _mean(list(c08.values()))
        r["c2_mean_success_diff_mu08__n"] = min(len(c08), len(t08))
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evals", required=True)
    ap.add_argument("--gate-out", required=True)
    ap.add_argument("--results-out", required=True)
    a = ap.parse_args(argv)
    ev = load(Path(a.evals))
    g, notes = gate_evidence(ev)
    for n in notes:
        print("MISSING", n, file=sys.stderr)
    core.write_once(a.gate_out, g)
    core.write_once(a.results_out, results(ev))
    print(f"{len(ev)} evaluations -> {a.gate_out} ({len(g)} keys), {a.results_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
