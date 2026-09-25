"""Run: python -m models.learn --model ppo [--smoke-test]."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Also support `python models/learn.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gymnasium as gym
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.logger import HumanOutputFormat, Logger
from stable_baselines3.common.monitor import Monitor

from models.config import CONFIG, SMOKE_CONFIG, TrainConfig

MODEL_CLASSES = {"ppo": PPO}


def build_model(model_name: str, env: gym.Env, config: TrainConfig = CONFIG) -> PPO:
    """Build a model, preserving the wrapper's (3,5)/(3,4) spaces."""
    name = model_name.lower()
    if name not in MODEL_CLASSES:
        raise ValueError(f"Unsupported model {model_name!r}; supported: {tuple(MODEL_CLASSES)}")
    for key, value, minimum in (
        ("total_timesteps", config.total_timesteps, 1),
        ("torch_num_threads", config.torch_num_threads, 1),
        ("n_steps", config.ppo.n_steps, 2),
        ("batch_size", config.ppo.batch_size, 2),
        ("n_epochs", config.ppo.n_epochs, 1),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{key} must be an integer >= {minimum}")
    if config.ppo.n_steps % config.ppo.batch_size:
        raise ValueError("For this single-env trainer, batch_size must divide n_steps")
    for key in ("lr", "eps", "clip_range", "max_grad_norm"):
        value = getattr(config.ppo, key)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if config.check_env:
        # SB3 warns about the 2D Box. MlpPolicy's FlattenExtractor handles
        # the 15 values; keep the public three-robot observation intact.
        check_env(env, warn=True, skip_render_check=True)
    torch.set_num_threads(config.torch_num_threads)
    monitored = env if isinstance(env, Monitor) else Monitor(env, filename=None)
    model = MODEL_CLASSES[name](
        "MlpPolicy", monitored, **config.ppo.sb3_kwargs(),
        seed=config.seed, device=config.device, verbose=config.verbose,
    )
    # Console only: no monitor.csv, JSON, TensorBoard or default log directory.
    outputs = [HumanOutputFormat(sys.stdout)] if config.verbose else []
    model.set_logger(Logger(folder=None, output_formats=outputs))
    return model


def learn(
    model_name: str | None = None,
    env: gym.Env | None = None,
    config: TrainConfig = CONFIG,
    *,
    callback: BaseCallback | None = None,
) -> PPO:
    """Train and return PPO. Caller closes model.get_env() after using it.

    An explicit env/model_name overrides config's environment/model choice.
    No files are written; call save_model() explicitly for a checkpoint.
    SB3 rounds total_timesteps up to complete its rollout buffer.
    """
    owned_env = env is None
    training_env = config.make_env() if owned_env else env
    try:
        model = build_model(model_name or config.model_name, training_env, config)
        model.learn(total_timesteps=config.total_timesteps, callback=callback)
        return model
    except BaseException:
        if owned_env:
            training_env.close()
        raise


def save_model(model: PPO, output_dir: str | Path) -> Path:
    """Save one SB3 zip checkpoint with a unique name."""
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"ppo_{stamp}_{uuid4().hex[:8]}.zip"
    model.save(path)
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Train SB3 PPO on the three-robot WAAM environment")
    parser.add_argument("--model", type=str.lower, choices=MODEL_CLASSES, default=CONFIG.model_name)
    parser.add_argument("--smoke-test", action="store_true", help="64 steps using SMOKE_CONFIG")
    parser.add_argument("--timesteps", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--device")
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)
    config = SMOKE_CONFIG if args.smoke_test else CONFIG
    overrides = {"model_name": args.model}
    for argument, field in (("timesteps", "total_timesteps"), ("seed", "seed"),
                            ("device", "device"), ("output_dir", "output_dir")):
        if getattr(args, argument) is not None:
            overrides[field] = getattr(args, argument)
    env_kwargs = dict(config.env_kwargs)
    if args.job_dir is not None:
        env_kwargs["job_dir"] = args.job_dir
    if args.max_steps is not None:
        env_kwargs["max_steps"] = args.max_steps
    config = replace(config, env_kwargs=env_kwargs, **overrides)
    env = config.make_env()
    try:
        model = learn(config.model_name, env, config)
        print(f"Training complete: {model.num_timesteps} environment steps")
        if not args.no_save:
            print(f"Model saved: {save_model(model, config.output_dir)}")
    finally:
        env.close()


if __name__ == "__main__":
    main()
