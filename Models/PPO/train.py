"""Train PPO: python -m Models.PPO.train --total-timesteps 100000."""

from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .common import (
        DEFAULT_JOB,
        DEFAULT_RUNS,
        create_run_directory,
        make_env,
        positive_float,
        positive_int,
        probability,
        resolve_job,
        write_json,
    )
else:
    from common import (
        DEFAULT_JOB,
        DEFAULT_RUNS,
        create_run_directory,
        make_env,
        positive_float,
        positive_int,
        probability,
        resolve_job,
        write_json,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train SB3 PPO on the WAAM Gymnasium environment.")
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--output", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--total-timesteps", type=positive_int, default=100_000)
    parser.add_argument("--max-steps", type=positive_int, default=128)
    parser.add_argument("--movement-step-mm", type=positive_float, default=10.0)
    parser.add_argument("--learning-rate", type=positive_float, default=3e-4)
    parser.add_argument("--n-steps", type=positive_int, default=1024)
    parser.add_argument("--batch-size", type=positive_int, default=64)
    parser.add_argument("--n-epochs", type=positive_int, default=10)
    parser.add_argument("--gamma", type=probability, default=0.99)
    parser.add_argument("--gae-lambda", type=probability, default=0.95)
    parser.add_argument("--clip-range", type=probability, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu", help="cpu, cuda, or auto")
    parser.add_argument("--eval-freq", type=positive_int, default=5000)
    parser.add_argument("--eval-episodes", type=positive_int, default=3)
    parser.add_argument("--checkpoint-freq", type=positive_int, default=10000)
    parser.add_argument("--tensorboard", action="store_true", help="Requires tensorboard")
    parser.add_argument("--skip-env-check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.n_steps < 2 or args.batch_size < 2:
        parser.error("--n-steps and --batch-size must both be at least 2")
    if args.batch_size > args.n_steps or args.n_steps % args.batch_size:
        parser.error("--batch-size must divide --n-steps without a remainder")
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    try:
        job = resolve_job(args.job)
    except FileNotFoundError as exc:
        parser.error(str(exc))

    import gymnasium
    import stable_baselines3
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.logger import configure

    settings = {
        "job_dir": str(job),
        "max_steps": args.max_steps,
        "movement_step_mm": args.movement_step_mm,
    }
    ppo_settings = {
        "learning_rate": args.learning_rate,
        "n_steps": args.n_steps,
        "batch_size": args.batch_size,
        "n_epochs": args.n_epochs,
        "gamma": args.gamma,
        "gae_lambda": args.gae_lambda,
        "clip_range": args.clip_range,
        "policy_kwargs": {"net_arch": {"pi": [128, 128], "vf": [128, 128]}},
    }
    train_env = eval_env = None
    try:
        if not args.skip_env_check:
            probe = make_env(settings, seed=args.seed)
            try:
                check_env(probe.unwrapped, warn=True)
            finally:
                probe.close()

        run_dir = create_run_directory(args.output)
        write_json(run_dir / "config.json", {
            "environment": settings,
            "ppo": ppo_settings,
            "seed": args.seed,
            "total_timesteps": args.total_timesteps,
            "device": args.device,
            "eval_freq": args.eval_freq,
            "eval_episodes": args.eval_episodes,
            "checkpoint_freq": args.checkpoint_freq,
            "versions": {
                "stable_baselines3": stable_baselines3.__version__,
                "gymnasium": gymnasium.__version__,
            },
        })
        train_env = make_env(settings, seed=args.seed, monitor_path=run_dir / "train")
        eval_env = make_env(settings, seed=args.seed + 1, monitor_path=run_dir / "eval")
        callbacks = [
            CheckpointCallback(
                save_freq=args.checkpoint_freq,
                save_path=str(run_dir / "checkpoints"),
                name_prefix="ppo_waam",
            ),
            EvalCallback(
                eval_env,
                best_model_save_path=str(run_dir / "best"),
                log_path=str(run_dir / "evaluation"),
                eval_freq=args.eval_freq,
                n_eval_episodes=args.eval_episodes,
                deterministic=True,
            ),
        ]
        model = PPO("MlpPolicy", train_env, seed=args.seed, device=args.device,
                    verbose=1, **ppo_settings)
        log_formats = ["stdout", "csv"]
        if args.tensorboard:
            log_formats.append("tensorboard")
        model.set_logger(configure(str(run_dir / "logs"), log_formats))
        print(f"Run directory: {run_dir}", flush=True)
        try:
            model.learn(total_timesteps=args.total_timesteps, callback=callbacks)
        except KeyboardInterrupt:
            model.save(run_dir / "interrupted_model")
            print(f"Interrupted model saved: {run_dir / 'interrupted_model.zip'}")
            return 130
        model.save(run_dir / "final_model")
        print(f"Model saved: {run_dir / 'final_model.zip'}")
        return 0
    finally:
        if eval_env is not None:
            eval_env.close()
        if train_env is not None:
            train_env.close()


if __name__ == "__main__":
    raise SystemExit(main())
