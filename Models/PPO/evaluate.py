"""Evaluate a saved PPO policy using its training environment settings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev

if __package__:
    from .common import make_env, positive_int, resolve_job, write_json
else:
    from common import make_env, positive_int, resolve_job, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a saved WAAM PPO policy.")
    parser.add_argument("--model", required=True, type=Path, help="Path to a model .zip")
    parser.add_argument("--config", type=Path, help="Training config.json; normally auto-detected")
    parser.add_argument("--job", type=Path, help="Optional evaluation job override")
    parser.add_argument("--episodes", type=positive_int, default=5)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        parser.error(f"Model does not exist: {model_path}")
    config_path = args.config
    if config_path is None:
        config_path = next(
            (folder / "config.json" for folder in (model_path.parent, model_path.parent.parent)
             if (folder / "config.json").is_file()),
            None,
        )
    if config_path is None:
        parser.error("Could not find training config.json; provide --config")
    config = json.loads(config_path.expanduser().read_text(encoding="utf-8"))
    settings = dict(config["environment"])
    settings["job_dir"] = str(resolve_job(args.job or settings["job_dir"]))

    from stable_baselines3 import PPO

    env = make_env(settings, seed=args.seed)
    try:
        # Passing env verifies that the policy and environment spaces match.
        model = PPO.load(model_path, env=env, device=args.device)
        episodes = []
        for index in range(args.episodes):
            observation, _ = env.reset(seed=args.seed + index)
            total_reward = 0.0
            for step in range(settings["max_steps"]):
                action, _ = model.predict(observation, deterministic=True)
                observation, reward, terminated, truncated, info = env.step(action)
                total_reward += float(reward)
                if terminated or truncated:
                    break
            else:
                raise RuntimeError("Environment did not finish within its configured max_steps")
            episodes.append({
                "episode": index + 1,
                "reward": total_reward,
                "length": step + 1,
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "validation": {key: value for key, value in info.items() if key != "episode"},
            })
        rewards = [episode["reward"] for episode in episodes]
        report = {
            "model": str(model_path),
            "environment": settings,
            "seed": args.seed,
            "mean_reward": mean(rewards),
            "std_reward": pstdev(rewards),
            "pass_count": sum(ep["validation"].get("status") == "PASS" for ep in episodes),
            "validation_error_count": sum("validation_error" in ep["validation"] for ep in episodes),
            "episodes": episodes,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        if args.output:
            output = args.output.expanduser().resolve()
            if output.exists():
                parser.error(f"Report already exists; choose a new --output path: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            write_json(output, report)
    finally:
        env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
