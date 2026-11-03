#!/usr/bin/env python3
"""Evaluate one policy at one friction condition (one Isaac process per condition).

  RAK_PREREG=friction-dr-anymal python evaluate.py --policy runs/train/control-9101 --mu 0.3 --out runs/eval --headless
  ... --policy runs/train/control-9101 --default-path    # task default friction, no override (G3, G4)
  ... --zero-action --default-path                        # do-nothing baseline (G5)

Not executed yet (design stage). The decisions live in core.py (tested on CPU):
  * friction override: static = mu, dynamic = 0.75 mu, through the task's own material event;
  * materials are read back from the physics engine after start-up (gate G1), robot and ground;
  * the command is locked: resampling timer off, heading control off, standing envs off, the command
    term's resample replaced by CommandLock.resample, and CommandLock.check() every step;
  * success is binary at episode end (core.EpisodeTracker): timed out, not fallen, mean planar error <= 0.25 m/s.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402
import protocol as P  # noqa: E402


def parse(argv=None):
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--policy", help="training run directory (with run.json and DONE)")
    src.add_argument("--zero-action", action="store_true")
    src.add_argument("--materials-only", action="store_true",
                     help="preflight: build the env, read the materials back, apply G1's thresholds, exit (no policy)")
    fr = ap.add_mutually_exclusive_group(required=True)
    fr.add_argument("--mu", type=float)
    fr.add_argument("--default-path", action="store_true")
    ap.add_argument("--out", required=True)
    return ap


def policy_identity(policy_dir: str | None) -> dict:
    if policy_dir is None:
        return {"arm": "zero", "seed": None}
    import json
    run = json.loads((Path(policy_dir) / "run.json").read_text(encoding="utf-8"))
    if run.get("smoke"):
        raise core.ProtocolError("the timing-smoke policy is not evaluated")
    if not (Path(policy_dir) / "DONE").is_file():
        raise core.ProtocolError(f"{policy_dir} has no DONE marker; training did not finish")
    return {"arm": run["arm"], "seed": run["seed"]}


def output_name(pol: dict, mu: float | None) -> str:
    who = "zero" if pol["arm"] == "zero" else f"{pol['arm']}-{pol['seed']}"
    return f"{who}__{'default' if mu is None else f'mu{mu:g}'}.json"


def apply_eval_settings(env_cfg, mu):
    """Command lock settings + material override. Raises if a setting it relies on is not there."""
    cmd = env_cfg.commands.base_velocity
    for name in ("resampling_time_range", "heading_command", "rel_heading_envs", "rel_standing_envs", "ranges"):
        if not hasattr(cmd, name):
            raise core.ProtocolError(f"command cfg has no {name}; the installed task differs from the registered one")
    cmd.resampling_time_range = (1.0e9, 1.0e9)
    cmd.heading_command = False
    cmd.rel_heading_envs = 0.0
    cmd.rel_standing_envs = 0.0
    for k, (lo, hi) in P.COMMAND_RANGES.items():
        if tuple(getattr(cmd.ranges, k)) != (lo, hi):
            raise core.ProtocolError(f"command range {k}={getattr(cmd.ranges, k)} differs from registered {(lo, hi)}")
    env_cfg.events.push_robot = None
    env_cfg.events.base_external_force_torque = None
    env_cfg.observations.policy.enable_corruption = False
    env_cfg.episode_length_s = P.EVAL_EPISODE_S
    ev = env_cfg.events.physics_material
    ev.params = core.eval_event_params(mu, dict(ev.params))


def read_ground_material(stage) -> dict:
    """Find the physics material bound under the ground prim and read friction + combine mode."""
    from pxr import UsdPhysics
    found = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not path.startswith("/World/ground") or not prim.HasAPI(UsdPhysics.MaterialAPI):
            continue
        m = UsdPhysics.MaterialAPI(prim)
        mode = prim.GetAttribute("physxMaterial:frictionCombineMode")
        found.append({"path": path, "static": m.GetStaticFrictionAttr().Get(),
                      "dynamic": m.GetDynamicFrictionAttr().Get(), "combine_mode": mode.Get() if mode else None})
    if len(found) != 1:
        raise core.ProtocolError(f"expected one ground physics material, found {len(found)}: {[f['path'] for f in found]}")
    return found[0]


def main(argv=None) -> int:
    from isaaclab.app import AppLauncher

    ap = parse(argv)
    AppLauncher.add_app_launcher_args(ap)
    args = ap.parse_args(argv)
    if os.environ.get("RAK_PREREG") != P.PREREG_ID:
        raise core.ProtocolError(f"launch with RAK_PREREG={P.PREREG_ID}")
    mu = None if args.default_path else args.mu
    if args.materials_only and mu is None:
        raise core.ProtocolError("--materials-only needs --mu (it checks the override path)")
    pol = {"arm": "preflight", "seed": None} if args.materials_only else policy_identity(args.policy)
    out_json = Path(args.out) / output_name(pol, mu)
    if out_json.exists():
        raise core.ProtocolError(f"{out_json} exists; evaluations are written once")
    app = AppLauncher(args).app

    import gymnasium as gym
    import torch
    import isaaclab_tasks  # noqa: F401
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from isaaclab_tasks.utils import parse_env_cfg
    from isaaclab_tasks.utils.parse_cfg import load_cfg_from_registry
    from rsl_rl.runners import OnPolicyRunner

    env_cfg = parse_env_cfg(P.TASK, device=args.device, num_envs=P.EVAL_NUM_ENVS)
    env_cfg.seed = P.EVAL_SEED
    apply_eval_settings(env_cfg, mu)
    env = RslRlVecEnvWrapper(gym.make(P.TASK, cfg=env_cfg))
    base = env.unwrapped
    robot = base.scene["robot"]

    # --- command lock: own the resample, then check every step
    lock = core.CommandLock(P.EVAL_NUM_ENVS)
    term = base.command_manager.get_term("base_velocity")

    def _resample(env_ids):
        for i, c in lock.resample(env_ids.tolist() if hasattr(env_ids, "tolist") else env_ids).items():
            term.vel_command_b[i] = torch.tensor(c, device=term.vel_command_b.device)
            term.is_heading_env[i] = False
            term.is_standing_env[i] = False
    term._resample_command = _resample

    if pol["arm"] == "zero":
        policy = lambda obs: torch.zeros(base.num_envs, base.action_manager.total_action_dim, device=base.device)  # noqa: E731
    else:
        agent_cfg = load_cfg_from_registry(P.TASK, "rsl_rl_cfg_entry_point")
        runner = OnPolicyRunner(env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device)
        ckpt = Path(args.policy) / (Path(args.policy) / "DONE").read_text(encoding="utf-8").strip()
        runner.load(str(ckpt))
        policy = runner.get_inference_policy(device=base.device)

    env.reset()          # resets every env through our _resample (episode 0 for all)
    lock.arm()
    # --- gate G1: what the engine actually uses
    props = robot.root_physx_view.get_material_properties().tolist()
    materials = core.check_materials(props, mu, read_ground_material(base.sim.stage))
    if args.materials_only:   # preflight: G1 before any training money is spent
        problems = core.preflight_problems(materials)
        core.write_once(Path(args.out) / f"materials_mu{mu:g}.json",
                        {"mu": mu, "materials": materials, "problems": problems, **core.provenance()})
        env.close(); app.close()
        return 1 if problems else 0

    tracker = core.EpisodeTracker(P.EVAL_NUM_ENVS)
    obs = env.get_observations()
    obs = obs[0] if isinstance(obs, tuple) else obs
    max_steps = int(P.EVAL_EPISODES_PER_ENV * P.EVAL_EPISODE_S / base.step_dt) + 10
    with torch.inference_mode():
        for _ in range(max_steps):
            lock.check(term.vel_command_b.tolist(), tracker.active())   # before acting: the command the policy sees
            obs, _, dones, extras = env.step(policy(obs))
            err = torch.linalg.norm(term.vel_command_b[:, :2] - robot.data.root_lin_vel_b[:, :2], dim=-1)
            tracker.update(err.tolist(), dones.bool().tolist(), extras["time_outs"].bool().tolist())
            core.check_episode_alignment(lock, tracker)
            if tracker.done():
                break
    if not tracker.done():
        raise core.ProtocolError(f"step budget {max_steps} ran out before every env finished {P.EVAL_EPISODES_PER_ENV} episodes")
    summary = {"policy": pol, "mu": mu, **tracker.summary(), "command_violations": 0,
               "materials": materials, "eval_seed": P.EVAL_SEED, **core.provenance()}
    core.write_once(out_json, summary)
    with open(out_json.with_suffix(".episodes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["env", "episode", "steps", "mean_track_err", "fell", "timed_out", "success"])
        for e in tracker.episodes:
            w.writerow([e.env, e.episode, e.steps, repr(e.mean_track_err), e.fell, e.timed_out, e.success])
    env.close()
    app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
