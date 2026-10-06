"""Exercise real PPO logging and inspect serialized TensorBoard events."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

from models import __version__
from models.tensorboard_reporting import ValidationTensorBoardCallback, write_evaluation


class ShortValidationEnv(gym.Env):
    observation_space = gym.spaces.Box(0, 1, shape=(1,), dtype=np.float32)
    action_space = gym.spaces.Discrete(2)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.step_count = 0
        return np.zeros(1, dtype=np.float32), {}

    def step(self, action):
        self.step_count += 1
        return np.zeros(1, dtype=np.float32), 1., self.step_count == 2, False, {
            "success": bool(action), "coverage": .96, "overfill": .02,
            "iou": .94, "makespan_weight": 0.,
        }


def events(path):
    return EventAccumulator(str(path), size_guidance={"scalars": 0}).Reload()


class TensorBoardTests(unittest.TestCase):
    def test_ppo_episode_and_final_validation_events(self):
        torch.set_num_threads(2)
        with TemporaryDirectory() as tmp:
            env = Monitor(ShortValidationEnv())
            model = PPO("MlpPolicy", env, n_steps=8, batch_size=8, n_epochs=1,
                        tensorboard_log=tmp, device="cpu", seed=17)
            model.learn(total_timesteps=24, callback=ValidationTensorBoardCallback(),
                        tb_log_name="test")
            model.logger.close()
            run = Path(model.logger.dir)
            train = events(run)
            self.assertIn("train/value_loss", train.Tags()["scalars"])
            episode = events(run / "episodes")
            self.assertEqual(len(episode.Scalars("episode/reward")), 12)
            self.assertEqual(episode.Scalars("episode/reward")[-1].step, 24)
            self.assertEqual(episode.Scalars("episode/reward")[-1].value, 2.)
            successes = [e.value for e in episode.Scalars("validation/cached_success")]
            self.assertAlmostEqual(episode.Scalars("validation/cached_pass_rate_100")[-1].value,
                                   sum(successes) / 12, places=6)
            for passed in (False, True):
                write_evaluation(run, 24 + int(passed),
                                 {"success": passed, "coverage": .96, "overfill": .02, "iou": .94},
                                 .98, artifact={"validation_status": "PASS" if passed else "FAIL",
                                               "stl_watertight": True,
                                               "stl_volume_relative_error": 1e-10})
            final = events(run / "evaluation")
            self.assertEqual([e.value for e in final.Scalars("independent_validation/pass")], [0., 1.])
            env.close()

    def test_disabled_logging_and_project_version(self):
        self.assertEqual(__version__, "1.0.0")
        with TemporaryDirectory() as tmp:
            model = PPO("MlpPolicy", Monitor(ShortValidationEnv()), n_steps=8,
                        batch_size=8, n_epochs=1, tensorboard_log=None, device="cpu")
            model.learn(total_timesteps=8)
            self.assertFalse(any(type(output).__name__ == "TensorBoardOutputFormat"
                                 for output in model.logger.output_formats))
            self.assertEqual(list(Path(model.logger.dir).rglob("events.out.tfevents.*")), [])
            model.logger.close()
            model.env.close()


if __name__ == "__main__":
    unittest.main()
