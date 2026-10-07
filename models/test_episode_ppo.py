"""Episode budgets, complete MC returns, LR and logging semantics."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from models.episode_ppo import EpisodePPO, LinearLearningRate
from tests.helpers import EpisodeEnv


class Capture(BaseCallback):
    def __init__(self):
        super().__init__()
        self.batches = []

    def _on_step(self):
        return True

    def _on_rollout_end(self):
        buffer = self.model.rollout_buffer
        self.batches.append((buffer.buffer_size, buffer.returns.copy()))


class OneActionEpisode(gym.Env):
    observation_space = gym.spaces.Box(0, 1, (1,), dtype=np.float32)
    action_space = gym.spaces.Discrete(2)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return np.zeros(1, dtype=np.float32), {}

    def step(self, action):
        return np.zeros(1, dtype=np.float32), float(action), True, False, {}


class EpisodePPOTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def test_exact_episode_limit_updates_final_single_transition_and_logs_episode_axis(self):
        with TemporaryDirectory() as directory:
            model = EpisodePPO("MlpPolicy", Monitor(EpisodeEnv()), n_steps=4, batch_size=4, n_epochs=1,
                               learning_rate=LinearLearningRate(), tensorboard_log=directory, device="cpu", seed=4)
            capture = Capture()
            model.learn_episodes(3, callback=capture)
            self.assertEqual(model.completed_episodes, 3)
            self.assertEqual(model.num_timesteps, 9)
            self.assertEqual([n for n, _ in capture.batches], [6, 3])
            self.assertEqual(model._n_updates, 2)
            self.assertAlmostEqual(model.policy.optimizer.param_groups[0]["lr"], 1e-5)
            self.assertTrue(all(torch.isfinite(p).all() for p in model.policy.parameters()))
            model.logger.close()
            events = EventAccumulator(model.logger.dir, size_guidance={"scalars": 0}).Reload()
            self.assertEqual([e.step for e in events.Scalars("train/learning_rate")], [2, 3])
            np.testing.assert_allclose([e.value for e in events.Scalars("train/learning_rate")],
                                       [0.0010066666666666667, 1e-5])
            path = Path(directory) / "episode.zip"
            model.save(path)
            loaded = EpisodePPO.load(path, device="cpu")
            self.assertEqual(loaded.completed_episodes, 3)
            self.assertEqual(loaded.trained_advantage_estimator, "monte_carlo")
            self.assertAlmostEqual(loaded.lr_schedule(0.5), 0.001505)
            model.get_env().close()

    def test_mc_finishes_episode_without_bootstrap(self):
        for truncated in (False, True):
            with self.subTest(truncated=truncated):
                model = EpisodePPO("MlpPolicy", EpisodeEnv(truncated=truncated), n_steps=2, batch_size=2,
                                   n_epochs=1, learning_rate=0., gamma=.9, gae_lambda=.8, device="cpu")
                with torch.no_grad():
                    model.policy.value_net.weight.zero_()
                    model.policy.value_net.bias.fill_(7)
                capture = Capture()
                model.learn_episodes(1, callback=capture)
                self.assertEqual(len(capture.batches), 1)
                np.testing.assert_allclose(capture.batches[0][1][:, 0], [5.23, 4.7, 3.], atol=1e-5)
                self.assertEqual(model.truncated_episodes, int(truncated))
                self.assertEqual(model.finished_episodes, int(not truncated))
                model.get_env().close()

    def test_exact_ten_thousand_completed_episodes(self):
        model = EpisodePPO("MlpPolicy", OneActionEpisode(), n_steps=256, batch_size=256, n_epochs=1,
                           policy_kwargs={"net_arch": dict(pi=[8], vf=[8])}, device="cpu", seed=5)
        model.learn_episodes(10000)
        self.assertEqual(model.completed_episodes, 10000)
        self.assertEqual(model.num_timesteps, 10000)
        self.assertEqual(model._n_updates, 40)
        self.assertEqual(model.rollout_buffer.buffer_size, 16)
        model.get_env().close()


if __name__ == "__main__":
    unittest.main()
