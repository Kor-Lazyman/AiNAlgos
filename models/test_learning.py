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
from models.reporting import TrainingReportCallback


class TrainingProbe(BaseCallback):
    def __init__(self):
        super().__init__()
        self.initial = {}
        self.rewards = []
        self.completed = []
        self.loss = None

    def _on_training_start(self):
        self.initial = {k: v.detach().clone() for k, v in self.model.policy.state_dict().items()}

    def _on_step(self):
        self.rewards.extend(self.locals["rewards"].tolist())
        for done, info in zip(self.locals["dones"], self.locals["infos"], strict=True):
            if done:
                self.completed.append(info.copy())
        return True

    def _on_training_end(self):
        self.loss = self.model.logger.name_to_value.get("train/loss")


class LearningTests(unittest.TestCase):
    def test_real_ppo_updates_save_reload_and_predict(self):
        config = replace(
            SMOKE_CONFIG, verbose=0, device="cpu", tensorboard_log=None,
            ppo=replace(SMOKE_CONFIG.ppo, lr=5e-4, eps=2e-5),
        )
        env = config.make_env()
        self.addCleanup(env.close)
        probe = TrainingProbe()
        # learn() receives the model name, existing environment and configuration.
        model = learn("PPO", env, config, callback=probe)
        self.addCleanup(model.logger.close)
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
        self.assertTrue(np.isfinite(probe.loss))
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
        config = replace(SMOKE_CONFIG, total_timesteps=16, verbose=0, check_env=False,
                         device="cpu", tensorboard_log=None)
        model = learn(config=config)
        self.addCleanup(model.get_env().close)
        self.addCleanup(model.logger.close)
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

    def test_tensorboard_records_real_training_and_every_completed_episode(self):
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

        with TemporaryDirectory(prefix="waam-tensorboard-test-") as directory:
            config = replace(SMOKE_CONFIG, verbose=0, device="cpu", check_env=False,
                             total_timesteps=32, tensorboard_log=Path(directory))
            probe = TrainingProbe()
            model = learn(config=config, callback=probe)
            try:
                events = EventAccumulator(model.logger.get_dir(), size_guidance={"scalars": 0, "tensors": 0})
                events.Reload()
                report = model.training_report
                self.assertGreater(report["episodes"], 0)
                self.assertEqual(report["episodes"], len(probe.completed))
                self.assertEqual(report["pass_count"], sum(info["success"] for info in probe.completed))
                self.assertEqual(report["fail_count"], report["episodes"] - report["pass_count"])
                self.assertEqual(len(events.Scalars("episode/success")), report["episodes"])
                texts = events.Tensors("episode/validation_result/text_summary")
                self.assertEqual(len(texts), report["episodes"])
                actual = [event.tensor_proto.string_val[0].decode() for event in texts]
                expected = ["PASS" if info["success"] else "FAIL" for info in probe.completed]
                self.assertEqual(actual, expected)
                self.assertEqual(events.Scalars("validation/episodes")[-1].value, report["episodes"])
                self.assertAlmostEqual(events.Scalars("validation/pass_rate")[-1].value, report["pass_rate"])
                losses = events.Scalars("train/loss")
                self.assertEqual(losses[-1].step, model.num_timesteps)
                self.assertTrue(np.isfinite([event.value for event in losses]).all())
                self.assertAlmostEqual(losses[-1].value, probe.loss, places=4)
                # SB3 deliberately excludes n_updates from TensorBoard.
                self.assertEqual(model._n_updates, 4)
                self.assertEqual(list(Path(directory).rglob("*.csv")), [])
                self.assertEqual(list(Path(directory).rglob("*.json")), [])
            finally:
                model.logger.close()
                model.get_env().close()

    def test_report_real_pass_fail_timeout_and_collision_reset(self):
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

        with TemporaryDirectory(prefix="waam-report-test-") as directory:
            config = replace(SMOKE_CONFIG, verbose=0, device="cpu", check_env=False,
                             tensorboard_log=Path(directory))
            env = config.make_env()
            model = build_model("ppo", env, config)
            vector_env = model.get_env()
            report = TrainingReportCallback()
            report.init_callback(model)
            report.on_training_start({}, {})
            vector_env.reset()

            def step(modes, targets=None):
                action = env.action_from_targets(env.state[:, 1:4] if targets is None else targets, modes)
                _, _, dones, infos = vector_env.step(np.asarray([action]))
                model.num_timesteps += 1
                report.update_locals({"dones": dones, "infos": infos})
                report.on_step()

            try:
                # A real valid deposition path gives PASS; no checker is mocked.
                targets = env.state[:, 1:4].copy()
                targets[0] = [-40, 0, 2]
                step(["T", "F", "F"], targets)
                self.assertEqual(report.episodes, 0)
                targets[0] = [40, 0, 2]
                step(["D", "F", "F"], targets)
                step(["F"] * 3)
                self.assertEqual(report.last_episode["result"], "PASS")
                self.assertEqual(report.last_episode["shape_pass"], 1)

                # Collision is tracked over the whole episode, then reset.
                step(["T"] * 3, [[0, 0, 2]] * 3)
                step(["F"] * 3)
                self.assertGreater(report.last_episode["collision_steps"], 0)
                step(["F"] * 3)
                self.assertEqual(report.last_episode["result"], "FAIL")
                self.assertEqual(report.last_episode["collision_steps"], 0)
                self.assertEqual(report.last_episode["trajectory_pass"], 1)
                self.assertEqual(report.last_episode["shape_pass"], 0)

                for _ in range(config.env_kwargs["max_steps"]):
                    step(["W"] * 3)
                self.assertEqual(report.last_episode["truncated"], 1)
                self.assertEqual(report.last_episode["result"], "FAIL")
                step(["W"] * 3)  # An unfinished episode must not count as FAIL.
                report.on_training_end()
                self.assertEqual(report.summary["episodes"], 4)
                self.assertEqual(report.summary["pass_count"], 1)
                self.assertEqual(report.summary["fail_count"], 3)
                self.assertEqual(report.summary["unfinished_episodes"], 1)
                self.assertEqual(report.summary["pass_rate"], 0.25)
                events = EventAccumulator(model.logger.get_dir())
                events.Reload()
                texts = events.Tensors("episode/validation_result/text_summary")
                self.assertEqual([event.tensor_proto.string_val[0].decode() for event in texts],
                                 ["PASS", "FAIL", "FAIL", "FAIL"])
            finally:
                model.logger.close()
                vector_env.close()


if __name__ == "__main__":
    unittest.main()
