"""Verify policy segment execution, real collisions and unbiased shape rewards."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from shapely import LineString
import trimesh
import yaml
import torch
from stable_baselines3.common.env_checker import check_env

from environment.stroke_wrapper import StrokePPOEnv
from environment import env as checks
from train import write_csv, rollout, select_policy_rollout
from models.episode_ppo import EpisodePPO

ROOT = Path(__file__).resolve().parents[1]


class StrokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)/"job"
        self.job.mkdir()
        shutil.copy2(ROOT/"examples/generic_jobs/box/config.yaml", self.job/"config.yaml")
        polygon = LineString([(-5, 0), (5, 0)]).buffer(2, quad_segs=8)
        trimesh.creation.extrude_polygon(polygon, 2, engine="earcut").export(self.job/"target.stl")

    def make_env(self, **kwargs):
        env = StrokePPOEnv(self.job, grid_size=4, **kwargs)
        self.addCleanup(env.close)
        env.reset()
        return env

    def stroke(self, end=1.):
        return np.array([-1, 0, end, 0, 0, -1, 0], dtype=np.float32)

    def finish(self):
        return np.array([0, 0, 0, 0, 0, 0, 1], dtype=np.float32)

    def test_policy_segment_has_real_T_D_return_and_independent_stl(self):
        env = self.make_env()
        _, reward, done, truncated, info = env.step(self.stroke())
        self.assertGreater(reward, .99)
        self.assertFalse(done or truncated)
        self.assertEqual(info["action_count"], 1)
        self.assertEqual(info["deposition_commands"], 1)
        data = env.get_trajectory(preserve_finish=True)
        rows = list(zip(*data.values()))
        robot1 = [r for r in rows if r[0] == 1]
        self.assertEqual([r[-1] for r in robot1], ["T", "D", "T", "W"])
        np.testing.assert_allclose(robot1[1][2:5], [-5, 0, 2], atol=1e-4)
        np.testing.assert_allclose(robot1[2][2:5], [5, 0, 2], atol=1e-4)
        np.testing.assert_allclose(env.state[:, 1:4], env._homes)
        _, reward, done, truncated, info = env.step(self.finish())
        self.assertTrue(done and info["success"])
        self.assertGreater(reward, 1.24)
        write_csv(self.job/"trajectory.csv", env.get_trajectory())
        result = subprocess.run([sys.executable, str(ROOT/"validate.py"), str(self.job), str(Path(self.tmp.name)/"validation")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        artifact = json.loads((Path(self.tmp.name)/"artifact_verification.json").read_text())
        self.assertGreater(artifact["mesh_comparison"]["iou"], .999)

    def test_collision_does_not_stop_or_erase_the_requested_motion(self):
        config = yaml.safe_load((self.job/"config.yaml").read_text())
        config["robots"][1]["home_xyz_mm"] = [0., 0., 2.]
        (self.job/"config.yaml").write_text(yaml.safe_dump(config))
        env = self.make_env(max_steps=4)
        _, _, done, truncated, info = env.step(self.stroke())
        self.assertFalse(done or truncated)
        self.assertEqual(info["collision_pass"], 0)
        self.assertEqual(info["collision_steps"], 1)
        self.assertEqual(info["termination_reason"], "running")
        self.assertIn("D", env.get_trajectory()["mode"])
        _, _, done, truncated, info = env.step(self.stroke(.5))
        self.assertFalse(done or truncated)
        self.assertEqual(info["action_count"], 2)
        _, _, done, _, info = env.step(self.finish())
        self.assertTrue(done)
        self.assertFalse(info["success"])
        self.assertLess(env.action_history[-1]["reward_terminal_adjustment"], 0)

    def test_partial_duplicate_and_empty_finish_rewards(self):
        env = self.make_env()
        _, first, _, _, partial = env.step(self.stroke(0))
        _, duplicate, _, _, repeated = env.step(self.stroke(0))
        self.assertGreater(first, 0)
        self.assertLess(partial["iou"], .99)
        self.assertAlmostEqual(duplicate, 0)
        self.assertAlmostEqual(partial["iou"], repeated["iou"])
        env.reset()
        _, reward, done, _, info = env.step(self.finish())
        self.assertTrue(done)
        self.assertEqual(reward, -1.)
        self.assertEqual(info["early_finish"], 1)
        self.assertFalse(info["success"])

    def test_invalid_zero_length_is_recorded_and_timeout_is_not_finish(self):
        env = self.make_env(max_steps=2)
        _, _, done, truncated, info = env.step(self.stroke(-1))
        self.assertFalse(done or truncated)
        self.assertEqual(info["invalid_process_steps"], 1)
        self.assertEqual(info["validation_pass"], 0)
        _, _, done, truncated, info = env.step(self.stroke())
        self.assertTrue(truncated)
        self.assertFalse(done or info["success"])
        self.assertNotIn("F", env.get_trajectory(preserve_finish=True)["mode"])

    def test_gym_bounds_and_policy_points_change_the_deposited_shape(self):
        env = self.make_env(max_steps=4)
        check_env(env)
        scores = []
        for end in (0, 1):
            env.reset()
            obs, _, _, _, info = env.step(self.stroke(end))
            self.assertTrue(env.observation_space.contains(obs))
            scores.append(info["iou"])
        self.assertGreater(scores[1], scores[0])
        self.assertEqual(checks.check_validation(env.get_trajectory(), job_dir=self.job), 1)

    def test_sampled_policy_export_is_reproducible_and_is_the_selected_episode(self):
        env = self.make_env(max_steps=4)
        torch.set_num_threads(2)
        model = EpisodePPO("MultiInputPolicy", env, n_steps=4, batch_size=4,
                           policy_kwargs={"net_arch": dict(pi=[8], vf=[8])}, device="cpu", seed=7)
        rng_before = torch.get_rng_state().clone()
        (selected, trajectory, modes, actions), candidates = select_policy_rollout(model, env, 3)
        self.assertTrue(torch.equal(rng_before, torch.get_rng_state()))
        replay = rollout(model, env, seed=selected["seed"], deterministic=selected["deterministic"])
        self.assertEqual(replay, selected["evaluation"])
        self.assertEqual(trajectory, env.get_trajectory())
        self.assertEqual(modes, env.get_trajectory(preserve_finish=True))
        self.assertEqual(actions, env.action_history)
        self.assertEqual(len(candidates), 4)


if __name__ == "__main__":
    unittest.main()
