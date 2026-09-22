"""Generate deterministic synthetic WAAM validation jobs."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import trimesh
import yaml
from shapely import LineString, set_precision

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
BASES = {
    1: (-1000.0, -600.0, 0.0),
    2: (1000.0, -600.0, 0.0),
    3: (0.0, 1200.0, 0.0),
}
CSV_HEADER = ("robot_id", "time_s", "x_mm", "y_mm", "z_mm", "mode")


def config(
    *,
    arm_enabled: bool = True,
    include_home: bool = False,
    workspace_radius_mm: float = 500.0,
) -> dict[str, object]:
    return {
        "simulation": {
            "max_time_step_s": 0.1,
            "max_tcp_step_mm": 5.0,
            "event_merge_gap_s": 0.2,
            "batch_size": 10000,
        },
        "robots": [
            {
                "id": robot_id,
                "base_xyz_mm": list(base),
                **({"home_xyz_mm": [base[0], base[1], 1000.0]} if include_home else {}),
                "tcp_radius_mm": 20.0,
                "arm_envelope_radius_mm": 100.0,
                "xy_reach_radius_mm": 2500.0,
            }
            for robot_id, base in BASES.items()
        ],
        "process": {
            "deposition_speed_mm_s": 8.0,
            "travel_speed_mm_s": 150.0,
            "layer_height_mm": 2.0,
            "bead_width_mm": 4.0,
            "build_plane_z_mm": 0.0,
            "tcp_z_reference": "top",
        },
        "workspace": {
            "shape": "circle_xy",
            "center_xy_mm": [0.0, 0.0],
            "radius_mm": workspace_radius_mm,
        },
        "collision": {
            "check_arm_envelope": arm_enabled,
            "arm_clearance_mm": 50.0,
            "check_tcp_radius": True,
            "touching_is_collision": True,
            "geometry_epsilon_mm": 0.000001,
        },
        "validation": {
            "wait_position_tolerance_mm": 0.001,
            "layer_z_tolerance_mm": 0.25,
            "speed_relative_tolerance": 0.10,
            "fail_on_speed_violation": False,
            "require_watertight_target": True,
            "attempt_target_repair": False,
            "target_volume_discrepancy_warning_ratio": 0.02,
        },
        "shape_validation": {
            "polygon_buffer_resolution": 8,
            "polygon_snap_tolerance_mm": 0.0001,
            "minimum_overall_coverage": 0.95,
            "maximum_overall_overfill_ratio": 0.05,
            "minimum_overall_iou": 0.90,
            "minimum_layer_iou": 0.80,
            "maximum_failed_layer_ratio": 0.05,
            "area_epsilon_mm2": 0.000001,
        },
    }


def parked(robot_id: int, end_s: float) -> list[tuple[object, ...]]:
    x_value, y_value, z_value = BASES[robot_id]
    z_value = 100.0 if z_value == 0.0 else z_value
    return [
        (robot_id, 0.0, x_value, y_value, z_value, "W"),
        (robot_id, end_s, x_value, y_value, z_value, "W"),
    ]


def depositing_path(start_x: float, end_x: float) -> list[tuple[object, ...]]:
    base_x, base_y, _ = BASES[1]
    deposit_duration = abs(end_x - start_x) / 8.0
    deposit_end = 4.0 + deposit_duration
    finish = deposit_end + 4.0
    return [
        (1, 0.0, base_x, base_y, 100.0, "T"),
        (1, 4.0, start_x, 0.0, 2.0, "D"),
        (1, deposit_end, end_x, 0.0, 2.0, "T"),
        (1, finish, base_x, base_y, 100.0, "W"),
    ]


def standard_rows(start_x: float = -40.0, end_x: float = 40.0) -> list[tuple[object, ...]]:
    robot_one = depositing_path(start_x, end_x)
    end_s = float(robot_one[-1][1])
    return robot_one + parked(2, end_s) + parked(3, end_s)


def arm_cross_rows() -> list[tuple[object, ...]]:
    rows = depositing_path(-40.0, 40.0)
    rows += [
        (2, 0.0, 1000.0, -600.0, 100.0, "W"),
        (2, 6.0, 1000.0, -600.0, 100.0, "T"),
        (2, 8.0, -500.0, 100.0, 100.0, "W"),
        (2, 10.0, -500.0, 100.0, 100.0, "T"),
        (2, 12.0, 1000.0, -600.0, 100.0, "W"),
        (2, 18.0, 1000.0, -600.0, 100.0, "W"),
    ]
    rows += parked(3, 18.0)
    return rows


def tcp_radius_rows() -> list[tuple[object, ...]]:
    rows = depositing_path(-40.0, 40.0)
    rows += [
        (2, 0.0, 1000.0, -600.0, 100.0, "W"),
        (2, 6.0, 1000.0, -600.0, 100.0, "T"),
        (2, 8.0, -20.0, -35.0, 100.0, "W"),
        (2, 10.0, -20.0, -35.0, 100.0, "T"),
        (2, 12.0, 1000.0, -600.0, 100.0, "W"),
        (2, 18.0, 1000.0, -600.0, 100.0, "W"),
    ]
    rows += parked(3, 18.0)
    return rows


def time_separated_rows() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = [
        (1, 0.0, -1000.0, -600.0, 100.0, "T"),
        (1, 4.0, -40.0, 0.0, 2.0, "D"),
        (1, 14.0, 40.0, 0.0, 2.0, "T"),
        (1, 18.0, -1000.0, -600.0, 100.0, "W"),
        (1, 36.0, -1000.0, -600.0, 100.0, "W"),
        (2, 0.0, 1000.0, -600.0, 100.0, "W"),
        (2, 18.0, 1000.0, -600.0, 100.0, "T"),
        (2, 22.0, -40.0, 0.0, 2.0, "D"),
        (2, 32.0, 40.0, 0.0, 2.0, "T"),
        (2, 36.0, 1000.0, -600.0, 100.0, "W"),
    ]
    rows += parked(3, 36.0)
    return rows


def arm_envelope_near_miss_rows() -> list[tuple[object, ...]]:
    """Non-crossing centerlines whose endpoint Capsules violate 250 mm."""
    return [
        (1, 0.0, -1000.0, -600.0, 100.0, "T"),
        (1, 10.0, 0.0, -100.0, 100.0, "W"),
        (1, 20.0, 0.0, -100.0, 100.0, "W"),
        (2, 0.0, 1000.0, -600.0, 100.0, "T"),
        (2, 10.0, 0.0, 100.0, 100.0, "W"),
        (2, 20.0, 0.0, 100.0, 100.0, "W"),
        *parked(3, 20.0),
    ]


def write_target(path: Path) -> None:
    polygon = LineString([(-40.0, 0.0), (40.0, 0.0)]).buffer(
        2.0, quad_segs=8, cap_style="round", join_style="round"
    )
    polygon = set_precision(polygon, 0.0001)
    mesh = trimesh.creation.extrude_polygon(polygon, 2.0, engine="earcut")
    mesh.export(path, file_type="stl")


def write_job(
    name: str,
    rows: list[tuple[object, ...]],
    *,
    arm_enabled: bool = True,
) -> None:
    directory = FIXTURES / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "config.yaml").write_text(
        yaml.safe_dump(config(arm_enabled=arm_enabled), sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    with (directory / "trajectory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
    write_target(directory / "target.stl")


def main() -> None:
    write_job("collision_free", standard_rows())
    write_job("arm_cross", arm_cross_rows())
    write_job("tcp_radius", tcp_radius_rows(), arm_enabled=False)
    write_job("time_separated_crossing", time_separated_rows())
    write_job("arm_envelope_near_miss", arm_envelope_near_miss_rows())
    write_job("shape_underfill", standard_rows(-40.0, 20.0))
    write_job("shape_overfill", standard_rows(-50.0, 50.0))
    example = ROOT / "examples" / "sample_job"
    example.mkdir(parents=True, exist_ok=True)
    source = FIXTURES / "collision_free"
    for filename in ("trajectory.csv", "target.stl"):
        shutil.copyfile(source / filename, example / filename)
    (example / "config.yaml").write_text(
        yaml.safe_dump(
            config(include_home=True, workspace_radius_mm=250.0),
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
