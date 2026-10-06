"""Acceptance tests on exported PPO artifacts, including deliberate bad trajectories.

Run after models.sphere_ppo. These checks intentionally require real artifacts.
"""
import csv
import json
from pathlib import Path
import unittest

import numpy as np
import trimesh

from environment import env as checks

OUTPUT = Path(__file__).resolve().parents[1] / "outputs/sphere_r-24mm_ppo"
JOB = OUTPUT / "job"


def read_trajectory(path):
    with path.open(encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    return {key: [row[key] for row in records] for key in checks.CSV_COLUMNS}


class SphereAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_trajectory(JOB / "trajectory.csv")

    def test_full_export_passes_all_three_checks(self):
        self.assertEqual(checks.check_validation(self.data, job_dir=JOB), 1)
        self.assertEqual(checks.check_collision(self.data, job_dir=JOB), 1)
        self.assertEqual(checks.check_shape(self.data, job_dir=JOB), 1)

    def test_removing_deposition_fails_shape(self):
        data = {key: list(value) for key, value in self.data.items()}
        data["mode"] = ["T" if mode == "D" else mode for mode in data["mode"]]
        self.assertEqual(checks.check_shape(data, job_dir=JOB), 0)

    def test_wrong_deposition_height_fails_process(self):
        data = {key: list(value) for key, value in self.data.items()}
        index = data["mode"].index("D")
        data["z_mm"][index] = float(data["z_mm"][index]) + 1.0
        self.assertEqual(checks.check_validation(data, job_dir=JOB), 0)

    def test_collision_is_not_hidden(self):
        data = {key: list(value) for key, value in self.data.items()}
        for i, robot in enumerate(data["robot_id"]):
            if int(robot) in (2, 3):
                data["x_mm"][i], data["y_mm"][i], data["z_mm"][i] = 0., 0., 1000.
        self.assertEqual(checks.check_collision(data, job_dir=JOB), 0)

    def test_all_robots_deposit_and_finish(self):
        modes = read_trajectory(OUTPUT / "trajectory_robot_modes.csv")
        for robot in ("1", "2", "3"):
            robot_modes = [m for r, m in zip(modes["robot_id"], modes["mode"]) if r == robot]
            self.assertTrue({"T", "D", "W"}.issubset(robot_modes))
            self.assertEqual(robot_modes[-1], "F")

    def test_stl_is_actual_deposition(self):
        config = checks.load_config(JOB / "config.yaml")
        layers = checks.build_deposited_layers(checks._load_trajectory(self.data), config)
        expected_volume = sum(p.area for p in layers.values()) * config.process.layer_height_mm
        mesh = trimesh.load(OUTPUT / "deposited_sphere.stl")
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(np.isfinite(mesh.vertices).all())
        self.assertAlmostEqual(mesh.volume / expected_volume, 1., places=5)

    def test_real_ppo_training_and_independent_pass(self):
        summary = json.loads((OUTPUT / "training_summary.json").read_text())
        independent = json.loads((OUTPUT / "validation/summary.json").read_text())
        self.assertGreater(summary["training_timesteps"], 0)
        self.assertGreater(summary["parameter_change_l2"], 0)
        self.assertTrue(summary["deterministic_evaluation"]["success"])
        self.assertEqual(independent["status"], "PASS")
        self.assertAlmostEqual(summary["deterministic_evaluation"]["coverage"],
                               independent["shape"]["coverage"], places=5)


if __name__ == "__main__":
    unittest.main()
