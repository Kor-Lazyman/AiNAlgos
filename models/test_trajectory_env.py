"""Verify the policy's actions, not a planner, create the exported trajectory."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import subprocess
import sys
import unittest

import numpy as np
import torch
import trimesh
from gymnasium.error import ResetNeeded
from shapely import LineString
from models.episode_ppo import EpisodePPO as PPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.monitor import Monitor

from environment.trajectory_env import TrajectoryPPOEnv
from environment.sampled_ppo_wrapper import SampledWaamPPOEnv
from environment import env as checks
from models.tensorboard_reporting import ValidationTensorBoardCallback

ROOT = Path(__file__).resolve().parents[1]


class DirectTrajectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.job = Path(cls.tmp.name) / "job"
        cls.job.mkdir()
        shutil.copy2(ROOT / "examples/generic_jobs/box/config.yaml", cls.job / "config.yaml")
        polygon = LineString([(-5, 0), (5, 0)]).buffer(2, quad_segs=8)
        trimesh.creation.extrude_polygon(polygon, 2, engine="earcut").export(cls.job / "target.stl")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make_env(self, **kwargs):
        return TrajectoryPPOEnv(self.job, grid_size=4, **kwargs)

    def action(self, env, xyz=None, modes=("W", "W", "W")):
        positions = env.state[:, 1:4].astype(float)
        if xyz is not None:
            positions[0] = xyz
        return env.action_from_targets(positions, modes)

    def test_direct_waypoints_form_valid_deposition_and_finish(self):
        env = self.make_env(max_steps=10)
        obs, _ = env.reset()
        self.assertGreater(obs["target"].sum(), 0)
        self.assertEqual(obs["deposited"].sum(), 0)
        env.step(self.action(env, [-5, 0, 2], ("T", "W", "W")))
        obs, reward, done, truncated, info = env.step(self.action(env, [5, 0, 2], ("D", "W", "W")))
        self.assertFalse(done or truncated)  # One nominal slab does not end the episode.
        self.assertGreater(reward, 0)  # Dense IoU progress before the terminal percentage.
        self.assertGreater(obs["deposited"].sum(), 0)
        obs, reward, done, truncated, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertAlmostEqual(reward, info["reward_similarity"] + info["reward_incomplete"])
        self.assertGreater(reward, 99.9)
        self.assertTrue(done)
        self.assertFalse(truncated)
        self.assertTrue(info["success"], info)
        self.assertEqual(info["action_count"], 3)
        self.assertEqual(len(env.action_history), 3)
        data = env.get_trajectory()
        self.assertEqual(checks.check_validation(data, job_dir=self.job), 1)
        self.assertEqual(checks.check_collision(data, job_dir=self.job), 1)
        self.assertEqual(checks.check_shape(data, job_dir=self.job), 1)
        self.assertIn("F", env.get_trajectory(preserve_finish=True)["mode"])
        self.assertNotIn("F", data["mode"])
        np.testing.assert_allclose(env.state[0, 1:4], [5, 0, 2], atol=1e-4)
        self.assertTrue(env.observation_space.contains(obs))
        # Test the standalone file pipeline on the same executed actions.
        from train import write_csv
        write_csv(self.job / "trajectory.csv", data)
        report = Path(self.tmp.name) / "independent"
        result = subprocess.run([sys.executable, str(ROOT / "validate.py"), str(self.job), str(report)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        artifact = json.loads((report.parent / "artifact_verification.json").read_text())
        self.assertTrue(artifact["stl_generated"] and artifact["stl_watertight"])
        self.assertEqual(artifact["validation_status"], "PASS")

    def test_waypoint_changes_change_trajectory_without_templates(self):
        env = self.make_env()
        ends = []
        for x in (-7, 9):
            env.reset()
            obs, _, done, _, _ = env.step(self.action(env, [x, 1, 4], ("T", "W", "W")))
            self.assertFalse(done)
            self.assertTrue(env.observation_space.contains(obs))
            ends.append(env.get_trajectory()["x_mm"][1])
        np.testing.assert_allclose(ends, [-7, 9], atol=1e-4)

    def test_invalid_deposition_is_not_projected_to_a_legal_path(self):
        env = self.make_env()
        env.reset()
        env.step(self.action(env, [-5, 0, 2], ("T", "W", "W")))
        _, reward, done, _, info = env.step(self.action(env, [5, 0, 3], ("D", "W", "W")))
        self.assertFalse(done)
        self.assertFalse(info["success"])
        self.assertEqual(info["termination_reason"], "running")
        self.assertEqual(info["validation_pass"], 0)
        self.assertEqual(reward, -10.)
        self.assertAlmostEqual(float(env.state[0, 3]), 3, places=4)
        self.assertEqual(checks.check_validation(env.get_trajectory(), job_dir=self.job), 0)
        _, reward, done, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertFalse(info["success"])
        self.assertEqual(reward, -100.)
        self.assertEqual(info["validation_pass"], 0)  # Earlier invalid action remains a failure.

    def test_finish_and_timeout_are_not_layer_counts(self):
        env = self.make_env(max_steps=3)
        env.reset()
        _, _, done, truncated, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertFalse(truncated or info["success"])
        self.assertEqual(info["action_count"], 1)
        env.reset()
        for _ in range(3):
            _, _, done, truncated, info = env.step(self.action(env))
        self.assertFalse(done or info["success"])
        self.assertTrue(truncated)
        self.assertEqual(info["termination_reason"], "max_steps")
        self.assertNotIn("F", env.get_trajectory(preserve_finish=True)["mode"])

    def test_collisions_fail_and_finished_robot_is_absorbing(self):
        env = self.make_env()
        env.reset()
        xyz = env.state[:, 1:4].copy()
        xyz[:2] = [0, 0, 2]
        _, reward, done, _, info = env.step(env.action_from_targets(xyz, ["T", "T", "W"]))
        self.assertFalse(done)
        self.assertEqual(info["termination_reason"], "running")
        self.assertEqual(reward, -50.)
        self.assertEqual(info["reward_collision"], -50.)
        _, reward, done, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertFalse(info["success"])
        self.assertEqual(reward, -150.)  # Empty finish plus this action collision.
        self.assertEqual(info["episode_reward_collision"], -100.)
        with self.assertRaises(ResetNeeded):
            env.step(self.action(env))
        env.reset()
        home = env.state[0, 1:4].copy()
        env.step(self.action(env, modes=("F", "W", "W")))
        env.step(self.action(env, [0, 0, 2], ("T", "W", "W")))
        np.testing.assert_array_equal(env.state[0, 1:4], home)

    def test_collision_reward_also_applies_to_invalid_process_and_resets(self):
        env = self.make_env(collision_penalty=75.)
        self.addCleanup(env.close)
        env.reset()
        xyz = env.state[:, 1:4].copy()
        xyz[:2] = [0, 0, 2]
        _, reward, done, _, info = env.step(env.action_from_targets(xyz, ["D", "D", "W"]))
        self.assertFalse(done)
        self.assertEqual(info["termination_reason"], "running")
        self.assertEqual(info["validation_pass"], 0)
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(info["reward_collision"], -75.)
        self.assertEqual(reward, -85.)
        self.assertEqual(env.action_history[-1]["reward_collision"], -75.)
        _, reward, done, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertEqual(reward, -175.)
        self.assertEqual(info["episode_reward_collision"], -150.)
        _, info = env.reset()
        self.assertEqual(info["reward_collision"], 0.)
        _, reward, _, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertEqual(reward, -100.)  # Empty finish penalty.
        self.assertEqual(info["reward_collision"], 0.)

    def test_collision_penalty_validation_and_zero_weight(self):
        for penalty in (-1., float("nan"), float("inf"), 1e100):
            with self.subTest(penalty=penalty), self.assertRaises(ValueError):
                self.make_env(collision_penalty=penalty)
        env = self.make_env(collision_penalty=0.)
        self.addCleanup(env.close)
        env.reset()
        xyz = env.state[:, 1:4].copy()
        xyz[:2] = [0, 0, 2]
        _, reward, done, _, info = env.step(env.action_from_targets(xyz, ["T", "T", "W"]))
        self.assertFalse(done)  # Reward weight does not disable collision validation.
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(reward, 0.)
        _, reward, done, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertFalse(info["success"])
        self.assertEqual(reward, -100.)

    def test_collision_history_stays_failed_after_separation_and_finish(self):
        env = self.make_env()
        self.addCleanup(env.close)
        env.reset()
        homes = env.state[:, 1:4].copy()
        xyz = homes.copy()
        xyz[:2] = [0, 0, 2]
        env.step(env.action_from_targets(xyz, ["T", "T", "W"]))
        env.step(env.action_from_targets(homes, ["T", "T", "W"]))
        _, reward, done, _, info = env.step(self.action(env, modes=("F", "F", "F")))
        self.assertTrue(done)
        self.assertEqual(info["reward_collision"], 0.)
        self.assertEqual(info["episode_reward_collision"], -100.)
        self.assertEqual(info["collision_pass"], 0)
        self.assertFalse(info["success"])
        self.assertEqual(reward, -100.)

    def test_partial_shape_percentage_paid_once_on_finish_or_timeout(self):
        for max_steps in (2, 4):
            with self.subTest(max_steps=max_steps):
                env = self.make_env(max_steps=max_steps)
                self.addCleanup(env.close)
                env.reset()
                env.step(self.action(env, [-5, 0, 2], ("T", "W", "W")))
                _, reward, done, truncated, info = env.step(self.action(env, [0, 0, 2], ("D", "W", "W")))
                if max_steps == 4:
                    self.assertGreater(reward, 0.)
                    self.assertFalse(done or truncated)
                    _, reward, done, truncated, info = env.step(self.action(env, modes=("F", "F", "F")))
                self.assertTrue(done or truncated)
                self.assertEqual(truncated, max_steps == 2)
                self.assertFalse(info["success"])  # Reward exists below the validation threshold.
                self.assertGreater(reward, 0.)
                self.assertLess(reward, 100.)
                expected = info["reward_similarity"] + info["reward_incomplete"]
                if max_steps == 2:
                    expected += info["episode_reward_shape"]
                self.assertAlmostEqual(reward, expected)
                self.assertEqual(info["reward_similarity"], info["similarity_percent"])
                with self.assertRaises(ResetNeeded):
                    env.step(self.action(env, modes=("F", "F", "F")))
                _, info = env.reset()
                self.assertEqual(info["reward_similarity"], 0.)

    def test_overfill_reduces_similarity_reward(self):
        scores = []
        for end_x in (5, 10):
            env = self.make_env()
            self.addCleanup(env.close)
            env.reset()
            env.step(self.action(env, [-5, 0, 2], ("T", "W", "W")))
            env.step(self.action(env, [end_x, 0, 2], ("D", "W", "W")))
            _, reward, _, _, info = env.step(self.action(env, modes=("F", "F", "F")))
            scores.append(reward)
            if end_x == 10:
                self.assertGreater(info["overfill"], 0.)
                self.assertGreater(info["coverage"], .99)
                self.assertLess(reward, 99.)
        self.assertLess(scores[1], scores[0])

    def test_gym_contract_real_ppo_sampling_save_and_reload(self):
        torch.set_num_threads(2)
        env = self.make_env(max_steps=4)
        check_env(env, warn=True)
        second = TrajectoryPPOEnv(ROOT / "examples/generic_jobs/box", grid_size=4, max_steps=4)
        sampled = SampledWaamPPOEnv([env, second], ["bead", "box"])
        monitor = Monitor(sampled)
        log_dir = Path(self.tmp.name) / "logs"
        model = PPO("MultiInputPolicy", monitor, n_steps=16, batch_size=16, n_epochs=1,
                    policy_kwargs={"net_arch": dict(pi=[16], vf=[16])},
                    device="cpu", tensorboard_log=str(log_dir), seed=42)
        before = [p.detach().clone() for p in model.policy.parameters()]
        model.learn_episodes(total_episodes=8, callback=ValidationTensorBoardCallback())
        self.assertEqual(model.completed_episodes, 8)
        self.assertEqual(int(sampled.episode_counts.sum()), 8)
        self.assertTrue(any(not torch.equal(a, b) for a, b in zip(before, model.policy.parameters())))
        self.assertTrue(all(sampled.episode_counts > 0))
        path = Path(self.tmp.name) / "direct_ppo.zip"
        model.save(path)
        reloaded = PPO.load(path, device="cpu")
        obs, _ = env.reset(seed=42)
        original, _ = model.predict(obs, deterministic=True)
        restored, _ = reloaded.predict(obs, deterministic=True)
        self.assertEqual(restored.shape, (3, 4))
        np.testing.assert_array_equal(original, restored)
        self.assertTrue(list(log_dir.rglob("events.out.tfevents.*")))
        model.logger.close()
        monitor.close()


if __name__ == "__main__":
    unittest.main()
