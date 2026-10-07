import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil

import numpy as np
from shapely.geometry import box, LineString
import trimesh
from stable_baselines3.common.env_checker import check_env

from environment.residual_wrapper import ResidualStrokeEnv
from environment import env as checks
from train import policy_acceptance

ROOT = Path(__file__).resolve().parents[1]


class ResidualTests(unittest.TestCase):
    def test_mesh_pass_does_not_label_unfinished_policy_as_pass(self):
        artifact = {"validation_status": "PASS", "stl_generated": True}
        result = policy_acceptance(artifact, {"termination_reason": "max_steps", "success": False})
        self.assertEqual(result["validation_status"], "FAIL")
        self.assertEqual(result["independent_geometry_process_status"], "PASS")
        self.assertFalse(result["policy_completed"])
        self.assertEqual(artifact["validation_status"], "PASS")
        self.assertEqual(policy_acceptance(artifact, {"termination_reason": "finished", "success": True})["validation_status"], "PASS")

    def make_env(self, name="box", **kwargs):
        env = ResidualStrokeEnv(ROOT/"examples/generic_jobs"/name, grid_size=4, **kwargs)
        self.addCleanup(env.close)
        env.reset()
        return env

    def test_observation_and_geometry_hints_follow_real_deposition(self):
        env = self.make_env(max_steps=6)
        check_env(env)
        env.reset()
        initial = dict(env._focus)
        obs, reward, done, truncated, info = env.step(np.array([-.5, 0, .5, 0, -1, 0], np.float32))
        self.assertGreater(info["iou"], 0)
        self.assertFalse(done or truncated)
        self.assertTrue(env.observation_space.contains(obs))
        self.assertIn("geometry_guidance", env.action_history[-1]["stroke"])
        next_focus = env._focus
        self.assertTrue(next_focus["z"] != initial["z"] or not np.array_equal(next_focus["anchor"], initial["anchor"]))
        self.assertEqual(checks.check_validation(env.get_trajectory(), job_dir=env.job_dir), 1)

    def test_disconnected_targets_do_not_receive_gap_spanning_segments(self):
        env = self.make_env("islands", max_steps=20)
        rng = np.random.default_rng(10)
        for _ in range(12):
            action = rng.uniform(-1, 1, 6).astype(np.float32)
            action[-1] = 0
            _, _, done, truncated, info = env.step(action)
            stroke = env.action_history[-1]["stroke"]
            start, end = np.array(stroke["points_mm"])
            index = min(env.print_indices, key=lambda i: abs(env.config.process.build_plane_z_mm+(i+1)*env.config.process.layer_height_mm-start[2]))
            self.assertTrue(env._target_slices[index].covers(LineString([start[:2], end[:2]])))
        self.assertLess(info["overfill"], 1e-6)
        self.assertGreater(info["iou"], 0)

    def test_finish_is_not_inserted_at_horizon_or_by_the_hint(self):
        env = self.make_env(max_steps=2)
        a = np.array([-.5, 0, .5, 0, -1, 0], np.float32)
        env.step(a)
        _, _, done, truncated, info = env.step(a)
        self.assertFalse(done or info["success"])
        self.assertTrue(truncated)
        self.assertNotIn("F", env.get_trajectory(preserve_finish=True)["mode"])
        self.assertEqual(info["reward_terminal_adjustment"], -25)
        env.reset()
        a[-1] = 1
        _, reward, done, truncated, info = env.step(a)
        self.assertTrue(done)
        self.assertFalse(truncated or info["success"])
        self.assertEqual(reward, -1)

    def test_concave_hole_is_not_clipped_and_new_overfill_is_penalized(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            shutil.copy2(ROOT/"examples/generic_jobs/box/config.yaml", job/"config.yaml")
            polygon = box(-10, -10, 10, 10).difference(box(-3, -3, 3, 3))
            trimesh.creation.extrude_polygon(polygon, 2, engine="earcut").export(job/"target.stl")
            env = ResidualStrokeEnv(job, grid_size=4, max_steps=3)
            self.addCleanup(env.close)
            env.reset()
            env._focus["anchor"] = np.array([-5., 0.])
            _, reward, _, _, info = env.step(np.array([-.5, 0, 1, 0, -1, 0], np.float32))
            self.assertGreater(info["overfill"], 0)
            self.assertLess(env.action_history[-1]["reward_overfill"], 0)
            np.testing.assert_allclose(env.action_history[-1]["stroke"]["points_mm"][1], [3, 0, 2])

    def test_reset_restores_focus_and_diagnostics(self):
        env = self.make_env(max_steps=4)
        first, _ = env.reset(seed=1)
        env.step(np.array([-.5, 0, .5, 0, -1, 0], np.float32))
        reset, info = env.reset(seed=1)
        for key in first:
            np.testing.assert_array_equal(first[key], reset[key])
        self.assertEqual(info["duplicate_steps"], 0)
        self.assertEqual(info["episode_reward_overfill"], 0)

    def test_shape_ready_still_requires_policy_F(self):
        with TemporaryDirectory() as tmp:
            job = Path(tmp)
            shutil.copy2(ROOT/"examples/generic_jobs/box/config.yaml", job/"config.yaml")
            polygon = LineString([(-5, 0), (5, 0)]).buffer(2, quad_segs=8)
            trimesh.creation.extrude_polygon(polygon, 2, engine="earcut").export(job/"target.stl")
            env = ResidualStrokeEnv(job, grid_size=4, max_steps=4)
            self.addCleanup(env.close)
            env.reset()
            env._focus["anchor"] = np.array([0., 0.])
            a = np.array([-.625, 0, .625, 0, -1, 0], np.float32)
            obs, _, done, truncated, info = env.step(a)
            self.assertEqual(info["finish_ready"], 1)
            self.assertEqual(obs["guidance"][8], 1)
            self.assertFalse(done or truncated or info["success"])
            a[-1] = 1
            _, reward, done, truncated, info = env.step(a)
            self.assertTrue(done and info["success"])
            self.assertGreater(reward, 1.99)
            self.assertEqual(info["reward_validation_bonus"], 10)
            self.assertGreater(info["reward_makespan"], 0)
            self.assertGreater(info["terminal_mesh_iou"], .999)
            self.assertEqual(info["terminal_validation_pass"], 1)
            self.assertAlmostEqual(info["reward_terminal_adjustment"], (10+info["reward_makespan"])/env.reward_scale)


if __name__ == "__main__":
    unittest.main()
