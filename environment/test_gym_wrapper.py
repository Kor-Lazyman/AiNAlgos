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
            checks, "evaluate_shape"
        ) as shape:
            state, reward, terminated, truncated, info = env.step(self.action(env, ["W"] * 3))
        self.assertFalse(terminated or truncated)
        self.assertEqual(state[:, 4].tolist(), [Mode.W] * 3)
        self.assertEqual(reward, 0.0)
        for key in ("reward_shape", "reward_terminal", "reward_collision", "reward_makespan"):
            self.assertEqual(info[key], 0.0)
        self.assertIsNone(info["validation_pass"])
        valid.assert_not_called()
        shape.assert_not_called()

    def test_finish_is_absorbing_and_output_maps_f_to_w(self):
        env = self.make_env()
        env.reset()
        first_position = env.state[0, 1:4].copy()
        with patch.object(checks, "check_collision", return_value=1), patch.object(
            checks, "check_validation", return_value=1
        ) as valid, patch.object(checks, "evaluate_shape", return_value=(1, 100.0)) as shape:
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
        self.assertAlmostEqual(info["reward_terminal"], env.terminal_reward * info["reward_discount_scale"])
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

    def test_rewards_are_zero_until_finish_and_past_collision_is_charged_once(self):
        env = self.make_env(collision_penalty=3, makespan_weight=2, shape_weight=6)
        env.reset()
        with patch.object(checks, "check_collision", side_effect=[0, 1, 1]) as collision, patch.object(
            checks, "check_validation", return_value=1
        ), patch.object(checks, "evaluate_shape", return_value=(1, 100.0)) as shape:
            _, first, _, _, first_info = env.step(self.action(env, ["W"] * 3))
            _, second, _, _, _ = env.step(self.action(env, ["W"] * 3))
            shape.assert_not_called()
            _, reward, done, _, info = env.step(self.action(env, ["F"] * 3))
        self.assertEqual(first, 0.0)
        self.assertEqual(second, 0.0)
        self.assertEqual(first_info["collision_pass"], 0)
        self.assertEqual(first_info["reward_collision"], 0)
        self.assertTrue(done)
        self.assertEqual(info["collision_pass"], 1)
        self.assertEqual(info["episode_collision_pass"], 0)
        self.assertEqual(info["collision_steps"], 1)
        self.assertAlmostEqual(info["reward_collision"], -3 * info["reward_discount_scale"])
        self.assertEqual(info["reward_makespan"], 0)
        self.assertEqual(info["reward_shape"], 0)
        self.assertEqual(info["reward_terminal"], 0)
        self.assertEqual(info["success"], 0)
        self.assertAlmostEqual(info["terminal_score"], -3)
        self.assertAlmostEqual(reward * env.gamma ** 2, info["terminal_score"])
        shape.assert_called_once()
        second_window = collision.call_args_list[1].args[0]
        self.assertEqual(len(second_window["robot_id"]), 6)
        self.assertEqual(min(second_window["time_s"]), 0.0)
        self.assertAlmostEqual(max(second_window["time_s"]), 0.1)
        env.reset()
        with patch.object(checks, "check_collision", return_value=1):
            _, reward, _, _, info = env.step(self.action(env, ["W"] * 3))
        self.assertEqual(info["collision_steps"], 0)
        self.assertEqual(info["episode_collision_pass"], 1)
        self.assertEqual(reward, 0)

    def test_final_reward_requires_both_checks(self):
        for valid_result, shape_result in ((1, 1), (1, 0), (0, 1), (0, 0)):
            with self.subTest(valid=valid_result, shape=shape_result):
                env = self.make_env()
                env.reset()
                with patch.object(checks, "check_validation", return_value=valid_result) as valid:
                    with patch.object(checks, "evaluate_shape", return_value=(shape_result, 75.0)) as shape:
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
            checks, "evaluate_shape", return_value=(1, 100.0)
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

    def test_failure_dominates_all_other_discounted_rewards(self):
        for gamma in (0.99, 0.9999, 1.0):
            with self.subTest(gamma=gamma):
                env = self.make_env(max_steps=512, gamma=gamma, makespan_weight=3,
                                    collision_penalty=7, shape_weight=20, terminal_reward=200,
                                    terminal_penalty=0)
                # This conservative interval covers every possible episode length,
                # geometry, collision history and shape percentage.
                # Discount compensation cancels gamma at every episode length.
                self.assertGreater(env.terminal_penalty, env.return_bound)
                best_failed_return = -env.collision_penalty
                worst_successful_return = env.terminal_reward - env.makespan_weight
                self.assertLess(best_failed_return, worst_successful_return)
                self.assertLess(-env.terminal_penalty, -env.collision_penalty)

    def test_shape_percentage_reward_and_failure_at_early_and_late_finish(self):
        for length in (1, 4):
            for valid in (0, 1):
                with self.subTest(length=length, valid=valid):
                    env = self.make_env(max_steps=4, shape_weight=2)
                    env.reset()
                    rewards = []
                    with patch.object(checks, "check_collision", return_value=1), patch.object(
                        checks, "check_validation", return_value=valid
                    ), patch.object(checks, "evaluate_shape", return_value=(1, 80.0)) as shape:
                        for _ in range(length - 1):
                            _, reward, _, _, info = env.step(self.action(env, ["W"] * 3))
                            rewards.append(reward)
                            self.assertEqual(reward, 0.0)
                            self.assertEqual(info["reward_shape"], 0)
                            self.assertIsNone(info["shape_percentage"])
                        _, reward, _, _, info = env.step(self.action(env, ["F"] * 3))
                        rewards.append(reward)
                    shape.assert_called_once()
                    self.assertEqual(info["shape_percentage"], 80)
                    self.assertEqual(info["shape_score_percentage"], 80)
                    expected_shape = 160 * info["reward_discount_scale"] if valid else 0
                    self.assertAlmostEqual(info["reward_shape"], expected_shape)
                    self.assertAlmostEqual(reward, sum(info[key] for key in (
                        "reward_shape", "reward_terminal", "reward_collision", "reward_makespan")))
                    if not valid:
                        total = sum(env.gamma ** i * r for i, r in enumerate(rewards))
                        self.assertLess(total, -env.return_bound)

    def test_priority_shape_then_collision_then_makespan_for_discounted_return(self):
        def episode(percentage, shape_pass, collision, duration, steps, gamma):
            env = self.make_env(max_steps=4, wait_time_s=duration, gamma=gamma)
            env.reset()
            rewards = []
            with patch.object(checks, "check_collision", return_value=1 - collision), patch.object(
                checks, "check_validation", return_value=1
            ), patch.object(checks, "evaluate_shape", return_value=(shape_pass, percentage)):
                for step in range(steps):
                    modes = ["F"] * 3 if step == steps - 1 else ["W"] * 3
                    _, reward, _, _, info = env.step(self.action(env, modes))
                    rewards.append(reward)
            self.assertTrue(all(value == 0 for value in rewards[:-1]))
            score = sum(gamma ** index * value for index, value in enumerate(rewards))
            self.assertAlmostEqual(score, info["terminal_score"])
            return score

        for gamma in (0.99, 0.9999, 1.0):
            with self.subTest(gamma=gamma):
                # Failed shape gets no advantage from coverage, safety or speed.
                failed = episode(100, 0, 0, 0.1, 1, gamma)
                failed_slow = episode(0, 0, 1, 10000, 4, gamma)
                self.assertAlmostEqual(failed, failed_slow)
                # After shape passes, collision blocks all positive/time scoring.
                collision = episode(100, 1, 1, 0.1, 1, gamma)
                collision_slow = episode(95, 1, 1, 10000, 4, gamma)
                self.assertAlmostEqual(collision, collision_slow)
                self.assertLess(collision, 0)
                self.assertGreater(collision, failed)
                safe = episode(95, 1, 0, 10000, 4, gamma)
                self.assertGreater(safe, collision)
                # Only after all gates pass do coverage and makespan rank results.
                better_shape = episode(96, 1, 0, 10000, 4, gamma)
                fast = episode(95.99, 1, 0, 0.1, 1, gamma)
                self.assertGreater(better_shape, fast)
                self.assertGreater(fast, safe)

    def test_higher_priority_failure_blocks_every_reward_component(self):
        for finished in (False, True):
            for valid in (0, 1):
                for shape_pass in (0, 1):
                    for collision_pass in (0, 1):
                        with self.subTest(finished=finished, valid=valid, shape=shape_pass, collision=collision_pass):
                            env = self.make_env(max_steps=1)
                            env.reset()
                            with patch.object(checks, "check_validation", return_value=valid), patch.object(
                                checks, "evaluate_shape", return_value=(shape_pass, 100.0)
                            ), patch.object(checks, "check_collision", return_value=collision_pass):
                                _, reward, done, truncated, info = env.step(
                                    self.action(env, ["F" if finished else "W"] * 3)
                                )
                            success = finished and valid == 1 and shape_pass == 1 and collision_pass == 1
                            self.assertEqual(info["success"], int(success))
                            self.assertEqual(done, finished)
                            self.assertEqual(truncated, not finished)
                            if not (finished and valid and shape_pass):
                                self.assertEqual(info["reward_terminal"], -env.terminal_penalty)
                                self.assertEqual(info["reward_collision"], 0)
                                self.assertEqual(info["reward_shape"], 0)
                                self.assertEqual(info["reward_makespan"], 0)
                            elif not collision_pass:
                                self.assertEqual(info["reward_collision"], -env.collision_penalty)
                                self.assertEqual(info["reward_terminal"], 0)
                                self.assertEqual(info["reward_shape"], 0)
                                self.assertEqual(info["reward_makespan"], 0)
                            else:
                                self.assertEqual(info["reward_shape"], 100 * env.shape_weight)
                                self.assertEqual(info["reward_terminal"], env.terminal_reward)
                                self.assertLess(info["reward_makespan"], 0)
                            if not success:
                                self.assertLess(reward, 0)
                                self.assertTrue(all(info[key] <= 0 for key in (
                                    "reward_shape", "reward_collision", "reward_makespan", "reward_terminal")))

    def test_delay_cannot_reduce_discounted_failure_penalty(self):
        scores = []
        for steps in (1, 4):
            env = self.make_env(max_steps=4, gamma=0.9, makespan_weight=0)
            env.reset()
            with patch.object(checks, "check_collision", return_value=1), patch.object(
                checks, "check_validation", return_value=1
            ), patch.object(checks, "evaluate_shape", return_value=(0, 30.9)):
                for index in range(steps):
                    _, reward, _, _, info = env.step(self.action(env, ["F" if index == steps - 1 else "W"] * 3))
            scores.append(reward * env.gamma ** (steps - 1))
            self.assertEqual(info["shape_percentage"], 30.9)
            self.assertEqual(info["shape_score_percentage"], 30)
        self.assertAlmostEqual(scores[0], scores[1])

    def test_invalid_reward_configuration(self):
        for kwargs in ({"gamma": 0}, {"gamma": 1.1}, {"gamma": float("nan")},
                       {"shape_weight": -1}, {"shape_weight": float("inf")},
                       {"gamma": 0.001, "max_steps": 1000}, {"terminal_penalty": 1e40},
                       {"makespan_weight": 1}, {"shape_weight": 1},
                       {"makespan_reference_s": 0}, {"makespan_reference_s": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                WaamGymEnv(**kwargs)

    def test_shape_evaluation_invalid_input_fails_closed(self):
        self.assertEqual(checks.evaluate_shape({}), (0, 0.0))
        self.assertEqual(checks.check_shape({}), 0)

    def test_real_collision_detection(self):
        env = self.make_env()
        env.reset()
        action = self.action(env, ["T"] * 3, [[0, 0, 2]] * 3)
        _, reward, terminated, _, info = env.step(action)
        self.assertFalse(terminated)
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(info["episode_collision_pass"], 0)
        self.assertEqual(info["reward_collision"], 0)
        self.assertEqual(reward, 0)

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
        self.assertGreater(info["shape_percentage"], 90)
        self.assertLessEqual(info["shape_percentage"], 100)
        self.assertAlmostEqual(info["reward_shape"], env.shape_weight * info["shape_score_percentage"]
                               * info["reward_discount_scale"])
        trajectory = env.get_trajectory()
        frame = pd.DataFrame(trajectory)
        for check in (checks.check_collision, checks.check_shape, checks.check_validation):
            self.assertEqual(check(frame), check(trajectory))
        self.assertEqual(checks.evaluate_shape(frame), checks.evaluate_shape(trajectory))
        after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in env.job_dir.iterdir()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
