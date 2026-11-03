"""CPU tests for the friction demo's decision logic (no Isaac). Run from the example folder:
    python -m pytest -q tests
Every check has a case it must reject; a check that cannot fail is not a check.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

EXP = Path(__file__).resolve().parent.parent / "experiments" / "friction-dr-anymal"
sys.path.insert(0, str(EXP))
import core  # noqa: E402
import evaluate  # noqa: E402  (module import must not need Isaac)
import protocol as P  # noqa: E402
import train  # noqa: E402

DEFAULT = {"asset_cfg": object(), "static_friction_range": (0.8, 0.8), "dynamic_friction_range": (0.6, 0.6),
           "restitution_range": (0.0, 0.0), "num_buckets": 64}


class FrictionParams(unittest.TestCase):
    def test_control_keeps_default(self):
        p = core.friction_event_params("control", dict(DEFAULT))
        self.assertEqual(p["static_friction_range"], (0.8, 0.8))
        self.assertNotIn("make_consistent", p)

    def test_treatment_range(self):
        p = core.friction_event_params("treatment", dict(DEFAULT))
        self.assertEqual(p["static_friction_range"], (0.25, 1.2))
        self.assertTrue(p["make_consistent"])

    def test_changed_installed_default_raises(self):
        changed = dict(DEFAULT, static_friction_range=(1.0, 1.0))
        with self.assertRaises(core.ProtocolError):
            core.friction_event_params("control", changed)

    def test_list_valued_default_accepted(self):  # configs loaded from yaml give lists
        core.friction_event_params("control", dict(DEFAULT, static_friction_range=[0.8, 0.8]))

    def test_unknown_arm_raises(self):
        with self.assertRaises(core.ProtocolError):
            core.friction_event_params("treatment2", dict(DEFAULT))

    def test_eval_override(self):
        p = core.eval_event_params(0.3, dict(DEFAULT))
        self.assertEqual(p["static_friction_range"], (0.3, 0.3))
        self.assertAlmostEqual(p["dynamic_friction_range"][0], 0.225, places=12)
        self.assertEqual(core.eval_event_params(None, dict(DEFAULT))["static_friction_range"], (0.8, 0.8))
        with self.assertRaises(core.ProtocolError):
            core.eval_event_params(0.0, dict(DEFAULT))


class FakeTerm:
    """Stands in for the velocity command term: a resample hook, a per-step update that may rewrite commands."""
    def __init__(self, n, lock, heading=False, standing=False):
        self.n, self.lock, self.heading, self.standing = n, lock, heading, standing
        self.cmd = [[0.0, 0.0, 0.0] for _ in range(n)]

    def reset(self, ids):
        for i, c in self.lock.resample(ids).items():
            self.cmd[i] = [float(x) for x in c]

    def update(self):  # what Isaac Lab's _update_command does when heading / standing are on
        for i in range(self.n):
            if self.heading:
                self.cmd[i][2] = 0.5 * self.cmd[i][2]
            if self.standing and i % 7 == 0:
                self.cmd[i] = [0.0, 0.0, 0.0]


class CommandLockTests(unittest.TestCase):
    def test_deterministic_and_policy_independent(self):
        self.assertEqual(core.command_for(3, 1), core.command_for(3, 1))
        self.assertNotEqual(core.command_for(3, 0), core.command_for(3, 1))
        for v, (lo, hi) in zip(core.command_for(5, 0), P.COMMAND_RANGES.values()):
            self.assertTrue(lo <= v <= hi)

    def test_locked_commands_pass(self):
        lock = core.CommandLock(8); t = FakeTerm(8, lock)
        t.reset(range(8)); lock.arm()
        for _ in range(5):
            t.update(); lock.check(t.cmd)
        t.reset([2]); t.update(); lock.check(t.cmd)
        self.assertEqual(lock.episode[2], 1)

    def test_heading_control_is_caught(self):
        lock = core.CommandLock(8); t = FakeTerm(8, lock, heading=True)
        t.reset(range(8)); lock.arm(); t.update()
        with self.assertRaises(core.CommandChanged):
            lock.check(t.cmd)

    def test_standing_envs_are_caught(self):
        lock = core.CommandLock(8); t = FakeTerm(8, lock, standing=True)
        t.reset(range(8)); lock.arm(); t.update()
        with self.assertRaises(core.CommandChanged):
            lock.check(t.cmd)

    def test_untracked_resample_is_caught(self):
        lock = core.CommandLock(4); t = FakeTerm(4, lock)
        t.reset(range(4)); lock.arm()
        t.cmd[1] = [0.1, 0.2, 0.3]   # something resampled outside the lock
        with self.assertRaises(core.CommandChanged):
            lock.check(t.cmd)

    def test_float32_storage_tolerated(self):
        import struct
        lock = core.CommandLock(2); t = FakeTerm(2, lock)
        t.reset(range(2)); lock.arm()
        t.cmd = [[struct.unpack("f", struct.pack("f", x))[0] for x in row] for row in t.cmd]
        lock.check(t.cmd)

    def test_inactive_envs_skipped(self):
        lock = core.CommandLock(2); t = FakeTerm(2, lock)
        t.reset(range(2)); lock.arm(); t.cmd[0] = [9, 9, 9]
        lock.check(t.cmd, active=[False, True])


class TrackerTests(unittest.TestCase):
    def run_episode(self, tr, env, errs, end_timeout):
        n = tr.num_envs
        for e in errs:
            tr.update([e if i == env else 0.0 for i in range(n)], [False] * n, [False] * n)
        tr.update([99.0 if i == env else 0.0 for i in range(n)], [i == env for i in range(n)], [end_timeout if i == env else False for i in range(n)])

    def test_success_needs_timeout_and_low_error(self):
        tr = core.EpisodeTracker(1, episodes_per_env=3)
        self.run_episode(tr, 0, [0.1, 0.2, 0.3], True)       # mean 0.2, timed out -> success
        self.run_episode(tr, 0, [0.1, 0.1], False)           # fell -> fail
        self.run_episode(tr, 0, [0.3, 0.3], True)            # mean 0.3 > 0.25 -> fail
        self.assertEqual([e.success for e in tr.episodes], [True, False, False])
        self.assertEqual([e.fell for e in tr.episodes], [False, True, False])
        self.assertAlmostEqual(tr.episodes[0].mean_track_err, 0.2, places=12)  # reset-step error (99) excluded

    def test_threshold_not_rounded(self):
        tr = core.EpisodeTracker(1, episodes_per_env=1)
        self.run_episode(tr, 0, [0.2500001], True)
        self.assertFalse(tr.episodes[0].success)

    def test_summary_requires_every_episode(self):
        tr = core.EpisodeTracker(2, episodes_per_env=1)
        self.run_episode(tr, 0, [0.1], True)
        with self.assertRaises(core.ProtocolError):
            tr.summary()
        self.run_episode(tr, 1, [0.1], True)
        self.assertEqual(tr.summary()["success_rate"], 1.0)

    def test_extra_episodes_ignored(self):
        tr = core.EpisodeTracker(1, episodes_per_env=1)
        self.run_episode(tr, 0, [0.1], True)
        self.run_episode(tr, 0, [5.0], False)
        self.assertEqual(len(tr.episodes), 1)

    def test_alignment_check(self):
        lock = core.CommandLock(2); tr = core.EpisodeTracker(2)
        lock.arm(); core.check_episode_alignment(lock, tr)
        lock.resample([1])          # a reset the tracker never saw end
        with self.assertRaises(core.ProtocolError):
            core.check_episode_alignment(lock, tr)


class MaterialTests(unittest.TestCase):
    GROUND = {"static": 1.0, "dynamic": 1.0, "combine_mode": "multiply"}

    def rows(self, s, d, envs=3, shapes=4):
        return [[[s, d, 0.0] for _ in range(shapes)] for _ in range(envs)]

    def test_applied_override_passes(self):
        m = core.check_materials(self.rows(0.3, 0.225), 0.3, self.GROUND)
        self.assertLessEqual(m["robot_static_max_abs_dev"], 1e-9)
        self.assertEqual(m["n_shapes"], 12)

    def test_override_not_applied_is_visible(self):   # e.g. instanced prims keep the default material
        rows = self.rows(0.3, 0.225); rows[1][2] = [0.8, 0.6, 0.0]
        m = core.check_materials(rows, 0.3, self.GROUND)
        self.assertGreater(m["robot_static_max_abs_dev"], 0.4)
        self.assertGreater(m["robot_dynamic_max_abs_dev"], 0.3)

    def test_default_path_expects_default(self):
        m = core.check_materials(self.rows(0.8, 0.6), None, self.GROUND)
        self.assertLessEqual(m["robot_static_max_abs_dev"], 1e-9)

    def test_empty_readback_raises(self):
        with self.assertRaises(core.ProtocolError):
            core.check_materials([], 0.3, self.GROUND)

    def test_wrong_combine_mode_raises(self):
        with self.assertRaises(core.ProtocolError):
            core.check_materials(self.rows(0.3, 0.225), 0.3, dict(self.GROUND, combine_mode="average"))


class LaunchAndSettings(unittest.TestCase):
    def test_train_launch_checks(self):
        env = {"RAK_PREREG": P.PREREG_ID}
        self.assertEqual(train.check_launch("control", 9101, False, env), 300)
        self.assertEqual(train.check_launch("control", P.SMOKE_SEED, True, env), 50)
        for args in [("control", 9101, False, {}), ("control", 1, False, env), ("treatment", P.SMOKE_SEED, True, env)]:
            with self.assertRaises(core.ProtocolError):
                train.check_launch(*args)

    def test_train_has_no_default_arm_or_seed(self):
        with self.assertRaises(SystemExit):
            train.parse().parse_args(["--seed", "9101", "--out", "x"])
        with self.assertRaises(SystemExit):
            train.parse().parse_args(["--arm", "control", "--seed", "9101", "--out", "x", "--bogus"])

    def fake_cfg(self, **cmd_over):
        cmd = SimpleNamespace(resampling_time_range=(10.0, 10.0), heading_command=True, rel_heading_envs=1.0,
                              rel_standing_envs=0.02, ranges=SimpleNamespace(lin_vel_x=(-1.0, 1.0), lin_vel_y=(-1.0, 1.0),
                                                                             ang_vel_z=(-1.0, 1.0)))
        for k, v in cmd_over.items():
            setattr(cmd, k, v)
        return SimpleNamespace(commands=SimpleNamespace(base_velocity=cmd),
                               events=SimpleNamespace(push_robot=1, base_external_force_torque=1,
                                                      physics_material=SimpleNamespace(params=dict(DEFAULT))),
                               observations=SimpleNamespace(policy=SimpleNamespace(enable_corruption=True)),
                               episode_length_s=20.0)

    def test_eval_settings_lock_commands(self):
        c = self.fake_cfg()
        evaluate.apply_eval_settings(c, 0.3)
        b = c.commands.base_velocity
        self.assertEqual((b.heading_command, b.rel_heading_envs, b.rel_standing_envs), (False, 0.0, 0.0))
        self.assertGreater(b.resampling_time_range[0], 1e8)
        self.assertIsNone(c.events.push_robot)
        self.assertEqual(c.events.physics_material.params["static_friction_range"], (0.3, 0.3))

    def test_eval_settings_raise_on_changed_task(self):
        c = self.fake_cfg(); del c.commands.base_velocity.rel_standing_envs
        with self.assertRaises(core.ProtocolError):
            evaluate.apply_eval_settings(c, 0.3)
        c = self.fake_cfg(ranges=SimpleNamespace(lin_vel_x=(-2.0, 2.0), lin_vel_y=(-1.0, 1.0), ang_vel_z=(-1.0, 1.0)))
        with self.assertRaises(core.ProtocolError):
            evaluate.apply_eval_settings(c, 0.3)

    def test_output_names_unique(self):
        names = {evaluate.output_name({"arm": a, "seed": s}, mu)
                 for a in P.ARMS for s in P.TRAIN_SEEDS for mu in (0.3, 0.8, 0.05, None)}
        self.assertEqual(len(names), 2 * 5 * 4)


if __name__ == "__main__":
    unittest.main()
