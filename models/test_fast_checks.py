"""Compare optimized training checks against the original validator."""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from environment import env as checks
from environment.fast_checks import PreparedTrajectoryChecks, iter_position_batches
from environment.trajectory_env import TrajectoryPPOEnv
from waam_validator.trajectory.sampling import iter_simulation_samples


ROOT = Path(__file__).resolve().parents[1]


class FastChecksTests(unittest.TestCase):
    def setUp(self):
        self.env = TrajectoryPPOEnv(ROOT / "examples/generic_jobs/box", grid_size=4, max_steps=8)
        self.addCleanup(self.env.close)

    def window(self, action):
        self.env.reset()
        return self.env._advance(*self.env._decode_action(action))

    def test_exact_sample_times_positions_and_batch_bound(self):
        rng = np.random.default_rng(18)
        config = self.env.config.model_copy(update={
            "simulation": self.env.config.simulation.model_copy(update={"batch_size": 1000})})
        for _ in range(5):
            trajectory = checks._load_trajectory(self.window(rng.uniform(-1, 1, (3, 4))))
            reference = list(iter_simulation_samples(trajectory, config))
            batches = list(iter_position_batches(trajectory, config))
            self.assertTrue(all(len(times) <= 1000 for times, _ in batches))
            np.testing.assert_array_equal(np.concatenate([times for times, _ in batches]),
                                          [sample.time_s for sample in reference])
            np.testing.assert_array_equal(np.concatenate([xyz for _, xyz in batches]),
                                          [sample.xyz_by_robot for sample in reference])

    def test_collision_flags_equal_reference_with_enabled_checks_and_touching(self):
        rng = np.random.default_rng(123)
        windows = [self.window(rng.uniform(-1, 1, (3, 4))) for _ in range(16)]
        # Include an actual crossing and a completely stationary safe trajectory.
        self.env.reset()
        xyz = self.env.state[:, 1:4].copy()
        xyz[:2] = [0, 0, 2]
        windows.append(self.window(self.env.action_from_targets(xyz, ["T", "T", "W"])))
        windows.append(self.window(np.full((3, 4), .25, dtype=np.float32)))
        trajectories = [checks._load_trajectory(window) for window in windows]
        for arm, tcp in ((True, True), (True, False), (False, True), (False, False)):
            for touching in (False, True):
                config = self.env.config.model_copy(update={
                    "collision": self.env.config.collision.model_copy(update={
                        "check_arm_envelope": arm, "check_tcp_radius": tcp,
                        "touching_is_collision": touching})})
                checker = PreparedTrajectoryChecks(config)
                with self.subTest(arm=arm, tcp=tcp, touching=touching):
                    for trajectory in trajectories:
                        expected = not checks.run_collision_analysis(trajectory, config).events
                        self.assertEqual(checker.collision_free(trajectory), expected)

    def test_process_flags_and_invalid_input_match_public_checks(self):
        rng = np.random.default_rng(99)
        for _ in range(15):
            window = self.window(rng.uniform(-1, 1, (3, 4)))
            _, process, collision = self.env._checks.evaluate(window)
            self.assertEqual(process, bool(checks.check_validation(window, job_dir=self.env.job_dir)))
            self.assertEqual(collision, bool(checks.check_collision(window, job_dir=self.env.job_dir)))
        self.assertEqual(self.env._checks.evaluate({}), (None, False, False))

    def test_touching_tcp_threshold(self):
        # Test equality, and one float32 unit on each side of the boundary.
        for distance in (np.nextafter(np.float32(40), np.float32(0)),
                         np.float32(40), np.nextafter(np.float32(40), np.float32(100))):
            window = {key: [] for key in checks.CSV_COLUMNS}
            for robot, x in ((1, 0), (2, float(distance)), (3, 1000)):
                for t in (0., .1):
                    for key, value in zip(window, (robot, t, x, 0., 2., "W")):
                        window[key].append(value)
            trajectory = checks._load_trajectory(window)
            for touching in (False, True):
                config = self.env.config.model_copy(update={
                    "collision": self.env.config.collision.model_copy(update={
                        "check_arm_envelope": False, "touching_is_collision": touching})})
                checker = PreparedTrajectoryChecks(config)
                expected = not checks.run_collision_analysis(trajectory, config).events
                self.assertEqual(checker.collision_free(trajectory), expected)
                if distance == 40:
                    self.assertEqual(expected, not touching)

    def test_step_does_not_reload_config_and_reset_reuses_empty_geometry(self):
        self.env.reset()
        with patch.object(checks, "load_config", side_effect=AssertionError("unexpected disk read")), \
             patch("environment.trajectory_env.compute_shape_metrics", side_effect=AssertionError("unexpected geometry work")):
            for _ in range(3):
                self.env.step(np.full((3, 4), .25, dtype=np.float32))
            self.env.reset()


if __name__ == "__main__":
    unittest.main()
