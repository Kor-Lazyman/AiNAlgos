"""Prepared in-memory checks for training, using the validator's exact rules.

Collision checks use the same adaptive sample times, float32 positions and
geometry primitives as the report generator. Only boolean results are needed,
so sample interpolation is batched and collision event reports are not built.
"""
import math

import numpy as np

from . import env as checks  # Select the checkout's validator backend first.
from waam_validator.collision.geometry2d import check_arm_envelope_xy_batch
from waam_validator.constants import ROBOT_PAIRS
from waam_validator.trajectory.interpolation import interpolate_all_states


def _positions_at(trajectories, times):
    positions = np.empty((len(times), 3, 3), dtype=np.float32)
    for robot, trajectory in enumerate(trajectories.robots):
        indices = np.searchsorted(trajectory.time_s, times, side="right") - 1
        indices = np.clip(indices, 0, len(trajectory.time_s) - 2)
        start = trajectory.time_s[indices]
        end = trajectory.time_s[indices + 1]
        alpha = (times - start) / (end - start)
        xyz_start = trajectory.xyz_mm[indices].astype(np.float64)
        xyz_end = trajectory.xyz_mm[indices + 1].astype(np.float64)
        positions[:, robot] = xyz_start + alpha[:, None] * (xyz_end - xyz_start)
        positions[times >= trajectory.time_s[-1], robot] = trajectory.xyz_mm[-1]
    return positions


def iter_position_batches(trajectories, config):
    """Match iter_simulation_samples without one Python call per sample."""
    breakpoints = np.unique(np.concatenate([item.time_s for item in trajectories.robots]))
    batch_size = config.simulation.batch_size
    for left, right in zip(breakpoints[:-1], breakpoints[1:], strict=True):
        left, right = float(left), float(right)
        xyz_left, _ = interpolate_all_states(trajectories, left)
        xyz_right, _ = interpolate_all_states(trajectories, right)
        duration = right - left
        displacement = np.linalg.norm(xyz_right.astype(np.float64) - xyz_left.astype(np.float64), axis=1)
        subdivisions = max(1, math.ceil(duration / config.simulation.max_time_step_s),
                           int(np.max(np.ceil(displacement / config.simulation.max_tcp_step_mm))))
        for start in range(0, subdivisions, batch_size):
            offsets = np.arange(start, min(start + batch_size, subdivisions), dtype=np.float64)
            times = left + duration * offsets / subdivisions
            yield times, _positions_at(trajectories, times)
    times = np.array([breakpoints[-1]], dtype=np.float64)
    yield times, _positions_at(trajectories, times)


class PreparedTrajectoryChecks:
    """An environment's config is fixed for its lifetime; no per-step disk I/O."""

    def __init__(self, config):
        self.config = config
        self.robots = {robot.id: robot for robot in config.robots}
        self.bases = {robot.id: np.asarray(robot.base_xyz_mm[:2], dtype=np.float64)
                      for robot in config.robots}

    def collision_free(self, trajectories):
        config = self.config
        collision = config.collision
        if not collision.check_tcp_radius and not collision.check_arm_envelope:
            return True
        for _, xyz in iter_position_batches(trajectories, config):
            # The original simulator also converts float32 interpolated XYZ to float64.
            positions = xyz[:, :, :2].astype(np.float64)
            for robot_a, robot_b in ROBOT_PAIRS:
                a, b = positions[:, robot_a - 1], positions[:, robot_b - 1]
                if collision.check_tcp_radius:
                    distance = np.hypot(a[:, 0] - b[:, 0], a[:, 1] - b[:, 1])
                    required = self.robots[robot_a].tcp_radius_mm + self.robots[robot_b].tcp_radius_mm
                    collided = distance <= required if collision.touching_is_collision else distance < required
                    if np.any(collided):
                        return False
                if collision.check_arm_envelope:
                    result = check_arm_envelope_xy_batch(
                        self.bases[robot_a], a, self.robots[robot_a].arm_envelope_radius_mm,
                        self.bases[robot_b], b, self.robots[robot_b].arm_envelope_radius_mm,
                        collision.arm_clearance_mm, collision.geometry_epsilon_mm,
                        collision.touching_is_collision)
                    if np.any(result.collision):
                        return False
        return True

    def evaluate(self, window):
        errors = (checks.WaamValidatorError, OSError, ValueError, TypeError, OverflowError)
        try:
            trajectories = checks._load_trajectory(window)
        except errors:
            return None, False, False
        try:
            process_pass = not checks.validate_trajectory_set(trajectories, self.config).violations
        except errors:
            process_pass = False
        try:
            collision_pass = self.collision_free(trajectories)
        except errors:
            collision_pass = False
        return trajectories, bool(process_pass), bool(collision_pass)
