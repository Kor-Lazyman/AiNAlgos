"""Target-conditioned PPO macro-action environment for nominal WAAM validation.

PPO selects contour inset and infill spacing per layer. A deterministic compiler
supplies legal planar T/D moves and serial robot scheduling. This is hierarchical
planning, not a learned low-level XYZ controller. Cached geometry is calculated
from the actual compiled float32 trajectory with the unchanged validator engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import gymnasium as gym
import numpy as np
from shapely import LineString

from . import env as checks
from waam_validator.shape.metrics import compute_shape_metrics


@dataclass
class LayerOption:
    paths: list[np.ndarray]
    geometry: object
    coverage: float
    overfill: float
    iou: float
    intersection: float
    deposited: float
    safe: bool


def layer_paths(polygon, inset: float, spacing: float) -> list[np.ndarray]:
    """Contour plus clipped parallel infill; never deposit between strokes."""
    inner = polygon.buffer(-inset)
    if inner.is_empty or inner.geom_type != "Polygon":
        return []
    paths = [np.asarray(inner.exterior.coords, dtype=np.float64)]
    x0, y0, x1, y1 = inner.bounds
    count = max(1, math.ceil((y1 - y0) / spacing))
    for y in np.linspace(y0, y1, count + 1)[1:-1]:
        clipped = inner.intersection(LineString([(x0 - 1, y), (x1 + 1, y)]))
        parts = list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped]
        for part in parts:
            if part.geom_type == "LineString" and part.length > 1e-5:
                paths.append(np.asarray(part.coords, dtype=np.float64))
    return paths


def compile_trajectory(config, layers, *, preserve_finish=False):
    """Each macro starts/ends at home; other robots wait throughout its duration."""
    robots = sorted(config.robots, key=lambda item: item.id)
    homes = [np.asarray(r.home_xyz_mm or r.base_xyz_mm, dtype=float) for r in robots]
    rows = [[[0.0, *home, "W"]] for home in homes]
    now = 0.0
    for layer, paths in layers:
        robot = layer % 3
        current = homes[robot].copy()
        z = config.process.build_plane_z_mm + (layer + 1) * config.process.layer_height_mm

        def move(end, mode):
            nonlocal now, current
            end = np.asarray(end, dtype=float)
            distance = float(np.linalg.norm(end - current))
            if distance <= 1e-6:
                return
            speed = (config.process.deposition_speed_mm_s if mode == "D"
                     else config.process.travel_speed_mm_s)
            rows[robot][-1][-1] = mode
            now += distance / speed
            rows[robot].append([now, *end, "W"])
            current = end

        for path in paths:
            move([*path[0], z], "T")
            for xy in path[1:]:
                move([*xy, z], "D")
        move(homes[robot], "T")
        for other in range(3):
            if other != robot and now > rows[other][-1][0]:
                rows[other].append([now, *homes[other], "W"])
    now += 0.1
    for robot in range(3):
        rows[robot].append([now, *homes[robot], "F" if preserve_finish else "W"])
    data = {key: [] for key in checks.CSV_COLUMNS}
    for robot, robot_rows in enumerate(rows, 1):
        for row in robot_rows:
            for key, value in zip(data, [robot, *row], strict=True):
                data[key].append(value)
    return data


class SpherePPOEnv(gym.Env):
    """24 layer decisions; dense shape reward plus dominant terminal PASS reward.

    All options undergo trajectory and collision checks before training. Exact
    per-layer areas can be added because the validator evaluates separate slabs.
    No speed, duration, or makespan term is present in the reward.
    """
    metadata = {"render_modes": []}
    parameters = tuple((inset, spacing) for inset in (1.6, 2.0, 2.8, 4.0)
                       for spacing in (3.0, 3.8, 5.5))

    def __init__(self, job_dir: str | Path, *, catalog=None):
        super().__init__()
        self.job_dir = Path(job_dir)
        self.config = checks.load_config(self.job_dir / "config.yaml")
        self.mesh = checks.load_target_mesh(self.job_dir / "target.stl", self.config)
        self.indices = checks.determine_evaluation_layers(self.mesh, {}, self.config)
        self.targets = checks.slice_target_layers(self.mesh, self.indices, self.config)
        self.total_area = sum(p.area for p in self.targets.values())
        self.catalog = catalog if catalog is not None else self._build_catalog()
        self.action_space = gym.spaces.Discrete(len(self.parameters))
        self.observation_space = gym.spaces.Box(0, 1, shape=(9,), dtype=np.float32)
        self.reset()

    def _build_catalog(self):
        catalog = []
        for layer in self.indices:
            options = []
            for inset, spacing in self.parameters:
                paths = layer_paths(self.targets[layer], inset, spacing)
                data = compile_trajectory(self.config, [(layer, paths)])
                trajectories = checks._load_trajectory(data)
                deposited = checks.build_deposited_layers(trajectories, self.config)
                _, metrics = compute_shape_metrics(deposited, {layer: self.targets[layer]}, self.config)
                metric = metrics[0]
                safe = bool(checks.check_validation(data, job_dir=self.job_dir)
                            and checks.check_collision(data, job_dir=self.job_dir))
                options.append(LayerOption(paths, deposited.get(layer), metric.coverage,
                                           metric.overfill_ratio or 0.0, metric.iou,
                                           metric.intersection_area_mm2,
                                           metric.deposited_area_mm2, safe))
            catalog.append(options)
            print(f"Catalog layer {layer + 1}/{len(self.indices)}: "
                  f"{sum(o.safe for o in options)} safe options", flush=True)
        return catalog

    def _observation(self):
        i = min(self.cursor, len(self.indices) - 1)
        target = self.targets[self.indices[i]]
        return np.asarray([self.cursor / len(self.indices),
                           target.area / max(p.area for p in self.targets.values()),
                           target.length / max(p.length for p in self.targets.values()),
                           self.intersection / self.total_area,
                           min(1, self.over / self.total_area),
                           self.failed / len(self.indices),
                           *[float(i % 3 == r) for r in range(3)]], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.cursor = 0
        self.intersection = self.deposited = self.over = 0.0
        self.failed = 0
        self.safe = True
        self.selected = []
        return self._observation(), {}

    def step(self, action):
        if self.cursor >= len(self.indices):
            raise gym.error.ResetNeeded("Episode finished")
        if not self.action_space.contains(action):
            raise ValueError("Invalid layer option")
        option = self.catalog[self.cursor][int(action)]
        self.selected.append(int(action))
        self.intersection += option.intersection
        self.deposited += option.deposited
        self.over += option.deposited - option.intersection
        thresholds = self.config.shape_validation
        self.failed += int(option.iou < thresholds.minimum_layer_iou)
        self.safe &= option.safe
        # Constraint deficits give PPO a signal before it discovers a full pass.
        reward = (2 * option.iou - 20 * max(0, .95 - option.coverage)
                  - 20 * max(0, option.overfill - .05)) if option.safe else -100.0
        self.cursor += 1
        done = self.cursor == len(self.indices)
        coverage = self.intersection / self.total_area
        overfill = self.over / self.total_area
        iou = self.intersection / (self.total_area + self.deposited - self.intersection)
        success = (self.safe and coverage >= thresholds.minimum_overall_coverage
                   and overfill <= thresholds.maximum_overall_overfill_ratio
                   and iou >= thresholds.minimum_overall_iou
                   and self.failed / len(self.indices) <= thresholds.maximum_failed_layer_ratio)
        if done:
            reward += 100.0 if success else -100.0
        return self._observation(), float(reward), done, False, {
            "success": bool(done and success), "coverage": coverage,
            "overfill": overfill, "iou": iou, "makespan_weight": 0.0,
        }

    def get_trajectory(self, *, preserve_finish=False):
        return compile_trajectory(self.config,
                                  [(layer, self.catalog[i][a].paths)
                                   for i, (layer, a) in enumerate(zip(self.indices, self.selected))],
                                  preserve_finish=preserve_finish)
