"""Direct XYZ/mode PPO control; no path templates or layer-action catalog.

The inherited motion integrator executes exactly the policy's waypoints.
Validator slicing is used only to measure deposited geometry, never to choose
actions, robot order, waypoints, or episode length.
"""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import gymnasium as gym
import numpy as np
from shapely import contains_xy, union_all

from . import env as checks
from .gym_wrapper import Mode, WaamGymEnv
from .fast_checks import PreparedTrajectoryChecks
from waam_validator.shape.metrics import compute_shape_metrics
from waam_validator.shape.polygon_utils import normalize_polygon
from waam_validator.shape.target import slice_target_mesh_at_z


class TrajectoryPPOEnv(WaamGymEnv):
    """One step is simultaneous XYZ/mode decisions for the three robots."""

    reward_scheme = "dense_iou_terminal_completion_v013"
    policy_interface = "direct_xyz_modes_v1"
    reward_scale = 1.
    process_penalty = 10.

    def __init__(self, job_dir: str | Path, *, max_steps=512, grid_size=12, collision_penalty=50.):
        if not isinstance(grid_size, int) or not 4 <= grid_size <= 32:
            raise ValueError("grid_size must be an integer between 4 and 32")
        if not math.isfinite(collision_penalty) or not 0 <= collision_penalty <= float(np.finfo(np.float32).max) / 2:
            raise ValueError("collision_penalty must be finite, non-negative and fit float32 rewards")
        super().__init__(job_dir, max_steps=max_steps, makespan_weight=0., gamma=1.)
        # This direct-control environment uses its own reward, not the legacy base reward.
        self.collision_penalty = float(collision_penalty)
        self.grid_size = grid_size
        self.mesh = checks.load_target_mesh(self.job_dir / "target.stl", self.config)
        # Only the shape evaluator needs nominal deposition slabs. Their count
        # is never exposed as a control horizon or used to generate a path.
        indices = checks.determine_evaluation_layers(self.mesh, {}, self.config)
        self._target_slices = checks.slice_target_layers(self.mesh, indices, self.config)
        if sum(p.area for p in self._target_slices.values()) <= 0:
            raise ValueError("Target has no measurable geometry under this process configuration")
        self._checks = PreparedTrajectoryChecks(self.config)
        self._empty_metrics, _ = compute_shape_metrics({}, self._target_slices, self.config)
        # A relative margin keeps thin parts visible even at low resolutions.
        pad = np.maximum(self.mesh.bounds[1] - self.mesh.bounds[0], 1e-6) * .05
        self.grid_low = self.mesh.bounds[0] - pad
        self.grid_high = self.mesh.bounds[1] + pad
        axes = [np.linspace(lo, hi, grid_size, endpoint=False) + (hi - lo) / (2 * grid_size)
                for lo, hi in zip(self.grid_low, self.grid_high, strict=True)]
        self._grid_x, self._grid_y = np.meshgrid(axes[0], axes[1], indexing="ij")
        self._grid_z = axes[2]
        self._target_grid = np.zeros((grid_size,) * 3, dtype=np.float32)
        for index, z in enumerate(self._grid_z):
            polygon = slice_target_mesh_at_z(self.mesh, float(z),
                                            self.config.shape_validation.polygon_snap_tolerance_mm)
            self._target_grid[:, :, index] = contains_xy(polygon, self._grid_x, self._grid_y)
        self.observation_space = gym.spaces.Dict({
            "robots": gym.spaces.Box(0., 1., (15,), dtype=np.float32),
            "target": gym.spaces.Box(0., 1., (grid_size ** 3,), dtype=np.float32),
            "deposited": gym.spaces.Box(0., 1., (grid_size ** 3,), dtype=np.float32),
            "context": gym.spaces.Box(-np.inf, np.inf, (10,), dtype=np.float32),
            "progress": gym.spaces.Box(0., 1., (6,), dtype=np.float32),
        })

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed, options=options)
        self._deposited = {}
        self._deposited_grid = np.zeros_like(self._target_grid)
        self._metrics = replace(self._empty_metrics)
        self._reward_similarity = 0.
        self._previous_iou = 0.
        self._episode_reward_shape = 0.
        self._episode_reward_process = 0.
        self._reward_incomplete = 0.
        self._reward_terminal_adjustment = 0.
        self._process_pass = True
        self._reward_collision = 0.
        self._episode_reward_collision = 0.
        self.action_history = []
        return self._observation(), self._info(success=False, reason="running")

    def _observation(self):
        span = self.xyz_high - self.xyz_low
        robots = self.state.astype(np.float64)
        robots[:, 0] /= self.max_makespan_s
        robots[:, 1:4] = (robots[:, 1:4] - self.xyz_low) / span
        robots[:, 4] /= 3.
        process = self.config.process
        context = np.concatenate([
            (self.grid_low - self.xyz_low) / span,
            (self.grid_high - self.xyz_low) / span,
            [process.bead_width_mm / span[0], process.bead_width_mm / span[1],
             process.layer_height_mm / span[2],
             (process.build_plane_z_mm - self.xyz_low[2]) / span[2]],
        ]).astype(np.float32)
        obs = {
            "robots": np.clip(robots.ravel(), 0., 1.).astype(np.float32),
            "target": self._target_grid.ravel().copy(),
            "deposited": self._deposited_grid.ravel().copy(),
            "context": context,
            "progress": np.clip(np.asarray([
                self._step_count / self.max_steps, self._metrics.coverage,
                self._metrics.overfill_ratio / (1 + self._metrics.overfill_ratio),
                self._metrics.iou, float(self._collision_steps == 0), float(self._process_pass),
            ], dtype=np.float32), 0., 1.),
        }
        if not all(np.isfinite(value).all() for value in obs.values()):
            raise ValueError("Non-finite trajectory observation")
        return obs

    def _update_geometry(self, trajectories):
        additions = checks.build_deposited_layers(trajectories, self.config)
        if not additions:
            return
        for index, polygon in additions.items():
            previous = self._deposited.get(index)
            self._deposited[index] = normalize_polygon(
                polygon if previous is None else union_all([previous, polygon]),
                self.config.shape_validation.polygon_snap_tolerance_mm,
                self.config.shape_validation.area_epsilon_mm2)
        self._metrics, _ = compute_shape_metrics(self._deposited, self._target_slices, self.config)
        process = self.config.process
        for z_index, z in enumerate(self._grid_z):
            index = math.floor((z - process.build_plane_z_mm) / process.layer_height_mm)
            polygon = self._deposited.get(index)
            if polygon is not None:
                self._deposited_grid[:, :, z_index] = contains_xy(polygon, self._grid_x, self._grid_y)

    def _info(self, *, success, reason):
        return {"success": bool(success), "coverage": float(self._metrics.coverage),
                "overfill": float(self._metrics.overfill_ratio), "iou": float(self._metrics.iou),
                "similarity_percent": float(self._metrics.iou) * 100.,
                "reward_similarity": self._reward_similarity,
                "episode_reward_shape": self._episode_reward_shape,
                "episode_reward_process": self._episode_reward_process,
                "reward_incomplete": self._reward_incomplete,
                "reward_terminal_adjustment": self._reward_terminal_adjustment,
                "makespan_weight": 0., "makespan_s": self._time, "action_count": self._step_count,
                "validation_pass": int(self._process_pass),
                "collision_pass": int(self._collision_steps == 0),
                "reward_collision": self._reward_collision,
                "episode_reward_collision": self._episode_reward_collision,
                "collision_steps": self._collision_steps,
                "collision_penalty": self.collision_penalty,
                "shape_pass": int(self._metrics.passed), "termination_reason": reason,
                "finished": tuple(int(row[4]) == Mode.F for row in self._state)}

    def _execute_action(self, action):
        targets, modes = self._decode_action(action)
        return targets, modes, self._advance(targets, modes)

    def _terminal_adjustment(self, ended, success):
        return 0.

    def step(self, action):
        if self._closed or self._needs_reset:
            raise gym.error.ResetNeeded("Call reset before stepping")
        targets, requested_modes, window = self._execute_action(action)
        self._step_count += 1
        trajectories, process_pass, collision_pass = self._checks.evaluate(window)
        self._process_pass &= process_pass
        self._collision_steps += int(not collision_pass)
        # Invalid D moves remain invalid moves in the recorded trajectory.
        # Never snap heights, replace modes, or substitute a planned path.
        if process_pass:
            self._update_geometry(trajectories)
        all_finished = all(int(row[4]) == Mode.F for row in self._state)
        terminated = bool(all_finished)
        truncated = bool(self._step_count >= self.max_steps and not terminated)
        self._needs_reset = terminated or truncated
        reason = "finished" if all_finished else "max_steps" if truncated else "running"
        success = bool(all_finished and self._process_pass and self._collision_steps == 0
                       and self._metrics.passed)
        # Penalize each colliding action, continue until all F, and retain failure history.
        self._reward_collision = -self.collision_penalty if not collision_pass else 0.
        self._episode_reward_collision += self._reward_collision
        # Dense geometry feedback helps distinguish actual deposition from waiting.
        shape_reward = 100. * (float(self._metrics.iou) - self._previous_iou)
        self._previous_iou = float(self._metrics.iou)
        self._episode_reward_shape += shape_reward
        process_reward = 0. if process_pass else -self.process_penalty
        self._episode_reward_process += process_reward
        # Partial similarity is still rewarded, but finishing an empty object is not neutral.
        self._reward_similarity = float(self._metrics.iou) * 100. if terminated or truncated else 0.
        self._reward_incomplete = -100. * (1-float(self._metrics.iou)) if terminated or truncated else 0.
        terminal_adjustment = self._terminal_adjustment(terminated or truncated, success)
        self._reward_terminal_adjustment = terminal_adjustment
        raw_reward = shape_reward + self._reward_similarity + self._reward_incomplete + process_reward + self._reward_collision + terminal_adjustment
        reward = raw_reward * self.reward_scale
        self.action_history.append({
            "step": self._step_count, "policy_action": np.asarray(action).tolist(),
            "requested_xyz_mm": targets, "requested_modes": [m.name for m in requested_modes],
            "executed_xyz_mm": [row[1:4] for row in self._state],
            "executed_modes": [Mode(int(row[4])).name for row in self._state],
            "time_s": self._time, "termination_reason": reason,
            "reward": float(reward), "reward_collision": self._reward_collision,
            "raw_reward": float(raw_reward), "reward_scale": self.reward_scale,
            "reward_terminal_adjustment": terminal_adjustment,
            "reward_similarity": self._reward_similarity,
            "reward_shape": shape_reward, "reward_process": process_reward,
            "reward_incomplete": self._reward_incomplete,
            "validation_pass": process_pass, "collision_pass": collision_pass,
        })
        return self._observation(), float(reward), terminated, truncated, self._info(success=success, reason=reason)

    def get_trajectory(self, *, preserve_finish=False):
        if not preserve_finish:
            return super().get_trajectory()
        result = {column: [] for column in checks.CSV_COLUMNS}
        for robot, rows in enumerate(self._history, 1):
            for row in rows:
                for key, value in zip(result, [robot, *row], strict=True):
                    result[key].append(value)
        return result
