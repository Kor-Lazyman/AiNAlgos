"""Stable-Baselines3 environment backed by the WAAM validation pipeline."""

from __future__ import annotations

import csv
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

try:
    import gymnasium as gym
    from gymnasium import spaces
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the optional extra
    raise ModuleNotFoundError(
        "WaamPPOEnv requires the optional RL dependencies. "
        "Install them with `pip install -e .[rl]`."
    ) from exc

from .config.loader import load_config
from .errors import WaamValidatorError
from .pipeline import run_validation


class WaamPPOEnv(gym.Env[np.ndarray, np.ndarray]):
    """Continuous-control environment for generating a three-robot trajectory.

    Each robot consumes three action values in ``[-1, 1]``: normalized X
    movement, normalized Y movement, and a deposition request. The adapter
    converts those actions into valid ``T``, ``D`` or ``W`` trajectory
    intervals, then delegates scoring to :func:`run_validation`.

    The source job must contain the validator's normal ``config.yaml`` and
    ``target.stl`` files. The source directory is never modified; each episode
    gets an isolated temporary job directory and generated ``trajectory.csv``.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        job_dir: str | Path,
        *,
        max_steps: int = 128,
        movement_step_mm: float = 10.0,
        validate_each_step: bool = False,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if render_mode is not None:
            raise ValueError("WaamPPOEnv does not provide a render mode")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        if movement_step_mm <= 0:
            raise ValueError("movement_step_mm must be positive")

        self.source_dir = Path(job_dir).expanduser().resolve()
        self.config = load_config(self.source_dir / "config.yaml")
        self.target_path = self.source_dir / "target.stl"
        if not self.target_path.is_file():
            raise FileNotFoundError(f"Target STL does not exist: {self.target_path}")

        self.max_steps = max_steps
        self.movement_step_mm = float(movement_step_mm)
        self.validate_each_step = validate_each_step
        self._episode_dir = Path(tempfile.mkdtemp(prefix="waam-ppo-"))
        self._job_dir = self._episode_dir / "job"
        self._output_dir = self._episode_dir / "output"
        self._job_dir.mkdir()
        shutil.copy2(self.source_dir / "config.yaml", self._job_dir / "config.yaml")
        shutil.copy2(self.target_path, self._job_dir / "target.stl")

        self.action_space = spaces.Box(-1.0, 1.0, shape=(9,), dtype=np.float32)
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(10,), dtype=np.float32)
        self._normalization = self._compute_normalization()
        self._positions = np.zeros((3, 3), dtype=np.float64)
        self._times = np.zeros(3, dtype=np.float64)
        self._rows: list[list[object]] = []
        self._step_count = 0

    def _compute_normalization(self) -> float:
        coordinates = [
            abs(value)
            for robot in self.config.robots
            for point in (robot.base_xyz_mm, robot.home_xyz_mm or robot.base_xyz_mm)
            for value in point
        ]
        return max(
            1.0,
            self.config.workspace.radius_mm,
            max(robot.xy_reach_radius_mm for robot in self.config.robots),
            max(coordinates),
        ) * 1.1

    def _observation(self) -> npt.NDArray[np.float32]:
        position_values = (self._positions / self._normalization).reshape(-1)
        step_fraction = np.array([self._step_count / self.max_steps], dtype=np.float64)
        observation = np.concatenate((position_values, step_fraction))
        return np.clip(observation, -1.0, 1.0).astype(np.float32)

    def _reset_episode_files(self) -> None:
        if self._output_dir.exists():
            shutil.rmtree(self._output_dir)
        self._rows = []
        for robot_id, robot in enumerate(self.config.robots, start=1):
            home = np.asarray(robot.home_xyz_mm or robot.base_xyz_mm, dtype=np.float64)
            self._positions[robot_id - 1] = home
            self._times[robot_id - 1] = 0.0
            self._rows.append([robot_id, 0.0, home[0], home[1], home[2], "W"])

    def _write_trajectory(self) -> None:
        path = self._job_dir / "trajectory.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("robot_id", "time_s", "x_mm", "y_mm", "z_mm", "mode"))
            writer.writerows(sorted(self._rows, key=lambda row: (int(row[0]), float(row[1]))))

    def _append_transition(self, action: npt.NDArray[np.float32]) -> float:
        deposition_z = self.config.process.build_plane_z_mm + self.config.process.layer_height_mm
        total_deposition_distance = 0.0
        for index, robot in enumerate(self.config.robots):
            start = self._positions[index].copy()
            delta_xy = np.asarray(action[index * 3 : index * 3 + 2], dtype=np.float64)
            end = start.copy()
            end[:2] += delta_xy * self.movement_step_mm
            requests_deposition = float(action[index * 3 + 2]) > 0.0
            if requests_deposition:
                end[2] = deposition_z
            distance = float(np.linalg.norm(end - start))
            xy_distance = float(np.linalg.norm(end[:2] - start[:2]))
            at_deposition_height = abs(start[2] - deposition_z) <= 1.0e-6
            if distance <= self.config.collision.geometry_epsilon_mm:
                mode = "W"
                duration = 0.1
            elif requests_deposition and at_deposition_height:
                mode = "D"
                duration = distance / self.config.process.deposition_speed_mm_s
                total_deposition_distance += xy_distance
            else:
                mode = "T"
                duration = distance / self.config.process.travel_speed_mm_s
            duration = max(duration, 0.001)
            row_index = next(
                index
                for index in range(len(self._rows) - 1, -1, -1)
                if int(self._rows[index][0]) == robot.id
            )
            self._rows[row_index][5] = mode
            self._times[index] += duration
            self._rows.append([robot.id, self._times[index], end[0], end[1], end[2], "W"])
            self._positions[index] = end
        return total_deposition_distance

    def _validation_reward(self) -> tuple[float, dict[str, Any]]:
        self._write_trajectory()
        try:
            result = run_validation(self._job_dir, self._output_dir)
        except WaamValidatorError as exc:
            return -10.0, {"validation_error": exc.code, "validation_message": exc.message}
        reward = (
            result.shape.coverage
            - result.shape.overfill_ratio
            - 0.05 * len(result.collision.events)
            - 0.01 * result.reach.robots[0].xy_violation_point_count
            - 0.01 * result.reach.robots[1].xy_violation_point_count
            - 0.01 * result.reach.robots[2].xy_violation_point_count
        )
        if result.status == "PASS":
            reward += 1.0
        return float(reward), {
            "status": result.status,
            "coverage": result.shape.coverage,
            "overfill_ratio": result.shape.overfill_ratio,
            "collision_events": len(result.collision.events),
            "makespan_s": result.schedule.makespan_s,
        }

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[npt.NDArray[np.float32], dict[str, Any]]:
        del options
        super().reset(seed=seed)
        self._step_count = 0
        self._reset_episode_files()
        return self._observation(), {}

    def step(
        self, action: npt.NDArray[np.float32]
    ) -> tuple[npt.NDArray[np.float32], float, bool, bool, dict[str, Any]]:
        action_array = np.asarray(action, dtype=np.float32)
        if action_array.shape != self.action_space.shape:
            raise ValueError(
                f"Expected action shape {self.action_space.shape}, got {action_array.shape}"
            )
        action_array = np.clip(action_array, -1.0, 1.0)
        deposited_distance = self._append_transition(action_array)
        self._step_count += 1
        terminated = self._step_count >= self.max_steps
        info: dict[str, Any] = {"deposited_distance_mm": deposited_distance}
        reward = deposited_distance / max(self.movement_step_mm, 1.0)
        if self.validate_each_step or terminated:
            reward, validation_info = self._validation_reward()
            info.update(validation_info)
        return self._observation(), reward, terminated, False, info

    def close(self) -> None:
        shutil.rmtree(self._episode_dir, ignore_errors=True)
        super().close()
