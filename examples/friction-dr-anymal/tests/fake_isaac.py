#!/usr/bin/env python3
"""Stands in for `<venv>/bin/python` on the VM in the cloud flow test: `fake_isaac.py <script> args...`.

train.py / evaluate.py are emulated (no Isaac), but through the example's real code: launch checks, policy
identity, output names, material checks and write-once outputs come from core.py / train.py / evaluate.py.
The "world" (success rates, material read-back error, smoke timing) comes from $FAKE_WORLD (json).
"""
import json
import os
import sys
from pathlib import Path

script = Path(sys.argv[1])
args = [a for a in sys.argv[2:] if a != "--headless"]   # AppLauncher's flag; the real scripts accept it
sys.path.insert(0, str(script.resolve().parent))
import core  # noqa: E402
import protocol as P  # noqa: E402

W = {"preflight_dev": 0.0, "smoke_learn_s": 60.0, "smoke_startup_s": 90.0, "material_dev": 0.0,
     "ctrl03": 0.40, "treat03": 0.70, "ctrl08": 0.92, "treat08": 0.90, "ice": 0.10, "default": 0.93, "zero": 0.0}
W.update(json.loads(os.environ.get("FAKE_WORLD", "{}")))


def materials(mu):
    rows = [[[(mu if mu is not None else 0.8) + W["material_dev"], (P.DYNAMIC_TO_STATIC * mu if mu is not None else 0.6) + W["material_dev"], 0.0]] * 4] * 3
    return core.check_materials(rows, mu, {"static": 1.0, "dynamic": 1.0, "combine_mode": "multiply"})


if script.name == "train.py":
    import train
    a = train.parse().parse_args(args)
    iters = train.check_launch(a.arm, a.seed, a.smoke)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    params = core.friction_event_params(a.arm, dict(P.DEFAULT_FRICTION_EVENT))
    core.write_once(out / "run.json", {"prereg": P.PREREG_ID, "arm": a.arm, "seed": a.seed, "iterations": iters, "smoke": a.smoke,
                                       "friction_event": {k: list(v) if isinstance(v, tuple) else v for k, v in params.items()},
                                       **core.provenance()})
    (out / f"model_{iters - 1}.pt").write_bytes(b"fake weights " + a.arm.encode())
    learn = W["smoke_learn_s"] * iters / P.SMOKE_ITERATIONS
    core.write_once(out / "timing.json", {"iterations": iters, "startup_seconds": W["smoke_startup_s"], "learn_seconds": learn})
    (out / "DONE").write_text(f"model_{iters - 1}.pt\n")
    sys.exit(0)

if script.name == "evaluate.py":
    import evaluate
    a = evaluate.parse().parse_args(args)
    if os.environ.get("RAK_PREREG") != P.PREREG_ID:
        raise core.ProtocolError("RAK_PREREG missing")
    mu = None if a.default_path else a.mu
    if a.materials_only:
        m = materials(mu)
        m["robot_static_max_abs_dev"] += W["preflight_dev"]
        probs = core.preflight_problems(m)
        core.write_once(Path(a.out) / f"materials_mu{mu:g}.json", {"mu": mu, "materials": m, "problems": probs, **core.provenance()})
        sys.exit(1 if probs else 0)
    pol = evaluate.policy_identity(a.policy)
    if pol["arm"] == "zero":
        sr = W["zero"]
    elif mu is None:
        sr = W["default"]
    elif mu == P.GATE_ICE_MU:
        sr = W["ice"]
    else:
        sr = W[("ctrl" if pol["arm"] == "control" else "treat") + ("03" if mu == 0.3 else "08")]
    core.write_once(Path(a.out) / evaluate.output_name(pol, mu), {
        "policy": pol, "mu": mu, "n_episodes": P.episodes_per_policy(), "success_rate": sr, "fall_rate": 0.0,
        "mean_track_err": 0.1, "command_violations": 0, "materials": materials(mu), "eval_seed": P.EVAL_SEED, **core.provenance()})
    sys.exit(0)

sys.exit(f"fake_isaac: unexpected script {script}")
