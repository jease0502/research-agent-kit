"""Pure-Python logic of the friction demo: no Isaac, no torch, no numpy. Tested on CPU (tests/).

train.py and evaluate.py are thin Isaac adapters around this module. Anything that decides a number
(which friction an arm gets, which command an episode gets, whether an episode succeeded, whether the
material really changed) lives here so it can be tested with fakes that are able to fail.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import protocol as P


class ProtocolError(RuntimeError):
    """The run is not the registered run. Never caught: the job must stop."""


# ---------------------------------------------------------------- arms / friction

def friction_event_params(arm: str, current: dict) -> dict:
    """Return the physics_material event params for an arm, after checking the installed default.

    `current` is the event's params as installed. If it differs from the registered default, the task
    changed under us (or the prereg read the wrong version): raise instead of training something else.
    """
    if arm not in P.ARMS:
        raise ProtocolError(f"unknown arm {arm!r}; registered arms: {P.ARMS}")
    for k, v in P.DEFAULT_FRICTION_EVENT.items():
        got = current.get(k)
        got = tuple(got) if isinstance(got, (list, tuple)) else got
        if got != v:
            raise ProtocolError(f"installed task default {k}={got!r} differs from registered {v!r}; file an erratum before running")
    params = dict(current)
    if arm == "treatment":
        params.update(P.TREATMENT_FRICTION)
    return params


def eval_event_params(mu: float | None, current: dict) -> dict:
    """mu=None: the task default path (no override). Otherwise static=mu, dynamic=0.75*mu."""
    friction_event_params("control", current)  # same default check
    params = dict(current)
    if mu is not None:
        if not (0.0 < mu <= 2.0):
            raise ProtocolError(f"friction override {mu} outside (0, 2]")
        params.update(P.override_material(mu))
    return params


# ---------------------------------------------------------------- commands

def command_for(env_id: int, episode: int, seed: int = P.EVAL_SEED) -> tuple[float, float, float]:
    """Deterministic command per (env, episode): identical for every policy and arm."""
    rng = random.Random(f"{seed}:{env_id}:{episode}")  # str seeding is stable across runs and versions
    r = P.COMMAND_RANGES
    return (rng.uniform(*r["lin_vel_x"]), rng.uniform(*r["lin_vel_y"]), rng.uniform(*r["ang_vel_z"]))


class CommandChanged(ProtocolError):
    pass


class CommandLock:
    """Owns the velocity command during evaluation.

    install(): replaces the command term's resample with `resample`, which writes command_for(env, k)
    where k counts this env's resets after arm(). check(): called every step with the live command rows;
    raises CommandChanged if any env's command is not the locked one (heading control, standing envs,
    a resampling timer or anything else that rewrites the command makes this fail).
    """

    def __init__(self, num_envs: int, seed: int = P.EVAL_SEED, atol: float = P.COMMAND_ATOL):
        self.num_envs, self.seed, self.atol = num_envs, seed, atol
        self.armed = False
        self.episode = [0] * num_envs

    def arm(self) -> None:
        self.armed = True

    def resample(self, env_ids) -> dict[int, tuple[float, float, float]]:
        out = {}
        for i in env_ids:
            i = int(i)
            if self.armed:
                self.episode[i] += 1
            out[i] = command_for(i, self.episode[i] if self.armed else 0, self.seed)
        return out

    def expected(self, env_id: int) -> tuple[float, float, float]:
        return command_for(env_id, self.episode[env_id], self.seed)

    def check(self, rows, active=None) -> None:
        if len(rows) != self.num_envs:
            raise CommandChanged(f"expected {self.num_envs} command rows, got {len(rows)}")
        for i, row in enumerate(rows):
            if active is not None and not active[i]:
                continue
            exp = self.expected(i)
            if any(abs(float(a) - b) > self.atol for a, b in zip(row, exp)):
                raise CommandChanged(f"env {i} episode {self.episode[i]}: command {list(row)} != locked {list(exp)}")


# ---------------------------------------------------------------- episodes

@dataclass
class Episode:
    env: int
    episode: int
    steps: int
    mean_track_err: float
    fell: bool
    timed_out: bool
    success: bool


@dataclass
class EpisodeTracker:
    """Per-env episode bookkeeping. Success is decided at episode end, from these fields only.

    update() takes, per env, the planar tracking error of this step, whether the env finished an episode
    this step, and whether that finish was a time-out. The step on which an env is reset is not added to
    either episode: after an automatic reset the state read back belongs to the new episode.
    """
    num_envs: int
    episodes_per_env: int = P.EVAL_EPISODES_PER_ENV
    max_err: float = P.MAX_MEAN_TRACK_ERR
    episodes: list[Episode] = field(default_factory=list)

    def __post_init__(self):
        self.completed = [0] * self.num_envs
        self._sum = [0.0] * self.num_envs
        self._n = [0] * self.num_envs

    def active(self) -> list[bool]:
        return [c < self.episodes_per_env for c in self.completed]

    def update(self, errs, dones, time_outs) -> list[int]:
        """Returns the env ids that finished an episode this step."""
        if not (len(errs) == len(dones) == len(time_outs) == self.num_envs):
            raise ProtocolError("step arrays have the wrong length")
        finished = []
        for i in range(self.num_envs):
            if self.completed[i] >= self.episodes_per_env:
                continue
            if dones[i]:
                n = self._n[i]
                mean = self._sum[i] / n if n else float("inf")
                fell = not bool(time_outs[i])
                ok = bool(time_outs[i]) and not fell and mean <= self.max_err   # raw value, no rounding
                self.episodes.append(Episode(i, self.completed[i], n, mean, fell, bool(time_outs[i]), ok))
                self.completed[i] += 1
                self._sum[i], self._n[i] = 0.0, 0
                finished.append(i)
            else:
                self._sum[i] += float(errs[i])
                self._n[i] += 1
        return finished

    def done(self) -> bool:
        return all(c >= self.episodes_per_env for c in self.completed)

    def summary(self) -> dict:
        n = len(self.episodes)
        if n != self.num_envs * self.episodes_per_env:
            raise ProtocolError(f"{n} episodes recorded, expected {self.num_envs * self.episodes_per_env}")
        return {
            "n_episodes": n,
            "success_rate": sum(e.success for e in self.episodes) / n,
            "fall_rate": sum(e.fell for e in self.episodes) / n,
            "mean_track_err": sum(e.mean_track_err for e in self.episodes) / n,
        }


def check_episode_alignment(lock: CommandLock, tracker: EpisodeTracker) -> None:
    """The command lock counts resets, the tracker counts finished episodes; for active envs they must agree.
    If they drift, envs are being reset by something other than episode ends (or the reverse), and every
    command after that point is attached to the wrong episode."""
    for i, act in enumerate(tracker.active()):
        if act and lock.episode[i] != tracker.completed[i]:
            raise ProtocolError(f"env {i}: command lock at episode {lock.episode[i]}, tracker at {tracker.completed[i]}")


# ---------------------------------------------------------------- materials (gate G1)

def check_materials(robot_rows, mu: float | None, ground: dict) -> dict:
    """robot_rows: per env, per collision shape, (static, dynamic, restitution) read back from the engine.
    ground: {"static": s, "dynamic": d, "combine_mode": m} read from the ground's physics material.

    Returns the deviations; the gate decides pass/fail from them. Raises if there is nothing to check
    (an empty read-back must not look like a perfect match).
    """
    exp_s = mu if mu is not None else P.DEFAULT_FRICTION_EVENT["static_friction_range"][0]
    exp_d = P.DYNAMIC_TO_STATIC * mu if mu is not None else P.DEFAULT_FRICTION_EVENT["dynamic_friction_range"][0]
    dev_s = dev_d = 0.0
    n_shapes = 0
    for env in robot_rows:
        for shape in env:
            s, d = float(shape[0]), float(shape[1])
            dev_s, dev_d = max(dev_s, abs(s - exp_s)), max(dev_d, abs(d - exp_d))
            n_shapes += 1
    if n_shapes == 0:
        raise ProtocolError("material read-back returned no shapes")
    if ground.get("combine_mode") != P.GROUND_COMBINE_MODE:
        raise ProtocolError(f"ground friction combine mode {ground.get('combine_mode')!r}, registered {P.GROUND_COMBINE_MODE!r}")
    return {
        "expected_static": exp_s, "expected_dynamic": exp_d, "n_shapes": n_shapes,
        "robot_static_max_abs_dev": dev_s, "robot_dynamic_max_abs_dev": dev_d,
        "ground_static": float(ground["static"]), "ground_dynamic": float(ground["dynamic"]),
    }


def preflight_problems(materials: dict) -> list[str]:
    """Gate G1's thresholds applied before any training money is spent (same numbers as the verdict's G1)."""
    p = []
    if materials["robot_static_max_abs_dev"] > P.MATERIAL_ATOL:
        p.append(f"robot static friction off by {materials['robot_static_max_abs_dev']!r}")
    if materials["robot_dynamic_max_abs_dev"] > P.MATERIAL_ATOL:
        p.append(f"robot dynamic friction off by {materials['robot_dynamic_max_abs_dev']!r}")
    if abs(materials["ground_static"] - P.GROUND_FRICTION) > P.MATERIAL_ATOL:
        p.append(f"ground static friction {materials['ground_static']!r}, registered {P.GROUND_FRICTION}")
    return p


# ---------------------------------------------------------------- budget after the timing smoke

def projected_hours(setup_h: float, smoke_seconds: float, smoke_startup_s: float) -> dict:
    """Whole-run L4-hours projected from the timing smoke (prereg §6). smoke_seconds is the wall time of the
    smoke's learn() call for SMOKE_ITERATIONS; smoke_startup_s the process time before learn()."""
    if smoke_seconds <= 0 or smoke_startup_s < 0:
        raise ProtocolError("timing smoke produced no usable timing")
    per_iter = smoke_seconds / P.SMOKE_ITERATIONS
    train_h = len(P.TRAIN_SEEDS) * len(P.ARMS) * (smoke_startup_s + per_iter * P.TRAIN_ITERATIONS) / 3600
    eval_h = P.N_EVAL_PROCESSES * P.EVAL_PROCESS_HOURS_EST
    total = setup_h + train_h + eval_h + P.SLACK_HOURS
    return {"s_per_iteration": per_iter, "train_h": train_h, "eval_h": eval_h, "setup_h": setup_h,
            "total_h": total, "stop_h": P.BUDGET_STOP_L4_HOURS, "over": total > P.BUDGET_STOP_L4_HOURS}


# ---------------------------------------------------------------- provenance

def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def provenance() -> dict:
    here = Path(__file__).resolve().parent
    return {"protocol_sha256": sha256_file(here / "protocol.py"), "core_sha256": sha256_file(here / "core.py")}


def write_once(path: str | Path, obj: dict) -> None:
    p = Path(path)
    if p.exists():
        raise ProtocolError(f"{p} exists; outputs are written once")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")
