import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import shutil

import numpy as np
import trimesh
from shapely.geometry import LineString

from models.terminal_rewards import TerminalRewards
from environment.residual_wrapper import ResidualStrokeEnv

ROOT = Path(__file__).resolve().parents[1]


class TerminalRewardTests(unittest.TestCase):
    def test_threshold_is_inclusive_and_failures_never_get_speed_or_pass_bonus(self):
        settings = TerminalRewards(min_mesh_iou=.9)
        def score(iou, validated=True, time=100):
            return settings.bonuses(validated=validated, actual_iou=iou, makespan_s=time, reference_seconds=100)
        self.assertEqual(score(.949999), (10, 0))
        self.assertEqual(score(.95), (10, .5))
        self.assertEqual(score(1, False, 0), (0, 0))
        self.assertGreater(score(.98, time=50)[1], score(.98, time=200)[1])
        self.assertLessEqual(score(1, time=0)[1], settings.makespan_weight)

    def test_invalid_settings_are_rejected(self):
        for options in ({"makespan_iou_threshold": 0}, {"makespan_iou_threshold": 1.1},
                        {"validation_bonus": 1, "makespan_weight": 2}, {"makespan_weight": -1},
                        {"reference_seconds": 0}, {"reference_seconds": float("nan")},
                        {"validation_bonus": float("inf")}, {"min_mesh_iou": -.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                TerminalRewards(**options)

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)
        shutil.copy2(ROOT/"examples/generic_jobs/box/config.yaml", self.job/"config.yaml")
        shape = LineString([(-5, 0), (5, 0)]).buffer(2, quad_segs=8)
        trimesh.creation.extrude_polygon(shape, 2, engine="earcut").export(self.job/"target.stl")

    def env(self, max_steps=8):
        env = ResidualStrokeEnv(self.job, grid_size=4, max_steps=max_steps,
                                 terminal_rewards=TerminalRewards(reference_seconds=100))
        self.addCleanup(env.close)
        env.reset()
        env._focus["anchor"] = np.array([0., 0.])
        return env

    def deposit(self, env):
        return env.step(np.array([-.625, 0, .625, 0, -1, 0], np.float32))

    def command(self, env, command):
        return env.step(np.array([0, 0, 0, 0, -1, command], np.float32))

    def test_real_stl_pass_pays_once_and_waiting_reduces_only_speed_bonus(self):
        env = self.env()
        _, _, _, _, before = self.deposit(env)
        self.assertEqual(before["terminal_validation_checked"], 0)
        self.assertEqual(before["reward_validation_bonus"], 0)
        _, _, _, _, fast = self.command(env, 1)
        self.assertTrue(fast["success"])
        self.assertGreater(fast["terminal_mesh_iou"], .999)
        self.assertEqual(fast["reward_validation_bonus"], 10)
        env.reset()
        env._focus["anchor"] = np.array([0., 0.])
        self.deposit(env)
        self.command(env, .7)  # Actual W time enters makespan.
        _, _, _, _, slow = self.command(env, 1)
        self.assertEqual(slow["terminal_mesh_iou"], fast["terminal_mesh_iou"])
        self.assertEqual(slow["reward_validation_bonus"], fast["reward_validation_bonus"])
        self.assertGreater(slow["makespan_s"], fast["makespan_s"])
        self.assertLess(slow["reward_makespan"], fast["reward_makespan"])
        _, reset = env.reset()
        self.assertEqual(reset["reward_makespan"], 0)
        self.assertEqual(reset["terminal_validation_checked"], 0)

    def test_nominal_pass_does_not_pay_when_actual_mesh_check_fails(self):
        env = self.env()
        self.deposit(env)
        with patch.object(env, "_check_terminal_mesh", return_value=(False, .90)) as check:
            _, _, _, _, info = self.command(env, 1)
        check.assert_called_once()
        self.assertEqual(info["shape_pass"], 1)
        self.assertFalse(info["success"])
        self.assertEqual(info["reward_validation_bonus"], 0)
        self.assertEqual(info["reward_makespan"], 0)

    def test_timeout_and_collision_skip_expensive_validation_and_bonus(self):
        env = self.env(max_steps=1)
        with patch.object(env, "_check_terminal_mesh") as check:
            _, _, done, truncated, info = self.deposit(env)
        check.assert_not_called()
        self.assertTrue(truncated)
        self.assertFalse(done or info["success"])
        self.assertEqual(info["reward_makespan"], 0)
        env = self.env()
        with patch.object(env._checks, "collision_free", return_value=False):
            self.deposit(env)
        with patch.object(env, "_check_terminal_mesh") as check:
            _, _, _, _, info = self.command(env, 1)
        check.assert_not_called()
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(info["reward_validation_bonus"], 0)


if __name__ == "__main__":
    unittest.main()
