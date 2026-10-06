"""Run: python -m models.sphere_ppo --timesteps 49152."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import torch
import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.monitor import Monitor

from environment.sphere_wrapper import SpherePPOEnv
from models import __version__
from models.tensorboard_reporting import ValidationTensorBoardCallback, write_evaluation

ROOT = Path(__file__).resolve().parents[1]


def write_csv(path, data):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(data)
        writer.writerows(zip(*data.values(), strict=True))


def rollout(model, env, *, seed=0, deterministic=True):
    obs, _ = env.reset(seed=seed)
    while True:
        action, _ = model.predict(obs, deterministic=deterministic)
        obs, _, done, _, info = env.step(int(action))
        if done:
            return info


def main():
    parser = argparse.ArgumentParser(prog="models.sphere_ppo", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--timesteps", type=int, default=49152)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "sphere_r-24mm_ppo")
    parser.add_argument("--model", type=Path, help="Evaluate an existing checkpoint without training")
    parser.add_argument("--tensorboard-log", type=Path, default=ROOT / "tensorboard",
                        help="TensorBoard root directory (default: ./tensorboard)")
    parser.add_argument("--run-name", default="sphere_ppo", help="TensorBoard run name")
    parser.add_argument("--no-tensorboard", action="store_true", help="Disable TensorBoard logging")
    args = parser.parse_args()
    tb_root = None if args.no_tensorboard else str(args.tensorboard_log.resolve())
    if tb_root is not None:
        try:
            import tensorboard  # noqa: F401
        except ImportError:
            parser.error("TensorBoard is missing: python -m pip install tensorboard; or use --no-tensorboard")
    output = args.output.resolve()
    job = output / "job"
    job.mkdir(parents=True, exist_ok=True)
    source = ROOT.parent / "Smooth Sphere - 115644" / "files" / "sphere_r-24mm.STL"
    shutil.copy2(source, job / "target.stl")
    config = yaml.safe_load((ROOT / "environment/examples/sample_job/config.yaml").read_text())
    config["validation"]["fail_on_speed_violation"] = True
    (job / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    torch.set_num_threads(2)
    started = time.monotonic()
    env = SpherePPOEnv(job)
    check_env(env, warn=True)
    monitor = Monitor(env, str(output / "training.monitor.csv"),
                      info_keywords=("success", "coverage", "overfill", "iou"))
    if args.model:
        model = PPO.load(args.model, env=monitor, device="cpu")
        baseline = None
        parameter_change = None
        run_dir = (str(Path(tb_root) / f"{args.run_name}_eval_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}")
                   if tb_root else None)
    else:
        model = PPO("MlpPolicy", monitor, learning_rate=3e-4, n_steps=1024,
                    batch_size=256, n_epochs=10, gamma=1.0, gae_lambda=.95,
                    ent_coef=.02, policy_kwargs={"net_arch": dict(pi=[64, 64], vf=[64, 64])},
                    seed=args.seed, device="cpu", verbose=1, tensorboard_log=tb_root)
        baseline = rollout(model, env)
        before = torch.cat([p.detach().flatten().clone() for p in model.policy.parameters()])
        model.learn(total_timesteps=args.timesteps, tb_log_name=args.run_name,
                    callback=ValidationTensorBoardCallback() if tb_root else None)
        run_dir = model.logger.dir if tb_root else None
        after = torch.cat([p.detach().flatten() for p in model.policy.parameters()])
        parameter_change = float(torch.linalg.vector_norm(after - before))
        model.logger.close()
    model.save(output / "ppo_sphere")
    # Export from a reloaded checkpoint, never substitute a hand-picked plan.
    model = PPO.load(output / "ppo_sphere.zip", device="cpu")
    evaluation = rollout(model, env, seed=2026)
    chosen = list(env.selected)
    write_csv(job / "trajectory.csv", env.get_trajectory())
    write_csv(output / "trajectory_robot_modes.csv", env.get_trajectory(preserve_finish=True))
    (output / "selected_actions.json").write_text(json.dumps([
        {"layer": layer, "robot_id": layer % 3 + 1, "action": a,
         "inset_mm": env.parameters[a][0], "infill_spacing_mm": env.parameters[a][1]}
        for layer, a in zip(env.indices, chosen, strict=True)], indent=2), encoding="utf-8")
    stochastic = [rollout(model, env, seed=i, deterministic=False)["success"] for i in range(100)]
    summary = {"project_version": __version__, "tensorboard_run": run_dir,
               "algorithm": "Stable-Baselines3 PPO", "seed": args.seed,
               "training_timesteps": model.num_timesteps, "baseline": baseline,
               "deterministic_evaluation": evaluation,
               "stochastic_shape_and_cached_safety_passes": sum(stochastic),
               "stochastic_evaluation_episodes": len(stochastic),
               "parameter_change_l2": parameter_change,
               "target_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "elapsed_seconds": time.monotonic() - started,
               "policy_scope": "Layer inset/infill selection; deterministic path compiler and serial scheduling",
               "makespan_weight": 0.0,
               "dependencies": {name: importlib.metadata.version(name) for name in
                                ("torch", "stable-baselines3", "gymnasium", "numpy",
                                 "trimesh", "shapely", "mapbox-earcut", "manifold3d")}}
    (output / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # A fresh process imports the standalone validator, not the environment copy.
    result = subprocess.run([sys.executable, str(ROOT / "models/validate_sphere.py"),
                             str(job), str(output / "validation")], cwd=ROOT)
    if run_dir is not None:
        artifact_path = output / "artifact_verification.json"
        artifact = (json.loads(artifact_path.read_text(encoding="utf-8"))
                    if result.returncode == 0 and artifact_path.exists() else None)
        write_evaluation(run_dir, model.num_timesteps, evaluation,
                         sum(stochastic) / len(stochastic), artifact=artifact)
        if result.returncode != 0:
            from torch.utils.tensorboard import SummaryWriter
            with SummaryWriter(str(Path(run_dir) / "evaluation")) as writer:
                writer.add_scalar("independent_validation/export_or_validation_failed", 1, model.num_timesteps)
    print(json.dumps(summary, indent=2), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
