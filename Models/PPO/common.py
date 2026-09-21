"""Shared paths, argument validation, and Gymnasium environment construction."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_ROOT = PROJECT_ROOT / "Environment"
DEFAULT_JOB = ENVIRONMENT_ROOT / "examples" / "sample_job"
DEFAULT_RUNS = Path(__file__).resolve().parent / "runs"


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def probability(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 1:
        raise argparse.ArgumentTypeError("must be in (0, 1]")
    return number


def resolve_job(path: str | Path) -> Path:
    job = Path(path).expanduser().resolve()
    for name in ("config.yaml", "target.stl"):
        if not (job / name).is_file():
            raise FileNotFoundError(f"Required job input does not exist: {job / name}")
    return job


def create_run_directory(root: Path) -> Path:
    name = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    run_dir = root.expanduser().resolve() / name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def make_env(settings: dict[str, Any], *, seed: int, monitor_path: Path | None = None):
    """Load this checkout's Environment, even if validator is also installed."""
    import gymnasium as gym
    from stable_baselines3.common.monitor import Monitor

    source = ENVIRONMENT_ROOT / "src"
    if not (source / "waam_validator" / "rl_env.py").is_file():
        raise FileNotFoundError(f"Missing environment source: {source}")
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    import waam_validator
    from waam_validator import WaamPPOEnv

    if not Path(waam_validator.__file__).resolve().is_relative_to(source.resolve()):
        raise RuntimeError(
            "waam_validator was already loaded from another folder. "
            "Run this trainer in a fresh Python process."
        )
    env: gym.Env = WaamPPOEnv(
        resolve_job(settings["job_dir"]),
        max_steps=settings["max_steps"],
        movement_step_mm=settings["movement_step_mm"],
        validate_each_step=False,
    )
    try:
        env.action_space.seed(seed)
        env.reset(seed=seed)
        return Monitor(env, filename=str(monitor_path) if monitor_path else None)
    except BaseException:
        env.close()
        raise
