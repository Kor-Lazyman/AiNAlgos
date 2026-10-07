"""Device selection and actual CUDA PPO training/save/reload."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import torch
from models.episode_ppo import EpisodePPO as PPO
from stable_baselines3.common.monitor import Monitor

from environment.trajectory_env import TrajectoryPPOEnv
from train import resolve_device

ROOT = Path(__file__).resolve().parents[1]


class DeviceTests(unittest.TestCase):
    def test_selection_and_explicit_cuda_failure(self):
        with patch("torch.cuda.is_available", return_value=True):
            self.assertEqual(resolve_device("auto"), "cuda")
            self.assertEqual(resolve_device("cuda"), "cuda")
            self.assertEqual(resolve_device("cpu"), "cpu")
        with patch("torch.cuda.is_available", return_value=False):
            self.assertEqual(resolve_device("auto"), "cpu")
            with self.assertRaisesRegex(ValueError, "CUDA is unavailable"):
                resolve_device("cuda")

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is unavailable")
    def test_real_cuda_policy_update_and_reload(self):
        torch.set_num_threads(2)
        env = Monitor(TrajectoryPPOEnv(ROOT / "examples/generic_jobs/box", grid_size=4, max_steps=4))
        try:
            model = PPO("MultiInputPolicy", env, n_steps=8, batch_size=8, n_epochs=1,
                        policy_kwargs={"net_arch": dict(pi=[16], vf=[16])}, device="cuda", seed=42)
            self.assertEqual(model.device.type, "cuda")
            before = [p.detach().clone() for p in model.policy.parameters()]
            model.learn_episodes(total_episodes=4)
            self.assertEqual(model.completed_episodes, 4)
            torch.cuda.synchronize()
            self.assertTrue(all(p.device.type == "cuda" for p in model.policy.parameters()))
            self.assertTrue(any(not torch.equal(a, b) for a, b in zip(before, model.policy.parameters())))
            with TemporaryDirectory() as directory:
                path = Path(directory) / "gpu_ppo.zip"
                model.save(path)
                loaded = PPO.load(path, device="cuda")
                obs, _ = env.reset(seed=42)
                expected, _ = model.predict(obs, deterministic=True)
                actual, _ = loaded.predict(obs, deterministic=True)
                self.assertEqual(loaded.device.type, "cuda")
                np.testing.assert_allclose(actual, expected, atol=1e-6)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
