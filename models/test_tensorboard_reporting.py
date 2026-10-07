"""Exercise real PPO logging and inspect serialized TensorBoard events."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gymnasium as gym
import numpy as np
import torch
from models.episode_ppo import EpisodePPO as PPO
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
            "reward_collision": 0. if bool(action) else -50.,
            "similarity_percent": 94., "reward_similarity": 94. if self.step_count == 2 else 0.,
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
            model.learn_episodes(total_episodes=12, callback=ValidationTensorBoardCallback(),
                        tb_log_name="test")
            model.logger.close()
            run = Path(model.logger.dir)
            train = events(run)
            self.assertIn("train/value_loss", train.Tags()["scalars"])
            self.assertEqual([e.value for e in train.Scalars("rollout/actions_collected")], [8.] * 3)
            self.assertEqual([e.step for e in train.Scalars("train/value_loss")], [4, 8, 12])
            self.assertEqual([e.value for e in train.Scalars("time/eps")], [4., 8., 12.])
            self.assertEqual(train.Scalars("time/target_eps")[-1].value, 12.)
            self.assertEqual(train.Scalars("time/action_steps")[-1].value, 24.)
            self.assertGreater(train.Scalars("time/eps_per_second")[-1].value, 0.)
            for tag in ("environment_ms_per_step", "policy_ms_per_step", "rollout_steps_per_second", "update_seconds"):
                self.assertGreater(train.Scalars(f"perf/{tag}")[-1].value, 0)
            episode = events(run / "episodes")
            self.assertEqual(len(episode.Scalars("episode/reward")), 12)
            self.assertEqual(episode.Scalars("episode/reward")[-1].step, 12)
            self.assertEqual([e.step for e in episode.Scalars("progress/eps")], list(range(1, 13)))
            self.assertEqual(episode.Scalars("episode/reward")[-1].value, 2.)
            self.assertEqual([e.value for e in episode.Scalars("reward/similarity")], [94.] * 12)
            self.assertEqual(episode.Scalars("shape/similarity_percent")[-1].step, 12)
            successes = [e.value for e in episode.Scalars("validation/environment_success")]
            self.assertEqual([e.value for e in episode.Scalars("reward/collision")],
                             [0. if success else -50. for success in successes])
            self.assertAlmostEqual(episode.Scalars("validation/environment_pass_rate_100")[-1].value,
                                   sum(successes) / 12, places=6)
            for passed in (False, True):
                write_evaluation(run, 12,
                                 {"success": passed, "coverage": .96, "overfill": .02, "iou": .94,
                                  "reward_collision": 0. if passed else -50.,
                                  "similarity_percent": 94., "reward_similarity": 94.},
                                 .98, artifact={"validation_status": "PASS" if passed else "FAIL",
                                               "stl_watertight": True,
                                               "stl_volume_relative_error": 1e-10})
            final = events(run / "evaluation")
            self.assertEqual([e.value for e in final.Scalars("independent_validation/pass")], [0., 1.])
            self.assertEqual([e.step for e in final.Scalars("independent_validation/pass")], [12, 12])
            self.assertEqual([e.value for e in final.Scalars("evaluation/reward_collision")], [-50., 0.])
            self.assertEqual([e.value for e in final.Scalars("evaluation/reward_similarity")], [94., 94.])
            env.close()

    def test_disabled_logging_and_project_version(self):
        self.assertEqual(__version__, "0.1.3")
        with TemporaryDirectory() as tmp:
            model = PPO("MlpPolicy", Monitor(ShortValidationEnv()), n_steps=8,
                        batch_size=8, n_epochs=1, tensorboard_log=None, device="cpu")
            model.learn_episodes(total_episodes=4)
            self.assertFalse(any(type(output).__name__ == "TensorBoardOutputFormat"
                                 for output in model.logger.output_formats))
            self.assertEqual(list(Path(model.logger.dir).rglob("events.out.tfevents.*")), [])
            model.logger.close()
            model.env.close()


if __name__ == "__main__":
    unittest.main()
