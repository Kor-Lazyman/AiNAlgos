"""Independent binary checks for DRL rewards, without CSV/JSON output.

Run Python from Project_version_0.0.2 and import this module::

    from environment.env import check_collision, check_shape, check_validation

    safe = check_collision(trajectory_dict)  # 1 = no enabled collision found
    shape_ok = check_shape(trajectory_df)    # 1 = shape thresholds passed
    valid = check_validation(trajectory_dict)  # 1 = trajectory rules passed

Every public check returns a Python int: 1 for pass, 0 for fail or invalid input.
No report dictionaries, JSON, CSV, logs, or output folders are generated. Combine
the three independent flags in the caller's reward function as needed.

Input keys/columns: robot_id, time_s, x_mm, y_mm, z_mm, mode. Dictionary
values must be lists, tuples, or one-dimensional arrays, not single rows.
DataFrame column order and its index are ignored; row order is preserved.
Rows must be sorted by robot_id/time_s, all three robots need at least two rows,
and each starts at time 0. Pass the accumulated trajectory up to the current
step. Unlike a completed CSV job, its last row may use T, D, or W: this allows
reward checks during an episode. The last row has no outgoing interval yet.
These checks do not decide episode termination or require all robots to be W.

The default fixed job is environment/examples/sample_job. Pass job_dir=...
to choose another config.yaml/target.stl pair. Collision and trajectory validity
need only config.yaml; shape checking also needs target.stl. No trajectory.csv
is read or written and no output directory is created. Inputs are not mutated.

Install the existing environment dependencies first. pandas is needed only for
DataFrame inputs (python -m pip install pandas); dictionary inputs need no pandas.
DataFrame conversion uses to_dict(orient="list"):
https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_dict.html

The existing XY capsule/TCP geometry, deposition model and shape thresholds are
reused unchanged. A shape pass alone does not imply collision-free motion.
This module provides evaluation functions, not Gymnasium reset()/step().
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Set, Sized
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

# Select this version's backend when running directly from the checkout.
_SOURCE_DIR = Path(__file__).resolve().parent / "src"
_loaded_backend = sys.modules.get("waam_validator")
if _loaded_backend is not None:
    _backend_file = getattr(_loaded_backend, "__file__", None)
    if _backend_file is None or not Path(_backend_file).resolve().is_relative_to(_SOURCE_DIR):
        raise ImportError(
            "waam_validator is already loaded from another folder. "
            "Import environment.env in a fresh Python process for version 0.0.2."
        )
if str(_SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIR))

from waam_validator.collision.simulator import run_collision_analysis  # noqa: E402
from waam_validator.config.loader import load_config  # noqa: E402
from waam_validator.constants import CSV_COLUMNS, MODE_FROM_TEXT, ROBOT_IDS  # noqa: E402
from waam_validator.errors import InputValidationError, WaamValidatorError  # noqa: E402
from waam_validator.models import RobotTrajectory, TrajectorySet  # noqa: E402
from waam_validator.shape.deposition import build_deposited_layers  # noqa: E402
from waam_validator.shape.metrics import compute_shape_metrics  # noqa: E402
from waam_validator.shape.target import (  # noqa: E402
    determine_evaluation_layers,
    load_target_mesh,
    slice_target_layers,
    validate_coordinate_consistency,
)
from waam_validator.trajectory.validator import validate_trajectory_set  # noqa: E402

DEFAULT_JOB_DIR = Path(__file__).resolve().parent / "examples" / "sample_job"
__all__ = ["DEFAULT_JOB_DIR", "check_collision", "check_shape", "check_validation"]


def _load_trajectory(data: Mapping[str, Any] | pd.DataFrame) -> TrajectorySet:
    """Apply structural checks to accumulated, possibly unfinished trajectories."""
    if isinstance(data, Mapping):
        raw_columns = data
    else:
        try:
            import pandas as pd
        except ModuleNotFoundError as exc:
            raise InputValidationError(
                "INVALID_INPUT_TYPE", "Expected a column dictionary or pandas DataFrame."
            ) from exc
        if not isinstance(data, pd.DataFrame):
            raise InputValidationError(
                "INVALID_INPUT_TYPE", "Expected a column dictionary or pandas DataFrame."
            )
        if not data.columns.is_unique:
            raise InputValidationError("INVALID_COLUMNS", "DataFrame columns must be unique.")
        raw_columns = data.to_dict(orient="list")

    if set(raw_columns) != set(CSV_COLUMNS):
        raise InputValidationError(
            "INVALID_COLUMNS", "Required columns are exactly: " + ", ".join(CSV_COLUMNS)
        )
    columns: dict[str, np.ndarray] = {}
    for name in CSV_COLUMNS:
        values = raw_columns[name]
        if (
            isinstance(values, (str, bytes, bytearray, Mapping, Set))
            or not isinstance(values, Iterable)
            or not isinstance(values, Sized)
        ):
            raise InputValidationError("INVALID_COLUMNS", f"{name} must be an ordered column.")
        column = np.asarray(list(values), dtype=object)
        if column.ndim != 1:
            raise InputValidationError("INVALID_COLUMNS", f"{name} must be one-dimensional.")
        columns[name] = column
    row_count = len(columns["robot_id"])
    if row_count == 0:
        raise InputValidationError("MISSING_ROBOT", "Trajectory has no data rows.")
    if any(len(column) != row_count for column in columns.values()):
        raise InputValidationError("INVALID_COLUMNS", "All columns must have the same length.")

    # Avoid silently truncating floating-point IDs or accepting booleans as IDs.
    if any(re.fullmatch(r"[+-]?\d+", str(value)) is None for value in columns["robot_id"]):
        raise InputValidationError("INVALID_ROBOT_ID", "robot_id must be integer 1, 2, or 3.")
    if any(not isinstance(value, str) or value not in MODE_FROM_TEXT for value in columns["mode"]):
        raise InputValidationError("INVALID_MODE", "mode must be exactly T, D, or W.")
    try:
        robot_ids = np.asarray(columns["robot_id"], dtype=np.int64)
        # String conversion preserves CSV semantics, e.g. True/complex are not numeric cells.
        numeric = np.asarray(
            [[str(value) for value in columns[name]]
             for name in ("time_s", "x_mm", "y_mm", "z_mm")],
            dtype=np.float64,
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise InputValidationError("NONFINITE_VALUE", f"Invalid numeric value: {exc}") from exc
    time_s, xyz64 = numeric[0], numeric[1:].T
    if not np.isfinite(numeric).all():
        raise InputValidationError("NONFINITE_VALUE", "Numeric columns must be finite.")
    if np.any(~np.isin(robot_ids, ROBOT_IDS)):
        raise InputValidationError("INVALID_ROBOT_ID", "robot_id must be one of 1, 2, and 3.")
    if not np.array_equal(np.lexsort((time_s, robot_ids)), np.arange(row_count)):
        raise InputValidationError(
            "UNSORTED_TRAJECTORY", "Rows must be sorted by robot_id and then time_s."
        )
    with np.errstate(over="ignore", invalid="ignore"):
        xyz32 = xyz64.astype(np.float32)
    if not np.isfinite(xyz32).all():
        raise InputValidationError("NONFINITE_VALUE", "Coordinates overflow float32.")
    modes = np.asarray([MODE_FROM_TEXT[value] for value in columns["mode"]], dtype=np.uint8)

    robots: list[RobotTrajectory] = []
    for robot_id in ROBOT_IDS:
        mask = robot_ids == robot_id
        if int(mask.sum()) < 2:
            raise InputValidationError(
                "MISSING_ROBOT", f"Robot {robot_id} must contain at least two rows."
            )
        robot_times = np.ascontiguousarray(time_s[mask], dtype=np.float64)
        if np.any(np.diff(robot_times) == 0):
            raise InputValidationError(
                "DUPLICATE_TIMESTAMP", f"Robot {robot_id} contains a duplicate timestamp."
            )
        if robot_times[0] != 0.0:
            raise InputValidationError(
                "FIRST_TIME_NOT_ZERO", f"Robot {robot_id} must start at time 0."
            )
        robot_modes = np.ascontiguousarray(modes[mask], dtype=np.uint8)
        robots.append(RobotTrajectory(
            robot_id=robot_id,
            time_s=robot_times,
            xyz_mm=np.ascontiguousarray(xyz32[mask], dtype=np.float32),
            mode=robot_modes,
        ))
    return TrajectorySet(robots=(robots[0], robots[1], robots[2]), row_count=row_count)


def check_collision(
    data: Mapping[str, Any] | pd.DataFrame,
    *,
    job_dir: str | Path = DEFAULT_JOB_DIR,
) -> int:
    """Return 1 for collision-free, 0 for collision/invalid input/error.

    Checks the complete supplied trajectory using enabled XY arm and TCP checks.
    Does not check shape, speed or reach. If both collision checks are disabled,
    a structurally valid trajectory passes.
    """
    try:
        trajectories = _load_trajectory(data)
        config = load_config(Path(job_dir).expanduser().resolve() / "config.yaml")
        collision = run_collision_analysis(trajectories, config)
        return int(not collision.events)
    except (WaamValidatorError, OSError, ValueError, TypeError, OverflowError):
        return 0


def check_shape(
    data: Mapping[str, Any] | pd.DataFrame,
    *,
    job_dir: str | Path = DEFAULT_JOB_DIR,
) -> int:
    """Return 1 when shape thresholds pass, 0 for a shape failure/error.

    Fatal deposition errors also fail. Non-fatal speed/wait/reach findings do
    not determine this shape-only result. No collision simulation is performed.
    """
    try:
        trajectories = _load_trajectory(data)
        job = Path(job_dir).expanduser().resolve()
        config = load_config(job / "config.yaml")
        messages = validate_trajectory_set(trajectories, config)
        mesh = load_target_mesh(job / "target.stl", config, messages)
        validate_coordinate_consistency(trajectories, mesh, config)
        deposited = build_deposited_layers(trajectories, config)
        indices = determine_evaluation_layers(mesh, deposited, config)
        target = slice_target_layers(mesh, indices, config, messages)
        shape, _ = compute_shape_metrics(
            deposited, target, config, target_mesh_volume_mm3=float(abs(mesh.volume))
        )
        return int(shape.passed)
    except (WaamValidatorError, OSError, ValueError, TypeError, OverflowError):
        return 0


def check_validation(
    data: Mapping[str, Any] | pd.DataFrame,
    *,
    job_dir: str | Path = DEFAULT_JOB_DIR,
) -> int:
    """Return 1 for valid trajectory/process rules, otherwise 0.

    Checks columns, times, modes, wait movement, deposition layers/workspace,
    reach and configured speed rules. Warnings alone do not fail validation;
    speed violations fail only when fail_on_speed_violation is enabled.
    Does not run collision or target-shape checking. Does not require target.stl.
    """
    try:
        trajectories = _load_trajectory(data)
        config = load_config(Path(job_dir).expanduser().resolve() / "config.yaml")
        messages = validate_trajectory_set(trajectories, config)
        return int(not messages.violations)
    except (WaamValidatorError, OSError, ValueError, TypeError, OverflowError):
        return 0
