"""Generate and compare bead-footprint paths for arbitrary horizontal sections."""
from dataclasses import dataclass
import math

import numpy as np
from shapely import LineString, union_all
from shapely.affinity import rotate

from environment import env as checks
from environment.fast_checks import PreparedTrajectoryChecks
from waam_validator.shape.polygon_utils import normalize_polygon, polygon_components


@dataclass
class SectionPlan:
    index: int
    paths: list
    parameters: dict
    predicted_iou: float
    robot: int = 0


def paths_for_section(polygon, inset, spacing, angle, simplify):
    inner = rotate(polygon.buffer(-inset), -angle, origin=(0, 0))
    paths = []
    for component in polygon_components(inner):
        component = component.simplify(simplify, preserve_topology=True)
        for ring in [component.exterior, *component.interiors]:
            paths.append(np.asarray(rotate(LineString(ring.coords), angle, origin=(0, 0)).coords))
        x0, y0, x1, y1 = component.bounds
        count = max(1, math.ceil((y1-y0)/spacing))
        for y in np.linspace(y0, y1, count+1)[1:-1]:
            clipped = component.intersection(LineString([(x0-1, y), (x1+1, y)]))
            for part in getattr(clipped, "geoms", [clipped]):
                if part.geom_type == "LineString" and part.length > 1e-5:
                    paths.append(np.asarray(rotate(part, angle, origin=(0, 0)).coords))
    return paths


def footprint(paths, config):
    pieces = []
    for path in paths:
        # Match the executed float32 coordinates and the validator's segment buffers.
        coordinates = np.asarray(path, dtype=np.float32).astype(float)
        for start, end in zip(coordinates[:-1], coordinates[1:]):
            if np.linalg.norm(end-start) > 1e-6:
                pieces.append(LineString([start, end]).buffer(config.process.bead_width_mm/2,
                    quad_segs=config.shape_validation.polygon_buffer_resolution))
    return normalize_polygon(union_all(pieces), config.shape_validation.polygon_snap_tolerance_mm,
                             config.shape_validation.area_epsilon_mm2)


def compile_trajectory(config, sections, preserve_finish=False):
    """Serial T/D strokes with explicit W for idle robots and F after home return."""
    robots = sorted(config.robots, key=lambda r: r.id)
    homes = [np.asarray(r.home_xyz_mm or r.base_xyz_mm, dtype=float) for r in robots]
    rows = [[[0., *home, "W"]] for home in homes]
    now = 0.
    for section in sections:
        robot = section.robot
        current = homes[robot].copy()
        reference = 1 if config.process.tcp_z_reference == "top" else .5
        z = config.process.build_plane_z_mm + (section.index + reference)*config.process.layer_height_mm

        def move(end, mode):
            nonlocal now, current
            end = np.asarray(end, dtype=float)
            distance = np.linalg.norm(end-current)
            if distance <= 1e-6:
                return
            speed = config.process.deposition_speed_mm_s if mode == "D" else config.process.travel_speed_mm_s
            rows[robot][-1][-1] = mode
            now += float(distance/speed)
            rows[robot].append([now, *end, "W"])
            current = end

        for path in section.paths:
            move([*path[0], z], "T")
            for xy in path[1:]:
                move([*xy, z], "D")
        move(homes[robot], "T")
        for other in range(3):
            if other != robot and now > rows[other][-1][0]:
                rows[other].append([now, *homes[other], "W"])
    now += .1
    for robot in range(3):
        rows[robot].append([now, *homes[robot], "F" if preserve_finish else "W"])
    data = {key: [] for key in checks.CSV_COLUMNS}
    for robot, robot_rows in enumerate(rows, 1):
        for row in robot_rows:
            for key, value in zip(data, [robot, *row]):
                data[key].append(value)
    return data


def build_plan(job_dir):
    """Infer section locations from STL; never require a user-supplied layer count."""
    config = checks.load_config(job_dir / "config.yaml")
    mesh = checks.load_target_mesh(job_dir / "target.stl", config)
    indices = checks.determine_evaluation_layers(mesh, {}, config)
    targets = checks.slice_target_layers(mesh, indices, config)
    targets = {i: p for i, p in targets.items() if p.area > config.shape_validation.area_epsilon_mm2}
    checker = PreparedTrajectoryChecks(config)
    width = config.process.bead_width_mm
    sections = []
    for number, (index, polygon) in enumerate(sorted(targets.items()), 1):
        candidates = []
        for inset in (.45, .5, .55):
            for spacing in (.7, .85, 1.):
                for angle in (0., 45., 90.):
                    paths = paths_for_section(polygon, width*inset, width*spacing, angle, width*.005)
                    geometry = footprint(paths, config)
                    intersection = polygon.intersection(geometry).area
                    union = polygon.union(geometry).area
                    iou = intersection / union if union > 0 else 0.
                    candidates.append(SectionPlan(index, paths,
                        {"inset_mm": width*inset, "spacing_mm": width*spacing, "angle_deg": angle}, iou))
        candidates.sort(key=lambda c: c.predicted_iou, reverse=True)
        selected = None
        for candidate in candidates:
            if not candidate.paths:
                continue
            # Robot assignment is chosen from actual validated motions, not index modulo 3.
            for robot in range(3):
                candidate.robot = robot
                _, process, collision = checker.evaluate(compile_trajectory(config, [candidate]))
                if process and collision:
                    selected = candidate
                    break
            if selected is not None:
                break
        if selected is None:
            raise ValueError(f"No valid path for section {index}; check bead width, workspace and robot reach")
        sections.append(selected)
        print(f"Section {number}/{len(targets)}: predicted IoU={selected.predicted_iou:.4%}, robot={selected.robot+1}", flush=True)
    if not sections:
        raise ValueError("No printable target sections")
    return config, sections
