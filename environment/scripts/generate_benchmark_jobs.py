"""Generate ten reproducible thin-wall/lattice WAAM benchmark jobs.

The target mesh and trajectory are derived from the same parametric centerline
definition.  This deliberately isolates Validator regressions from the quality
of an external slicer while still exercising distinct topology and path shapes.
"""

from __future__ import annotations

import argparse
import csv
import math
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import trimesh
from shapely import LineString, union_all

from waam_validator.config.loader import load_config
from waam_validator.config.models import Config
from waam_validator.shape.polygon_utils import normalize_polygon, polygon_components

Point2D = tuple[float, float]
PathFactory = Callable[[], list[LineString]]


@dataclass(slots=True, frozen=True)
class BenchmarkSpec:
    number: int
    name: str
    description: str
    layers: int
    factory: PathFactory


@dataclass(slots=True)
class RobotRows:
    robot_id: int
    home: np.ndarray
    rows: list[tuple[float, float, float, float, str]]

    @classmethod
    def create(cls, robot_id: int, home: np.ndarray) -> RobotRows:
        return cls(
            robot_id=robot_id,
            home=home,
            rows=[(0.0, float(home[0]), float(home[1]), float(home[2]), "W")],
        )

    @property
    def last_time(self) -> float:
        return self.rows[-1][0]

    @property
    def last_xyz(self) -> np.ndarray:
        return np.asarray(self.rows[-1][1:4], dtype=np.float64)

    def set_last_mode(self, mode: str) -> None:
        time_s, x_mm, y_mm, z_mm, _ = self.rows[-1]
        self.rows[-1] = (time_s, x_mm, y_mm, z_mm, mode)

    def append(self, time_s: float, xyz: np.ndarray, mode: str) -> None:
        if time_s <= self.last_time:
            raise ValueError(f"R{self.robot_id} timestamp did not increase")
        self.rows.append((time_s, float(xyz[0]), float(xyz[1]), float(xyz[2]), mode))


def _line(points: Sequence[Point2D]) -> LineString:
    line = LineString(points)
    if line.length <= 0.0:
        raise ValueError("Benchmark path must have positive length")
    return line


def _arc_segments(
    radius_mm: float,
    *,
    segment_count: int,
    center: Point2D = (0.0, 0.0),
    phase_rad: float = 0.0,
) -> list[LineString]:
    paths: list[LineString] = []
    for index in range(segment_count):
        angles = np.linspace(
            phase_rad + 2.0 * math.pi * index / segment_count,
            phase_rad + 2.0 * math.pi * (index + 1) / segment_count,
            13,
        )
        points = [
            (
                center[0] + radius_mm * math.cos(float(angle)),
                center[1] + radius_mm * math.sin(float(angle)),
            )
            for angle in angles
        ]
        paths.append(_line(points))
    return paths


def _raster_plate() -> list[LineString]:
    return [_line([(-180.0, y_mm), (180.0, y_mm)]) for y_mm in np.arange(-48.0, 48.1, 8.0)]


def _circular_ring() -> list[LineString]:
    return _arc_segments(150.0, segment_count=18)


def _concentric_rings() -> list[LineString]:
    return _arc_segments(165.0, segment_count=18) + _arc_segments(
        92.0, segment_count=12, phase_rad=math.pi / 12.0
    )


def _star_frame() -> list[LineString]:
    points: list[Point2D] = []
    for index in range(10):
        radius = 170.0 if index % 2 == 0 else 72.0
        angle = math.pi / 2.0 + index * math.pi / 5.0
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return [_line([points[index], points[(index + 1) % len(points)]]) for index in range(10)]


def _reinforced_cross() -> list[LineString]:
    center = (0.0, 0.0)
    outer = [(-180.0, 0.0), (180.0, 0.0), (0.0, -180.0), (0.0, 180.0)]
    diagonal = 118.0
    outer.extend(
        [
            (-diagonal, -diagonal),
            (diagonal, diagonal),
            (-diagonal, diagonal),
            (diagonal, -diagonal),
        ]
    )
    return [_line([center, endpoint]) for endpoint in outer]


def _hexagon_edges(center: Point2D, radius_mm: float) -> list[LineString]:
    vertices = [
        (
            center[0] + radius_mm * math.cos(math.pi / 6.0 + index * math.pi / 3.0),
            center[1] + radius_mm * math.sin(math.pi / 6.0 + index * math.pi / 3.0),
        )
        for index in range(6)
    ]
    return [_line([vertices[index], vertices[(index + 1) % 6]]) for index in range(6)]


def _honeycomb_cluster() -> list[LineString]:
    radius = 42.0
    centers = [(0.0, 0.0)]
    for index in range(6):
        angle = index * math.pi / 3.0
        centers.append(
            (
                math.sqrt(3.0) * radius * math.cos(angle),
                math.sqrt(3.0) * radius * math.sin(angle),
            )
        )
    unique: dict[tuple[Point2D, Point2D], LineString] = {}
    for center in centers:
        for edge in _hexagon_edges(center, radius):
            left = tuple(round(float(value), 6) for value in edge.coords[0])
            right = tuple(round(float(value), 6) for value in edge.coords[-1])
            key = cast(tuple[Point2D, Point2D], tuple(sorted((left, right))))
            unique[key] = edge
    return list(unique.values())


def _sinusoidal_panel() -> list[LineString]:
    x_values = np.linspace(-190.0, 190.0, 161)
    paths: list[LineString] = []
    for offset in np.linspace(-105.0, 105.0, 7):
        points = [(float(x_mm), float(offset + 13.0 * math.sin(x_mm / 28.0))) for x_mm in x_values]
        paths.append(_line(points))
    return paths


def _spiral_wall() -> list[LineString]:
    theta = np.linspace(0.0, 6.0 * math.pi, 361)
    radius = np.linspace(24.0, 185.0, len(theta))
    points = [
        (float(r_mm * math.cos(angle)), float(r_mm * math.sin(angle)))
        for r_mm, angle in zip(radius, theta, strict=True)
    ]
    boundaries = np.linspace(0, len(points) - 1, 16, dtype=np.int64)
    return [
        _line(points[int(left) : int(right) + 1])
        for left, right in zip(boundaries[:-1], boundaries[1:], strict=True)
    ]


def _triangular_truss() -> list[LineString]:
    vertices = [(-175.0, -105.0), (175.0, -105.0), (0.0, 190.0)]
    paths = [_line([vertices[index], vertices[(index + 1) % 3]]) for index in range(3)]
    center = (0.0, -6.666667)
    paths.extend(_line([vertex, center]) for vertex in vertices)
    midpoints = [
        (
            (vertices[index][0] + vertices[(index + 1) % 3][0]) / 2.0,
            (vertices[index][1] + vertices[(index + 1) % 3][1]) / 2.0,
        )
        for index in range(3)
    ]
    paths.extend(_line([midpoints[index], midpoints[(index + 1) % 3]]) for index in range(3))
    return paths


def _waam_wordmark() -> list[LineString]:
    strokes: list[Sequence[Point2D]] = [
        [(-235.0, 75.0), (-215.0, -75.0), (-190.0, 15.0), (-165.0, -75.0), (-145.0, 75.0)],
        [(-125.0, -75.0), (-95.0, 75.0), (-65.0, -75.0)],
        [(-112.0, -10.0), (-78.0, -10.0)],
        [(-45.0, -75.0), (-15.0, 75.0), (15.0, -75.0)],
        [(-32.0, -10.0), (2.0, -10.0)],
        [(35.0, -75.0), (35.0, 75.0), (78.0, -10.0), (121.0, 75.0), (121.0, -75.0)],
    ]
    return [_line(points) for points in strokes]


BENCHMARKS = (
    BenchmarkSpec(1, "raster_plate", "평행 raster로 채운 판형 모델", 6, _raster_plate),
    BenchmarkSpec(2, "circular_ring", "원형 단일 thin-wall", 8, _circular_ring),
    BenchmarkSpec(3, "concentric_rings", "서로 분리된 동심 이중 벽", 7, _concentric_rings),
    BenchmarkSpec(4, "star_frame", "오목 꼭짓점을 가진 별형 폐곡선", 6, _star_frame),
    BenchmarkSpec(5, "reinforced_cross", "직교·대각선이 만나는 보강 십자", 5, _reinforced_cross),
    BenchmarkSpec(6, "honeycomb_cluster", "다중 cell 육각 격자", 6, _honeycomb_cluster),
    BenchmarkSpec(7, "sinusoidal_panel", "평행한 곡선형 벽 배열", 7, _sinusoidal_panel),
    BenchmarkSpec(8, "spiral_wall", "연속 곡률의 나선형 벽", 8, _spiral_wall),
    BenchmarkSpec(9, "triangular_truss", "외곽·중앙 보강 삼각 truss", 6, _triangular_truss),
    BenchmarkSpec(10, "waam_wordmark", "다중 stroke WAAM 문자 모델", 5, _waam_wordmark),
)


def _home_position(config: Config, robot_id: int) -> np.ndarray:
    robot = config.robot(robot_id)
    if robot.home_xyz_mm is not None:
        return np.asarray(robot.home_xyz_mm, dtype=np.float64)
    base = np.asarray(robot.base_xyz_mm, dtype=np.float64)
    center = np.asarray(config.workspace.center_xy_mm, dtype=np.float64)
    direction = center - base[:2]
    direction /= np.linalg.norm(direction)
    safe_z = config.process.safe_travel_z_mm
    return np.asarray(
        [
            base[0] + direction[0] * min(400.0, robot.xy_reach_radius_mm * 0.2),
            base[1] + direction[1] * min(400.0, robot.xy_reach_radius_mm * 0.2),
            safe_z if safe_z is not None else config.process.build_plane_z_mm + 500.0,
        ],
        dtype=np.float64,
    )


def _assign_paths(paths: list[LineString], config: Config) -> dict[int, list[LineString]]:
    assignments = {1: [], 2: [], 3: []}
    loads = {1: 0.0, 2: 0.0, 3: 0.0}
    bases = {
        robot.id: np.asarray(robot.base_xyz_mm[:2], dtype=np.float64) for robot in config.robots
    }
    ordered = sorted(paths, key=lambda item: (-item.length, item.centroid.x, item.centroid.y))
    for path in ordered:
        center = np.asarray([path.centroid.x, path.centroid.y], dtype=np.float64)
        robot_id = min(
            (1, 2, 3),
            key=lambda candidate: (
                float(np.linalg.norm(center - bases[candidate])) + loads[candidate],
                candidate,
            ),
        )
        assignments[robot_id].append(path)
        loads[robot_id] += float(path.length)
    return assignments


def _order_paths(paths: list[LineString], start_xy: np.ndarray) -> list[list[Point2D]]:
    remaining = [list(path.coords) for path in paths]
    ordered: list[list[Point2D]] = []
    current = start_xy.astype(np.float64)
    while remaining:
        best_index = 0
        reverse = False
        best_distance = float("inf")
        for index, coordinates in enumerate(remaining):
            start = np.asarray(coordinates[0], dtype=np.float64)
            end = np.asarray(coordinates[-1], dtype=np.float64)
            start_distance = float(np.linalg.norm(start - current))
            end_distance = float(np.linalg.norm(end - current))
            candidate = min(start_distance, end_distance)
            if candidate < best_distance:
                best_index = index
                reverse = end_distance < start_distance
                best_distance = candidate
        selected = remaining.pop(best_index)
        if reverse:
            selected.reverse()
        ordered.append([(float(point[0]), float(point[1])) for point in selected])
        current = np.asarray(selected[-1], dtype=np.float64)
    return ordered


def _append_wait(builder: RobotRows, duration_s: float, next_mode: str) -> None:
    if duration_s > 0.0:
        builder.append(builder.last_time + duration_s, builder.last_xyz, next_mode)
    else:
        builder.set_last_mode(next_mode)


def _append_travel(
    builder: RobotRows,
    target: np.ndarray,
    speed_mm_s: float,
    next_mode: str,
) -> None:
    distance = float(np.linalg.norm(target - builder.last_xyz))
    if distance > 1.0e-9:
        builder.append(builder.last_time + distance / speed_mm_s, target, next_mode)
    else:
        builder.set_last_mode(next_mode)


def _append_task(
    builder: RobotRows,
    paths: list[LineString],
    z_mm: float,
    start_s: float,
    config: Config,
) -> float:
    if builder.last_time < start_s:
        builder.append(start_s, builder.home, "T")
    else:
        builder.set_last_mode("T")
    ordered = _order_paths(paths, builder.home[:2])
    arc_on = config.process.arc_on_time_s or 0.0
    arc_off = config.process.arc_off_time_s or 0.0
    for coordinates in ordered:
        start = np.asarray([coordinates[0][0], coordinates[0][1], z_mm], dtype=np.float64)
        _append_travel(builder, start, config.process.travel_speed_mm_s, "W")
        _append_wait(builder, arc_on, "D")
        for x_mm, y_mm in coordinates[1:]:
            target = np.asarray([x_mm, y_mm, z_mm], dtype=np.float64)
            _append_travel(builder, target, config.process.deposition_speed_mm_s, "D")
        builder.set_last_mode("W")
        _append_wait(builder, arc_off, "T")
    _append_travel(builder, builder.home, config.process.travel_speed_mm_s, "W")
    return builder.last_time


def _build_trajectory(paths: list[LineString], layers: int, config: Config) -> dict[int, RobotRows]:
    builders = {
        robot_id: RobotRows.create(robot_id, _home_position(config, robot_id))
        for robot_id in (1, 2, 3)
    }
    assignments = _assign_paths(paths, config)
    global_time = 0.0
    for layer_index in range(layers):
        z_mm = (
            config.process.build_plane_z_mm + (layer_index + 0.5) * config.process.layer_height_mm
        )
        for robot_id in (1, 2, 3):
            if assignments[robot_id]:
                global_time = _append_task(
                    builders[robot_id],
                    assignments[robot_id],
                    z_mm,
                    global_time,
                    config,
                )
    for builder in builders.values():
        if builder.last_time < global_time:
            builder.append(global_time, builder.home, "W")
        else:
            builder.set_last_mode("W")
    return builders


def _write_trajectory(path: Path, builders: dict[int, RobotRows]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("robot_id", "time_s", "x_mm", "y_mm", "z_mm", "mode"))
        for robot_id in (1, 2, 3):
            for time_s, x_mm, y_mm, z_mm, mode in builders[robot_id].rows:
                writer.writerow(
                    (
                        robot_id,
                        f"{time_s:.9f}",
                        f"{x_mm:.6f}",
                        f"{y_mm:.6f}",
                        f"{z_mm:.6f}",
                        mode,
                    )
                )


def _write_target(
    path: Path,
    paths: list[LineString],
    layers: int,
    config: Config,
) -> tuple[int, float]:
    radius = config.process.bead_width_mm / 2.0
    footprint = normalize_polygon(
        union_all(
            [
                centerline.buffer(
                    radius,
                    quad_segs=config.shape_validation.polygon_buffer_resolution,
                    cap_style="round",
                    join_style="round",
                )
                for centerline in paths
            ]
        ),
        config.shape_validation.polygon_snap_tolerance_mm,
        config.shape_validation.area_epsilon_mm2,
    )
    height = layers * config.process.layer_height_mm
    meshes: list[trimesh.Trimesh] = []
    for polygon in polygon_components(footprint):
        mesh = trimesh.creation.extrude_polygon(polygon, height, engine="earcut")
        mesh.apply_translation((0.0, 0.0, config.process.build_plane_z_mm))
        meshes.append(mesh)
    if not meshes:
        raise ValueError("Generated target footprint is empty")
    combined = cast(trimesh.Trimesh, trimesh.util.concatenate(meshes))
    combined.export(path, file_type="stl")
    return len(combined.faces), float(footprint.area)


def generate_jobs(repo_root: Path) -> None:
    config_path = repo_root / "config.yaml"
    config = load_config(config_path)
    tests_root = repo_root / "tests"
    for spec in BENCHMARKS:
        paths = spec.factory()
        job_dir = tests_root / f"{spec.number:02d}"
        job_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, job_dir / "config.yaml")
        builders = _build_trajectory(paths, spec.layers, config)
        _write_trajectory(job_dir / "trajectory.csv", builders)
        faces, area = _write_target(job_dir / "target.stl", paths, spec.layers, config)
        row_count = sum(len(builder.rows) for builder in builders.values())
        print(
            f"{spec.number:02d} {spec.name}: {spec.description}; "
            f"layers={spec.layers}, paths={len(paths)}, rows={row_count}, "
            f"footprint={area:.2f} mm2, faces={faces}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="WAAM_Validator repository root containing config.yaml",
    )
    args = parser.parse_args()
    generate_jobs(args.repo_root.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
