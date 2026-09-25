"""Real SB3 integration tests; no mocked collision/shape/validation checks."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from models.config import SMOKE_CONFIG
from models.learn import build_model, learn, save_model


class TrainingProbe(BaseCallback):
    def __init__(self):
        super().__init__()
        self.initial = {}
        self.rewards = []
        self.completed = []

    def _on_training_start(self):
        self.initial = {k: v.detach().clone() for k, v in self.model.policy.state_dict().items()}

    def _on_step(self):
        self.rewards.extend(self.locals["rewards"].tolist())
        for done, info in zip(self.locals["dones"], self.locals["infos"], strict=True):
            if done:
                self.completed.append(info.copy())
        return True


class LearningTests(unittest.TestCase):
    def test_real_ppo_updates_save_reload_and_predict(self):
        config = replace(
            SMOKE_CONFIG, verbose=0,
            ppo=replace(SMOKE_CONFIG.ppo, lr=5e-4, eps=2e-5),
        )
        env = config.make_env()
        self.addCleanup(env.close)
        probe = TrainingProbe()
        # learn() receives the model name, existing environment and configuration.
        model = learn("PPO", env, config, callback=probe)
        self.assertEqual(model.num_timesteps, 64)
        self.assertEqual(len(probe.rewards), 64)
        self.assertTrue(np.isfinite(probe.rewards).all())
        self.assertTrue(probe.completed)
        for info in probe.completed:
            self.assertIn(info["validation_pass"], (0, 1))
            self.assertIn(info["shape_pass"], (0, 1))
            self.assertIn(info["success"], (0, 1))
            self.assertEqual(info["terminal_observation"].shape, (3, 5))
        self.assertEqual(model.learning_rate, config.ppo.lr)
        self.assertEqual(model.policy.optimizer.defaults["eps"], config.ppo.eps)
        self.assertEqual(model.batch_size, config.ppo.batch_size)
        self.assertAlmostEqual(model.clip_range(1.0), config.ppo.clip_range)
        trained = model.policy.state_dict()
        self.assertTrue(all(torch.isfinite(tensor).all() for tensor in trained.values()))
        self.assertTrue(any(not torch.equal(probe.initial[k], v) for k, v in trained.items()))
        self.assertTrue(np.isfinite(model.logger.name_to_value["train/loss"]))
        self.assertEqual(model.policy.features_extractor.features_dim, 15)

        observation, _ = env.reset(seed=42)
        action, _ = model.predict(observation, deterministic=True)
        self.assertEqual(action.shape, (3, 4))
        self.assertTrue(env.action_space.contains(action))
        with TemporaryDirectory(prefix="waam-ppo-test-") as directory:
            checkpoint = save_model(model, directory)
            self.assertEqual(list(Path(directory).iterdir()), [checkpoint])
            self.assertEqual(checkpoint.suffix, ".zip")
            loaded = PPO.load(checkpoint, device="cpu")
            restored_action, _ = loaded.predict(observation, deterministic=True)
            np.testing.assert_array_equal(action, restored_action)
            self.assertEqual(loaded.num_timesteps, 64)
            next_obs, reward, _, _, _ = env.step(restored_action)
            self.assertTrue(env.observation_space.contains(next_obs))
            self.assertTrue(np.isfinite(reward))

    def test_config_creates_environment_and_selects_model(self):
        config = replace(SMOKE_CONFIG, total_timesteps=16, verbose=0, check_env=False)
        model = learn(config=config)
        self.addCleanup(model.get_env().close)
        self.assertIsInstance(model, PPO)
        self.assertEqual(model.num_timesteps, 16)

    def test_rejects_unknown_model_and_invalid_rollout_config(self):
        env = SMOKE_CONFIG.make_env()
        self.addCleanup(env.close)
        with self.assertRaisesRegex(ValueError, "Unsupported model"):
            build_model("unknown", env, SMOKE_CONFIG)
        for override in ({"n_steps": 1}, {"batch_size": 3}, {"eps": 0}, {"lr": float("nan")}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                build_model("ppo", env, replace(SMOKE_CONFIG, ppo=replace(SMOKE_CONFIG.ppo, **override)))


if __name__ == "__main__":
    unittest.main()
