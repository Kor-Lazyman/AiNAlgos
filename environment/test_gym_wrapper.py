"""Run from the version 0.0.2 root: python -B -m unittest environment.test_gym_wrapper."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium.utils.env_checker import check_env

from . import env as checks
from .gym_wrapper import Mode, WaamGymEnv


class WaamGymEnvTests(unittest.TestCase):
    def make_env(self, **kwargs):
        env = WaamGymEnv(**kwargs)
        self.addCleanup(env.close)
        return env

    @staticmethod
    def action(env, modes, targets=None):
        return env.action_from_targets(env.state[:, 1:4] if targets is None else targets, modes)

    def test_gymnasium_contract(self):
        env = self.make_env(max_steps=4)
        check_env(env, skip_render_check=True)

    def test_observation_and_action_encoding(self):
        env = self.make_env()
        state, _ = env.reset(seed=3)
        self.assertEqual(state.shape, (3, 5))
        self.assertEqual(state.dtype, np.float32)
        self.assertTrue(env.observation_space.contains(state))
        for name in ("T", "D", "W", "F"):
            action = self.action(env, [name] * 3)
            self.assertTrue(env.action_space.contains(action))
            xyz, modes = env._decode_action(action)
            np.testing.assert_allclose(xyz, state[:, 1:4], atol=1e-4)
            self.assertEqual(modes, [Mode[name]] * 3)
        state[:] = -999
        self.assertTrue(env.observation_space.contains(env.state))

    def test_wait_is_not_finish_and_terminal_checks_are_deferred(self):
        env = self.make_env()
        env.reset()
        with patch.object(checks, "check_validation") as valid, patch.object(
            checks, "check_shape"
        ) as shape:
            state, reward, terminated, truncated, info = env.step(self.action(env, ["W"] * 3))
        self.assertFalse(terminated or truncated)
        self.assertEqual(state[:, 4].tolist(), [Mode.W] * 3)
        self.assertAlmostEqual(reward, -env.makespan_weight * env.wait_time_s)
        self.assertIsNone(info["validation_pass"])
        valid.assert_not_called()
        shape.assert_not_called()

    def test_finish_is_absorbing_and_output_maps_f_to_w(self):
        env = self.make_env()
        env.reset()
        first_position = env.state[0, 1:4].copy()
        with patch.object(checks, "check_collision", return_value=1), patch.object(
            checks, "check_validation", return_value=1
        ) as valid, patch.object(checks, "check_shape", return_value=1) as shape:
            _, _, done, _, _ = env.step(self.action(env, ["F", "W", "W"]))
            self.assertFalse(done)
            targets = env.state[:, 1:4].copy()
            targets[0] = (env.xyz_low + env.xyz_high) / 2
            state, _, done, truncated, info = env.step(self.action(env, ["T", "F", "F"], targets))
        self.assertTrue(done)
        self.assertFalse(truncated)
        np.testing.assert_array_equal(state[0, 1:4], first_position)
        self.assertEqual(state[:, 4].tolist(), [Mode.F] * 3)
        self.assertEqual(info["success"], 1)
        self.assertEqual(info["reward_terminal"], env.terminal_reward)
        valid.assert_called_once()
        shape.assert_called_once()
        output = env.get_trajectory()
        self.assertNotIn("F", output["mode"])
        self.assertTrue(all(mode == "W" for mode in output["mode"]))
        output["x_mm"][0] = 999999
        self.assertNotEqual(env.get_trajectory()["x_mm"][0], 999999)
        with self.assertRaises(gym.error.ResetNeeded):
            env.step(self.action(env, ["W"] * 3))

    def test_simultaneous_timing_and_wait_padding(self):
        env = self.make_env()
        env.reset()
        targets = env.state[:, 1:4].copy()
        targets[0, 0] += 150
        targets[1, 0] -= 75
        state, _, terminated, _, info = env.step(self.action(env, ["T", "T", "W"], targets))
        self.assertFalse(terminated)
        self.assertAlmostEqual(info["makespan_s"], 1.0, places=5)
        np.testing.assert_allclose(state[:, 0], 1.0, atol=1e-5)
        data = env.get_trajectory()
        rows = [i for i, robot_id in enumerate(data["robot_id"]) if robot_id == 2]
        self.assertEqual([data["mode"][i] for i in rows], ["T", "W", "W"])
        np.testing.assert_allclose([data["time_s"][i] for i in rows], [0, 0.5, 1], atol=1e-5)
        self.assertEqual(checks.check_validation(data), 1)

    def test_deposition_uses_configured_speed(self):
        env = self.make_env()
        env.reset()
        targets = env.state[:, 1:4].copy()
        targets[0, 0] += env.config.process.deposition_speed_mm_s
        with patch.object(checks, "check_validation") as valid:
            _, _, _, _, info = env.step(self.action(env, ["D", "W", "W"], targets))
        self.assertAlmostEqual(info["delta_makespan_s"], 1.0, places=4)
        self.assertEqual(env.get_trajectory()["mode"][0], "D")
        valid.assert_not_called()

    def test_old_collisions_are_not_repeated_and_time_is_incremental(self):
        env = self.make_env(collision_penalty=3, makespan_weight=2)
        env.reset()
        with patch.object(checks, "check_collision", side_effect=[0, 1]) as collision:
            _, first, _, _, _ = env.step(self.action(env, ["W"] * 3))
            _, second, _, _, _ = env.step(self.action(env, ["W"] * 3))
        self.assertAlmostEqual(first, -3.2)
        self.assertAlmostEqual(second, -0.2)
        second_window = collision.call_args_list[1].args[0]
        self.assertEqual(len(second_window["robot_id"]), 6)
        self.assertEqual(min(second_window["time_s"]), 0.0)
        self.assertAlmostEqual(max(second_window["time_s"]), 0.1)

    def test_final_reward_requires_both_checks(self):
        for valid_result, shape_result in ((1, 1), (1, 0), (0, 1), (0, 0)):
            with self.subTest(valid=valid_result, shape=shape_result):
                env = self.make_env()
                env.reset()
                with patch.object(checks, "check_validation", return_value=valid_result) as valid:
                    with patch.object(checks, "check_shape", return_value=shape_result) as shape:
                        _, _, done, _, info = env.step(self.action(env, ["F"] * 3))
                self.assertTrue(done)
                self.assertEqual(info["success"], valid_result * shape_result)
                valid.assert_called_once()
                shape.assert_called_once()
                expected = env.terminal_reward if info["success"] else -env.terminal_penalty
                self.assertEqual(info["reward_terminal"], expected)

    def test_truncation_cannot_receive_success_bonus(self):
        env = self.make_env(max_steps=1)
        env.reset()
        with patch.object(checks, "check_validation", return_value=1) as valid, patch.object(
            checks, "check_shape", return_value=1
        ) as shape:
            _, _, done, truncated, info = env.step(self.action(env, ["W"] * 3))
        self.assertFalse(done)
        self.assertTrue(truncated)
        self.assertEqual(info["success"], 0)
        self.assertEqual(info["reward_terminal"], -env.terminal_penalty)
        valid.assert_called_once()
        shape.assert_called_once()
        state, _ = env.reset()
        np.testing.assert_array_equal(state[:, 0], 0)
        np.testing.assert_array_equal(state[:, 4], Mode.W)
        self.assertEqual(len(env.get_trajectory()["robot_id"]), 3)

    def test_invalid_actions_do_not_mutate_state(self):
        env = self.make_env()
        with self.assertRaises(gym.error.ResetNeeded):
            env.step(np.zeros((3, 4), dtype=np.float32))
        env.reset()
        before = env.state
        for action in (np.zeros(12), np.full((3, 4), np.nan), np.full((3, 4), 2)):
            with self.assertRaises(ValueError):
                env.step(action)
            np.testing.assert_array_equal(env.state, before)
        env.close()
        with self.assertRaises(RuntimeError):
            env.reset()

    def test_real_collision_detection(self):
        env = self.make_env()
        env.reset()
        action = self.action(env, ["T"] * 3, [[0, 0, 2]] * 3)
        _, _, terminated, _, info = env.step(action)
        self.assertFalse(terminated)
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(info["reward_collision"], -env.collision_penalty)

    def test_real_shape_and_validation_at_finish_and_dataframe_input(self):
        env = self.make_env()
        before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in env.job_dir.iterdir()}
        env.reset()
        targets = env.state[:, 1:4].copy()
        targets[0] = [-40, 0, 2]
        env.step(self.action(env, ["T", "F", "F"], targets))
        targets[0] = [40, 0, 2]
        env.step(self.action(env, ["D", "F", "F"], targets))
        _, _, terminated, truncated, info = env.step(self.action(env, ["F"] * 3))
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["validation_pass"], 1)
        self.assertEqual(info["shape_pass"], 1)
        self.assertEqual(info["success"], 1)
        trajectory = env.get_trajectory()
        frame = pd.DataFrame(trajectory)
        for check in (checks.check_collision, checks.check_shape, checks.check_validation):
            self.assertEqual(check(frame), check(trajectory))
        after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in env.job_dir.iterdir()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
