"""Gymnasium/SB3 interface for three-robot WAAM control, entirely in memory.

Observation: float32 (3, 5), one [now_s, x_mm, y_mm, z_mm, mode] per robot.
Action: float32 (3, 4) in [-1, 1], one [target_x, target_y, target_z, mode]
per robot. XYZ maps to absolute world coordinates inside xyz_bounds. Mode
bins are T, D, W, F, in that order; action_from_targets encodes physical inputs.

F is irreversible and observable. It maps to W only in get_trajectory() and
checker inputs. Nothing writes CSV, JSON, reports, or logs. See gym_wrapper.md.
"""

from __future__ import annotations

import math
from enum import IntEnum
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from . import env as checks


class Mode(IntEnum):
    """Observation mode codes; T/D/W agree with the validator's codes."""

    T = 0
    D = 1
    W = 2
    F = 3


class WaamGymEnv(gym.Env[np.ndarray, np.ndarray]):
    """Simultaneous robot actions with a barrier at the end of each step.

    T/D duration is distance / configured speed. W/F ignore target coordinates.
    Faster robots wait after arriving until the slowest robot has arrived.
    Finished robots remain stationary, participate in collision checks, and
    keep mode F in the observation while their 'now' clock continues advancing.

    Reward = -makespan_weight * elapsed_s - collision_penalty * collision
    plus a terminal reward/penalty only on the last step. Terminal success
    requires all robots finished AND check_validation AND check_shape passing.
    Collision is a separate per-step penalty; it is not silently folded into
    the terminal validity/shape result. Time-limit truncation always receives
    the terminal penalty, even if the partial trajectory passes both checks.

    The requested 15-value observation does not encode the deposited geometry
    or full history; this is a partially observed task. Coordinates and times
    in observations are physical units, while actions are normalized for PPO.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        job_dir: str | Path = checks.DEFAULT_JOB_DIR,
        *,
        max_steps: int = 256,
        wait_time_s: float = 0.1,
        makespan_weight: float = 0.01,
        collision_penalty: float = 1.0,
        terminal_reward: float = 10.0,
        terminal_penalty: float = 10.0,
        xyz_bounds: tuple[Any, Any] | None = None,
        render_mode: None = None,
    ) -> None:
        super().__init__()
        if render_mode is not None:
            raise ValueError("This environment does not provide rendering")
        if isinstance(max_steps, bool) or not isinstance(max_steps, (int, np.integer)):
            raise ValueError("max_steps must be a positive integer")
        if max_steps < 1 or not math.isfinite(wait_time_s) or wait_time_s <= 0:
            raise ValueError("max_steps and wait_time_s must be positive")
        weights = (makespan_weight, collision_penalty, terminal_reward, terminal_penalty)
        if any(not math.isfinite(value) or value < 0 for value in weights):
            raise ValueError("Reward weights must be finite and non-negative")
        self.job_dir = Path(job_dir).expanduser().resolve()
        self.config = checks.load_config(self.job_dir / "config.yaml")
        mesh = checks.load_target_mesh(self.job_dir / "target.stl", self.config)
        self.max_steps = int(max_steps)
        self.wait_time_s = float(wait_time_s)
        self.makespan_weight = float(makespan_weight)
        self.collision_penalty = float(collision_penalty)
        self.terminal_reward = float(terminal_reward)
        self.terminal_penalty = float(terminal_penalty)
        self.render_mode = render_mode
        robots = sorted(self.config.robots, key=lambda robot: robot.id)
        self._homes = [list(robot.home_xyz_mm or robot.base_xyz_mm) for robot in robots]

        if xyz_bounds is None:
            cx, cy = self.config.workspace.center_xy_mm
            radius = self.config.workspace.radius_mm
            z0 = self.config.process.build_plane_z_mm
            z1 = z0 + self.config.process.layer_height_mm
            points = np.asarray([
                *self._homes, *mesh.bounds.tolist(),
                [cx - radius, cy - radius, z0], [cx + radius, cy + radius, z1],
            ], dtype=np.float64)
            bounds = np.stack((points.min(axis=0), points.max(axis=0)))
        else:
            bounds = np.asarray(xyz_bounds, dtype=np.float64)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
            raise ValueError("xyz_bounds must contain finite lower/upper XYZ coordinates")
        self.xyz_low, self.xyz_high = bounds[0].copy(), bounds[1].copy()
        if np.any(self.xyz_low >= self.xyz_high):
            raise ValueError("Each lower XYZ bound must be smaller than its upper bound")
        homes = np.asarray(self._homes)
        if np.any(homes < self.xyz_low) or np.any(homes > self.xyz_high):
            raise ValueError("xyz_bounds must include every robot's initial position")

        slowest_speed = min(
            self.config.process.deposition_speed_mm_s, self.config.process.travel_speed_mm_s
        )
        longest_step = max(self.wait_time_s, math.dist(self.xyz_low, self.xyz_high) / slowest_speed)
        max_time = self.max_steps * longest_step
        low = np.asarray([0.0, *self.xyz_low, 0.0], dtype=np.float64)
        high = np.asarray([max_time, *self.xyz_high, float(Mode.F)], dtype=np.float64)
        if not np.isfinite(high).all() or np.max(np.abs([low, high])) > np.finfo(np.float32).max:
            raise ValueError("Bounds/horizon exceed the finite float32 observation range")
        self.observation_space = spaces.Box(
            np.tile(low, (3, 1)).astype(np.float32),
            np.tile(high, (3, 1)).astype(np.float32),
            dtype=np.float32,
        )
        self.action_space = spaces.Box(-1.0, 1.0, shape=(3, 4), dtype=np.float32)
        self._state: list[list[float]] = []
        self._history: list[list[list[Any]]] = []
        self._time = 0.0
        self._step_count = 0
        self._needs_reset = True
        self._closed = False

    @property
    def state(self) -> np.ndarray:
        """Return a detached copy of the three [time, x, y, z, mode] rows."""
        if not self._state:
            raise gym.error.ResetNeeded("Call reset() first")
        return np.asarray(self._state, dtype=np.float32).copy()

    def action_from_targets(self, xyz: Any, modes: Any) -> np.ndarray:
        """Encode (3,3) absolute XYZ targets and three T/D/W/F names or Mode values."""
        targets = np.asarray(xyz, dtype=np.float64)
        if targets.shape != (3, 3) or not np.isfinite(targets).all():
            raise ValueError("xyz must be finite and have shape (3, 3)")
        if np.any(targets < self.xyz_low) or np.any(targets > self.xyz_high):
            raise ValueError("Targets must lie inside xyz_bounds")
        values = list(modes)
        if len(values) != 3:
            raise ValueError("Provide exactly three modes")
        try:
            codes = [Mode[value] if isinstance(value, str) else Mode(value) for value in values]
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("Modes must be T, D, W, F or their integer codes") from exc
        action = np.empty((3, 4), dtype=np.float32)
        action[:, :3] = 2.0 * (targets - self.xyz_low) / (self.xyz_high - self.xyz_low) - 1.0
        action[:, 3] = [-0.75 + 0.5 * int(mode) for mode in codes]
        return action

    def _decode_action(self, action: Any) -> tuple[list[list[float]], list[Mode]]:
        values = np.asarray(action, dtype=np.float64)
        if values.shape != (3, 4) or not np.isfinite(values).all():
            raise ValueError("Action must be finite and have shape (3, 4)")
        if np.any(values < -1.0) or np.any(values > 1.0):
            raise ValueError("Action values must be inside [-1, 1]")
        xyz = self.xyz_low + (values[:, :3] + 1.0) * 0.5 * (self.xyz_high - self.xyz_low)
        modes = [Mode(min(3, math.floor((value + 1.0) * 2.0))) for value in values[:, 3]]
        return xyz.tolist(), modes

    @staticmethod
    def _trajectory_dict(
        robot_rows: list[list[list[Any]]], time_origin: float = 0.0,
    ) -> dict[str, list[Any]]:
        result: dict[str, list[Any]] = {column: [] for column in checks.CSV_COLUMNS}
        for robot_id, rows in enumerate(robot_rows, start=1):
            for time_s, x, y, z, mode in rows:
                output_mode = "W" if mode == "F" else mode
                values = (robot_id, time_s - time_origin, x, y, z, output_mode)
                for column, value in zip(checks.CSV_COLUMNS, values, strict=True):
                    result[column].append(value)
        return result

    def get_trajectory(self) -> dict[str, list[Any]]:
        """Return accumulated checker-ready columns with F mapped to W; no files."""
        if not self._state:
            raise gym.error.ResetNeeded("Call reset() first")
        return self._trajectory_dict(self._history)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if self._closed:
            raise RuntimeError("Cannot reset a closed environment")
        super().reset(seed=seed)
        del options
        self._time = 0.0
        self._step_count = 0
        self._needs_reset = False
        self._state = [[0.0, *home, float(Mode.W)] for home in self._homes]
        self._history = [[[0.0, *home, "W"]] for home in self._homes]
        return self.state, {"makespan_s": 0.0, "finished": (False, False, False)}

    def _advance(
        self, targets: list[list[float]], modes: list[Mode],
    ) -> dict[str, list[Any]]:
        """Append simultaneous moves and waiting tails, returning only this time window."""
        start_time = self._time
        plans = []
        for state, target, requested_mode in zip(self._state, targets, modes, strict=True):
            start = state[1:4]
            mode = Mode.F if int(state[4]) == Mode.F else requested_mode
            if mode in (Mode.W, Mode.F):
                end = start.copy()
                duration = self.wait_time_s
            else:
                end = list(target)
                speed = (
                    self.config.process.deposition_speed_mm_s if mode == Mode.D
                    else self.config.process.travel_speed_mm_s
                )
                distance = math.dist(start, end)
                duration = distance / speed if distance > 0.0 else self.wait_time_s
            plans.append((start, end, mode, duration))
        elapsed = max(self.wait_time_s, *(plan[3] for plan in plans))
        end_time = start_time + elapsed
        window = []
        for index, (start, end, mode, duration) in enumerate(plans):
            if mode in (Mode.W, Mode.F):
                rows = [[start_time, *start, mode.name], [end_time, *end, mode.name]]
            else:
                arrival = start_time + duration
                rows = [[start_time, *start, mode.name], [arrival, *end, "W"]]
                if arrival < end_time:
                    rows.append([end_time, *end, "W"])
            self._history[index][-1][4] = rows[0][4]
            self._history[index].extend([row.copy() for row in rows[1:]])
            self._state[index] = [end_time, *end, float(mode)]
            window.append(rows)
        self._time = end_time
        return self._trajectory_dict(window, time_origin=start_time)

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._closed or self._needs_reset:
            raise gym.error.ResetNeeded("Call reset() before stepping a new episode")
        targets, modes = self._decode_action(action)
        previous_time = self._time
        window = self._advance(targets, modes)
        self._step_count += 1
        finished = tuple(int(row[4]) == Mode.F for row in self._state)
        terminated = all(finished)
        truncated = self._step_count >= self.max_steps and not terminated
        self._needs_reset = terminated or truncated

        # Check just the new interval: old collisions are not penalized repeatedly.
        collision_pass = checks.check_collision(window, job_dir=self.job_dir)
        elapsed = self._time - previous_time
        time_reward = -self.makespan_weight * elapsed
        collision_reward = -self.collision_penalty * (1 - collision_pass)
        final_reward = 0.0
        validation_pass = shape_pass = success = None
        if self._needs_reset:
            trajectory = self.get_trajectory()
            validation_pass = checks.check_validation(trajectory, job_dir=self.job_dir)
            shape_pass = checks.check_shape(trajectory, job_dir=self.job_dir)
            success = int(terminated and validation_pass == 1 and shape_pass == 1)
            final_reward = self.terminal_reward if success else -self.terminal_penalty
        info = {
            "makespan_s": self._time,
            "delta_makespan_s": elapsed,
            "finished": finished,
            "collision_pass": collision_pass,
            "validation_pass": validation_pass,
            "shape_pass": shape_pass,
            "success": success,
            "reward_makespan": time_reward,
            "reward_collision": collision_reward,
            "reward_terminal": final_reward,
        }
        reward = float(time_reward + collision_reward + final_reward)
        return self.state, reward, terminated, truncated, info

    def close(self) -> None:
        self._closed = True
        self._needs_reset = True
        super().close()
