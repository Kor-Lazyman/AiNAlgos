from pathlib import Path
import unittest

from planning.geometry import build_plan, compile_trajectory, footprint
from environment import env as checks
from environment.fast_checks import PreparedTrajectoryChecks

ROOT = Path(__file__).resolve().parents[1]


class PlannerTests(unittest.TestCase):
    def test_actual_trajectory_matches_scored_footprint(self):
        config, sections = build_plan(ROOT / "examples/generic_jobs/box")
        data = compile_trajectory(config, sections)
        trajectory, process, collision = PreparedTrajectoryChecks(config).evaluate(data)
        self.assertTrue(process and collision)
        deposited = checks.build_deposited_layers(trajectory, config)
        for section in sections:
            expected = footprint(section.paths, config)
            self.assertLess(deposited[section.index].symmetric_difference(expected).area, 1e-4)
        modes = compile_trajectory(config, sections, True)
        self.assertIn("D", modes["mode"])
        self.assertIn("T", modes["mode"])
        for robot in (1, 2, 3):
            rows = [i for i, value in enumerate(modes["robot_id"]) if value == robot]
            self.assertEqual(modes["mode"][rows[-1]], "F")
        self.assertNotIn("F", data["mode"])
