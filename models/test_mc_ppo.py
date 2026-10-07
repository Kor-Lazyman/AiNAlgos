"""Check episodic MC targets independently of the PPO optimizer."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv

from models.mc_ppo import MonteCarloRolloutBuffer


class MonteCarloTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def test_exact_returns_episode_boundaries_and_value_baseline(self):
        for gamma, expected in ((1.0, [6, 5, 3, 9, 5]), (0.5, [2.75, 3.5, 3, 6.5, 5])):
            with self.subTest(gamma=gamma):
                space = gym.spaces.Box(-1, 1, (1,), dtype=np.float32)
                buffer = MonteCarloRolloutBuffer(2, space, space, gamma=gamma, device="cpu")
                values = [10, 20, 30, 40, 50]
                for i, (reward, value) in enumerate(zip([1, 2, 3, 4, 5], values)):
                    buffer.add(np.array([[0]]), np.array([[0]]), np.array([reward]),
                               np.array([i in (0, 3)]), torch.tensor([value]), torch.tensor([0.0]))
                buffer.compute_returns_and_advantage(torch.tensor([9999.0]), np.array([True]))
                self.assertEqual(buffer.buffer_size, 5)
                self.assertTrue(buffer.full)
                np.testing.assert_allclose(buffer.returns[:, 0], expected)
                np.testing.assert_allclose(buffer.advantages[:, 0], np.array(expected) - values)
                self.assertEqual(sum(len(batch.returns) for batch in buffer.get(2)), 5)

    def test_reject_incomplete_episode(self):
        space = gym.spaces.Box(-1, 1, (1,), dtype=np.float32)
        buffer = MonteCarloRolloutBuffer(2, space, space, device="cpu")
        buffer.add(np.array([[0]]), np.array([[0]]), np.array([1]), np.array([True]),
                   torch.tensor([0.0]), torch.tensor([0.0]))
        with self.assertRaisesRegex(ValueError, "complete episodes"):
            buffer.compute_returns_and_advantage(torch.tensor([10.0]), np.array([False]))


if __name__ == "__main__":
    unittest.main()
