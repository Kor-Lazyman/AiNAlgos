"""Policy-selected bead segments with explicit process-aware motion execution.

No planner, path catalogue or target path is consulted. Each action chooses
two continuous XY points, a printable height, a robot, and a command. Travel,
deposition and home return are all recorded and independently checked.
"""
import math

import gymnasium as gym
import numpy as np

from .gym_wrapper import Mode
from .trajectory_env import TrajectoryPPOEnv


class StrokePPOEnv(TrajectoryPPOEnv):
    policy_interface = "policy_segment_xyz_modes_v1"
    reward_scheme = "segment_iou_safety_scaled_v1"
    reward_scale = .01
    process_penalty = 2.

    def __init__(self, job_dir, *, max_steps=512, grid_size=12, collision_penalty=2.):
        super().__init__(job_dir, max_steps=max_steps, grid_size=grid_size,
                         collision_penalty=collision_penalty)
        self.action_space = gym.spaces.Box(-1., 1., (7,), dtype=np.float32)
        # Bound the bead centre to the target XY box, inset by half bead width.
        # This is a coordinate domain, not clipping to a target contour.
        radius = self.config.process.bead_width_mm / 2
        centre = self.mesh.bounds[:, :2].mean(axis=0)
        half = np.maximum((self.mesh.bounds[1, :2]-self.mesh.bounds[0, :2])/2-radius, 0.)
        self.stroke_xy_low, self.stroke_xy_high = centre-half, centre+half
        self.print_indices = sorted(i for i, polygon in self._target_slices.items()
                                    if polygon.area > self.config.shape_validation.area_epsilon_mm2)

    @staticmethod
    def _bin(value, count):
        return min(count-1, math.floor((float(value)+1)*.5*count))

    def decode_stroke(self, action):
        value = np.asarray(action, dtype=float)
        if value.shape != (7,) or not np.isfinite(value).all() or np.any(np.abs(value) > 1):
            raise ValueError("Stroke action must be finite (7,) in [-1,1]")
        xy = self.stroke_xy_low + (value[:4].reshape(2, 2)+1)*.5*(self.stroke_xy_high-self.stroke_xy_low)
        index = self.print_indices[self._bin(value[4], len(self.print_indices))]
        process = self.config.process
        reference = 1. if process.tcp_z_reference == "top" else .5
        z = process.build_plane_z_mm + (index+reference)*process.layer_height_mm
        robot = self._bin(value[5], 3)
        command = "T" if value[6] < -.8 else "D" if value[6] < .6 else "W" if value[6] < .9 else "F"
        return robot, np.column_stack((xy, np.full(2, z))), command

    def _execute_action(self, action):
        robot, points, command = self.decode_stroke(action)
        offsets = [len(rows)-1 for rows in self._history]
        start_time = self._time

        def move(position, mode):
            targets = [row[1:4].copy() for row in self._state]
            targets[robot] = list(position)
            modes = [Mode.W]*3
            modes[robot] = mode
            self._advance(targets, modes)

        if command in ("D", "T"):
            move(points[0], Mode.T)
            if command == "D":
                move(points[1], Mode.D)
            move(self._homes[robot], Mode.T)
        else:
            self._advance([row[1:4].copy() for row in self._state],
                          [Mode.F if command == "F" else Mode.W]*3)
        # Include every transition of this macro action in process/collision checks.
        window = self._trajectory_dict([rows[offset:] for rows, offset in zip(self._history, offsets)],
                                       time_origin=start_time)
        modes = [Mode.W]*3
        modes[robot] = Mode[command]
        if command == "F":
            modes = [Mode.F]*3
        self._last_stroke = {"robot_id": robot+1, "points_mm": points.tolist(), "command": command,
                             "execution": "T_to_start,D_to_end,T_home" if command == "D" else command}
        return [row[1:4].copy() for row in self._state], modes, window

    def _terminal_adjustment(self, ended, success):
        if not ended:
            return 0.
        # Retain a substantial terminal consequence even though exploration
        # penalties per segment are smaller. Violations never become PASS.
        safety = -100. if self._collision_steps or not self._process_pass else 0.
        return safety + (25. if success else 0.)

    def reset(self, *, seed=None, options=None):
        self._deposition_steps = 0
        self._invalid_process_steps = 0
        return super().reset(seed=seed, options=options)

    def step(self, action):
        result = super().step(action)
        self.action_history[-1]["stroke"] = self._last_stroke
        self._deposition_steps += int(self._last_stroke["command"] == "D")
        self._invalid_process_steps += int(not self.action_history[-1]["validation_pass"])
        result[-1].update(self._diagnostics())
        return result

    def _diagnostics(self):
        return {"deposition_commands": self._deposition_steps,
                "invalid_process_steps": self._invalid_process_steps,
                "reward_scale": self.reward_scale,
                "early_finish": int(self._needs_reset and self._step_count == 1 and self._metrics.iou == 0)}

    def _info(self, *, success, reason):
        return {**super()._info(success=success, reason=reason), **self._diagnostics()}
