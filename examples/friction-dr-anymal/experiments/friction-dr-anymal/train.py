#!/usr/bin/env python3
"""Train one arm x one seed of the friction demo (Isaac Lab + rsl_rl PPO).

  RAK_PREREG=friction-dr-anymal python train.py --arm treatment --seed 9101 --out runs/train/treatment-9101 --headless

Not executed yet (design stage). Everything that decides a number is in core.py and tested on CPU;
this file only wires it into Isaac Lab. There is no default for --arm or --seed: a missing condition raises.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

T_START = time.time()

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
import protocol as P  # noqa: E402


def parse(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=P.ARMS)
    ap.add_argument("--seed", required=True, type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--smoke", action="store_true", help="timing smoke: 50 iterations, seed must be SMOKE_SEED")
    return ap


def check_launch(arm: str, seed: int, smoke: bool, env=os.environ) -> int:
    """Return the iteration count, or raise if this is not a registered launch."""
    if env.get("RAK_PREREG") != P.PREREG_ID:
        raise core.ProtocolError(f"launch with RAK_PREREG={P.PREREG_ID} (got {env.get('RAK_PREREG')!r})")
    if smoke:
        if seed != P.SMOKE_SEED or arm != "control":
            raise core.ProtocolError(f"the timing smoke is control / seed {P.SMOKE_SEED}")
        return 50
    if seed not in P.TRAIN_SEEDS:
        raise core.ProtocolError(f"seed {seed} is not registered {P.TRAIN_SEEDS}")
    return P.TRAIN_ITERATIONS


def main(argv=None) -> int:
    from isaaclab.app import AppLauncher  # Isaac imports only here

    ap = parse(argv)
    AppLauncher.add_app_launcher_args(ap)
    args = ap.parse_args(argv)  # unknown flags raise
    iters = check_launch(args.arm, args.seed, args.smoke)
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise core.ProtocolError(f"{out} is not empty; one run per output directory")
    app = AppLauncher(args).app

    import gymnasium as gym
    import isaaclab_tasks  # noqa: F401  (registers tasks)
    from isaaclab.utils.io import dump_yaml
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from isaaclab_tasks.utils import parse_env_cfg
    from isaaclab_tasks.utils.parse_cfg import load_cfg_from_registry
    from rsl_rl.runners import OnPolicyRunner

    env_cfg = parse_env_cfg(P.TASK, device=args.device, num_envs=P.TRAIN_NUM_ENVS)
    agent_cfg = load_cfg_from_registry(P.TASK, "rsl_rl_cfg_entry_point")
    ev = env_cfg.events.physics_material
    ev.params = core.friction_event_params(args.arm, dict(ev.params))   # raises if the installed default differs
    env_cfg.seed = agent_cfg.seed = args.seed
    agent_cfg.max_iterations = iters

    out.mkdir(parents=True, exist_ok=True)
    dump_yaml(str(out / "env.yaml"), env_cfg)
    dump_yaml(str(out / "agent.yaml"), agent_cfg)
    core.write_once(out / "run.json", {
        "prereg": P.PREREG_ID, "arm": args.arm, "seed": args.seed, "iterations": iters, "smoke": args.smoke,
        "friction_event": {k: list(v) if isinstance(v, tuple) else v for k, v in ev.params.items()
                           if k != "asset_cfg"}, **core.provenance(),
    })

    env = RslRlVecEnvWrapper(gym.make(P.TASK, cfg=env_cfg))
    runner = OnPolicyRunner(env, agent_cfg.to_dict(), log_dir=str(out), device=agent_cfg.device)
    t_learn = time.time()
    runner.learn(num_learning_iterations=iters, init_at_random_ep_len=True)
    learn_s = time.time() - t_learn
    env.close()
    # success is decided by artifacts, not by the exit code (the app framework can swallow exceptions)
    final = sorted(out.glob("model_*.pt"), key=lambda p: int(p.stem.split("_")[1]))
    if not final or int(final[-1].stem.split("_")[1]) < iters - 1:
        raise core.ProtocolError(f"no final checkpoint in {out}")
    core.write_once(out / "timing.json", {"iterations": iters, "startup_seconds": t_learn - T_START, "learn_seconds": learn_s})
    (out / "DONE").write_text(final[-1].name + "\n", encoding="utf-8")
    app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
