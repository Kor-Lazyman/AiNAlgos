"""Geometry-guided PPO: residual-region hints, policy-selected local segments.

The controller selects an unfilled component and its process height. The
policy selects both XY endpoints, the robot and T/D/W/F command. This is an
explicit guided interface, not unconstrained XYZ control or a learned slicer.
No planned stroke, contour, path ordering or automatic F is substituted.
"""
import gymnasium as gym
import numpy as np
import shapely
import io
from time import perf_counter
import trimesh

from .stroke_wrapper import StrokePPOEnv
from . import env as checks
from models.reconstruction import compare_solids, deposited_solid
from models.terminal_rewards import TerminalRewards
from waam_validator.shape.metrics import compute_shape_metrics
from waam_validator.shape.polygon_utils import polygon_components


class ResidualStrokeEnv(StrokePPOEnv):
    policy_interface = "residual_guided_segments_v1"
    reward_scheme = "residual_validated_makespan_v2"

    def __init__(self, *args, terminal_rewards=None, **kwargs):
        self.terminal_rewards = terminal_rewards or TerminalRewards()
        super().__init__(*args, **kwargs)
        self.action_space = gym.spaces.Box(-1., 1., (6,), dtype=np.float32)
        self.observation_space = gym.spaces.Dict({**self.observation_space.spaces,
            "guidance": gym.spaces.Box(-np.inf, np.inf, (10,), dtype=np.float32)})
        radius = self.config.process.bead_width_mm/2
        self._regions = []
        for index, polygon in sorted(self._target_slices.items()):
            for part in polygon_components(polygon):
                domain = part.buffer(-radius)
                if domain.is_empty:
                    domain = part.representative_point()
                bounds = np.array(part.bounds).reshape(2, 2)
                centre = bounds.mean(axis=0)
                half = np.maximum((bounds[1]-bounds[0])/2-radius, 0.)
                low, high = centre-half, centre+half
                axes = [np.linspace(lo, hi, min(24, max(2, int(np.ceil((hi-lo)/radius))+1))) for lo, hi in zip(low, high)]
                x, y = np.meshgrid(*axes)
                candidates = np.column_stack((x.ravel(), y.ravel()))
                candidates = candidates[shapely.covers(domain, shapely.points(candidates))]
                if not len(candidates):
                    candidates = np.array(domain.representative_point().coords)
                disks = shapely.buffer(shapely.points(candidates), self.config.process.bead_width_mm)
                self._regions.append({"index": index, "part": part, "low": low, "high": high,
                    "candidates": candidates, "disks": disks, "last_deposited": False, "best": None})
        self._target_area = sum(region["part"].area for region in self._regions)
        process = self.config.process
        # A target-specific characteristic time, not a claimed optimal bound.
        reference_length = 2*process.bead_width_mm
        strokes = max(1., self._target_area/(process.bead_width_mm*reference_length))
        centre = self.mesh.bounds.mean(axis=0)
        round_trip = 2*np.linalg.norm(np.asarray(self._homes)-centre, axis=1).mean()/process.travel_speed_mm_s
        automatic_reference = self._target_area/(process.bead_width_mm*process.deposition_speed_mm_s) + strokes*round_trip
        self.makespan_reference_s = self.terminal_rewards.reference_seconds or float(automatic_reference)

    def _select_focus(self):
        # The hint comes from the actual residual geometry, not a waypoint list.
        options = []
        for region in self._regions:
            index, part = region["index"], region["part"]
            deposited = self._deposited.get(index)
            if region["last_deposited"] is not deposited:
                missing = part if deposited is None else part.difference(deposited)
                scores = shapely.area(shapely.intersection(region["disks"], missing))
                best = int(np.argmax(scores))
                region["best"] = (float(scores[best]), index, region["candidates"][best], region["low"], region["high"])
                region["last_deposited"] = deposited
            options.append(region["best"])
        area, index, anchor, low, high = max(options, key=lambda option: option[0])
        process = self.config.process
        z = process.build_plane_z_mm + (index+(1 if process.tcp_z_reference == "top" else .5))*process.layer_height_mm
        self._focus = {"anchor": anchor, "z": z, "low": low, "high": high, "remaining_area": area}
        return self._focus

    def _observation(self):
        result = super()._observation()
        focus = self._select_focus()
        span = self.xyz_high-self.xyz_low
        xyz = (np.array([*focus["anchor"], focus["z"]])-self.xyz_low)/span
        box = np.concatenate(((focus["low"]-self.xyz_low[:2])/span[:2],
                              (focus["high"]-self.xyz_low[:2])/span[:2]))
        result["guidance"] = np.array([*xyz, *box, focus["remaining_area"]/self._target_area,
                                      float(self._metrics.passed), self._metrics.overfill_ratio], dtype=np.float32)
        return result

    def decode_stroke(self, action):
        value = np.asarray(action, dtype=float)
        if value.shape != (6,) or not np.isfinite(value).all() or np.any(np.abs(value)>1):
            raise ValueError("Guided action must be finite (6,) in [-1,1]")
        focus = self._focus
        # Bound endpoints to the selected component's bounding box. Concave
        # contours and holes are NOT clipped; their overfill remains measurable.
        reach = 2*self.config.process.bead_width_mm
        xy = np.clip(focus["anchor"] + reach*value[:4].reshape(2, 2), focus["low"], focus["high"])
        command = "T" if value[5] < -.8 else "D" if value[5] < .6 else "W" if value[5] < .9 else "F"
        self._used_focus = {"anchor_xy_mm": focus["anchor"].tolist(), "z_mm": focus["z"],
                            "remaining_area_mm2": focus["remaining_area"]}
        return self._bin(value[4], 3), np.column_stack((xy, np.full(2, focus["z"]))), command

    def _execute_action(self, action):
        result = super()._execute_action(action)
        self._last_stroke["geometry_guidance"] = self._used_focus
        return result

    def _terminal_adjustment(self, ended, success):
        if not ended:
            return 0.
        safety = -100. if self._collision_steps or not self._process_pass else 0.
        if success and not self._terminal_validation_checked:
            self._terminal_validation_checked = True
            started = perf_counter()
            try:
                self._terminal_validation_pass, self._terminal_mesh_iou = self._check_terminal_mesh()
            except Exception as error:
                # Fail closed while retaining diagnostics; geometry failure is no bonus.
                self._terminal_validation_error = f"{type(error).__name__}: {error}"
                self._terminal_validation_pass = False
            self._terminal_validation_seconds = perf_counter()-started
        self._reward_validation_bonus, self._reward_makespan = self.terminal_rewards.bonuses(
            validated=success and self._terminal_validation_pass, actual_iou=self._terminal_mesh_iou,
            makespan_s=self._time, reference_seconds=self.makespan_reference_s)
        timeout = self._step_count >= self.max_steps and not all(int(row[4]) == 3 for row in self._state)
        return safety + (self._reward_validation_bonus+self._reward_makespan)/self.reward_scale - (25. if timeout else 0.)

    def _check_terminal_mesh(self):
        trajectories, process, collision = self._checks.evaluate(self.get_trajectory())
        if not process or not collision:
            return False, -1.
        deposited = checks.build_deposited_layers(trajectories, self.config)
        metrics, _ = compute_shape_metrics(deposited, self._target_slices, self.config)
        if not metrics.passed:
            return False, -1.
        solid = deposited_solid(deposited, self.config)
        # Match STL precision and round-trip checks without per-episode disk I/O.
        reloaded = trimesh.load(io.BytesIO(solid.export(file_type="stl")), file_type="stl")
        volume = sum(p.area for p in deposited.values())*self.config.process.layer_height_mm
        if volume <= 0 or not reloaded.is_volume or abs(reloaded.volume-volume)/volume > 1e-5:
            return False, -1.
        iou = compare_solids(self.mesh, reloaded)["iou"]
        return iou >= self.terminal_rewards.min_mesh_iou, iou

    def step(self, action):
        before_iou, before_overfill = self._metrics.iou, self._metrics.overfill_ratio
        obs, reward, terminated, truncated, info = super().step(action)
        overfill_penalty = -200.*max(0., self._metrics.overfill_ratio-before_overfill)
        duplicate = self._last_stroke["command"] == "D" and self._metrics.iou <= before_iou+1e-6
        repeat_penalty = -.5 if duplicate else 0.
        extra = overfill_penalty + repeat_penalty
        reward += extra*self.reward_scale
        self.action_history[-1].update(reward=float(reward),
            raw_reward=self.action_history[-1]["raw_reward"]+extra,
            reward_overfill=overfill_penalty, reward_repeat=repeat_penalty,
            reward_validation_bonus=self._reward_validation_bonus,
            reward_makespan=self._reward_makespan,
            terminal_mesh_iou=self._terminal_mesh_iou)
        self._episode_reward_overfill += overfill_penalty
        self._duplicate_steps += int(duplicate)
        info.update(self._guided_diagnostics())
        return obs, float(reward), terminated, truncated, info

    def reset(self, *, seed=None, options=None):
        self._episode_reward_overfill = 0.
        self._duplicate_steps = 0
        self._terminal_validation_checked = False
        self._terminal_validation_pass = False
        self._terminal_validation_error = ""
        self._terminal_validation_seconds = 0.
        self._terminal_mesh_iou = -1.
        self._reward_validation_bonus = 0.
        self._reward_makespan = 0.
        return super().reset(seed=seed, options=options)

    def _guided_diagnostics(self):
        return {"episode_reward_overfill": self._episode_reward_overfill,
                "duplicate_steps": self._duplicate_steps, "finish_ready": int(self._metrics.passed)}

    def _info(self, *, success, reason):
        return {**super()._info(success=success and self._terminal_validation_pass, reason=reason),
                **self._guided_diagnostics(),
                "makespan_weight": self.terminal_rewards.makespan_weight,
                "makespan_reference_s": self.makespan_reference_s,
                "reward_validation_bonus": self._reward_validation_bonus,
                "reward_makespan": self._reward_makespan,
                "terminal_validation_checked": int(self._terminal_validation_checked),
                "terminal_validation_pass": int(self._terminal_validation_pass),
                "terminal_mesh_iou": self._terminal_mesh_iou,
                "terminal_validation_seconds": self._terminal_validation_seconds,
                "terminal_validation_error": self._terminal_validation_error}
