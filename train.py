"""Train PPO to generate robot XYZ/mode trajectories for sampled STL targets."""
from __future__ import annotations

import argparse
import csv
import copy
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import torch
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.monitor import Monitor

from environment.trajectory_env import TrajectoryPPOEnv
from environment.stroke_wrapper import StrokePPOEnv
from environment.residual_wrapper import ResidualStrokeEnv
from environment.sampled_ppo_wrapper import SampledWaamPPOEnv
from models import __version__
from models.episode_ppo import EpisodePPO, LinearLearningRate
from models.terminal_rewards import TerminalRewards
from models.tensorboard_reporting import ValidationTensorBoardCallback, write_evaluation

ROOT = Path(__file__).resolve().parent


def resolve_device(requested):
    """Prefer CUDA by default; never silently fall back for explicit CUDA."""
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError("device must be auto, cpu, or cuda")
    if requested == "cpu":
        return "cpu"
    available = torch.cuda.is_available()
    if requested == "cuda" and not available:
        raise ValueError("CUDA is unavailable in this Python environment. Check the NVIDIA driver "
                         "and CUDA-enabled PyTorch, or explicitly use --device cpu.")
    return "cuda" if available else "cpu"


def create_run_directory(output_root):
    """Atomically reserve max(existing trainN directories) + 1, starting at 1."""
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    numbers = [int(match.group(1)) for path in output_root.iterdir()
               if path.is_dir() and (match := re.fullmatch(r"train([0-9]+)", path.name))]
    number = max(numbers, default=0) + 1
    while True:
        run = output_root / f"train{number}"
        try:
            run.mkdir()
            return run
        except FileExistsError:
            number += 1


def write_csv(path, data):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(data)
        writer.writerows(zip(*data.values(), strict=True))


def rollout(model, env, *, seed=0, deterministic=True):
    # Environment seeding alone does not seed the policy's Gaussian sampling.
    devices = [model.device.index or 0] if model.device.type == "cuda" else []
    with torch.random.fork_rng(devices=devices):
        torch.manual_seed(seed)
        obs, _ = env.reset(seed=seed)
        while True:
            action, _ = model.predict(obs, deterministic=deterministic)
            obs, _, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                return info


def select_policy_rollout(model, env, eval_episodes):
    """Rank actual policy samples; never replace their coordinates or add F."""
    candidates, best = [], None
    for deterministic, seed in [(True, 2026), *[(False, i) for i in range(eval_episodes)]]:
        info = rollout(model, env, seed=seed, deterministic=deterministic)
        record = {"deterministic": deterministic, "seed": seed, "evaluation": info}
        candidates.append(record)
        rank = (bool(info["success"]), bool(info["validation_pass"] and info["collision_pass"]),
                float(info["iou"]), info["termination_reason"] == "finished")
        if best is None or rank > best[0]:
            best = (rank, record, copy.deepcopy(env.get_trajectory()),
                    copy.deepcopy(env.get_trajectory(preserve_finish=True)), copy.deepcopy(env.action_history))
    return best[1:], candidates


def discover_targets(job_dir):
    job_dir = Path(job_dir).expanduser().resolve()
    if not (job_dir / "config.yaml").is_file():
        raise ValueError(f"Missing input: {job_dir / 'config.yaml'}")
    targets = sorted((p for p in job_dir.iterdir() if p.is_file() and p.suffix.lower() == ".stl"),
                     key=lambda p: (p.name.casefold(), p.name))
    if not targets:
        raise ValueError(f"No STL files found in {job_dir}; put one or more *.stl files beside config.yaml")
    return targets


def policy_acceptance(artifact, evaluation):
    """Keep independent geometry checks separate from policy completion."""
    independent = artifact.get("independent_geometry_process_status", artifact["validation_status"])
    completed = evaluation["termination_reason"] == "finished"
    return {**artifact, "independent_geometry_process_status": independent,
            "policy_completed": completed, "policy_episode_success": bool(evaluation["success"]),
            "validation_status": "PASS" if independent == "PASS" and completed and evaluation["success"] else "FAIL"}


def evaluate_target(model, env, directory, source, run_dir, eval_episodes):
    """Always evaluate/export this target, independent of training sampling counts."""
    job = directory / "job"
    (selected, trajectory, modes, actions), candidates = select_policy_rollout(model, env, eval_episodes)
    evaluation = selected["evaluation"]
    write_csv(job / "trajectory.csv", trajectory)
    write_csv(directory / "trajectory_robot_modes.csv", modes)
    (directory / "policy_actions.json").write_text(json.dumps(actions, indent=2), encoding="utf-8")
    (directory / "policy_candidates.json").write_text(json.dumps({
        "selection": "success, process_and_collision_valid, nominal_iou, finished",
        "selected": selected, "candidates": candidates,
    }, indent=2), encoding="utf-8")
    stochastic = [candidate["evaluation"]["success"] for candidate in candidates[1:]]
    validation_command = [sys.executable, str(ROOT / "validate.py"), str(job), str(directory / "validation")]
    if hasattr(env, "terminal_rewards"):
        validation_command += ["--min-mesh-iou", str(env.terminal_rewards.min_mesh_iou)]
    result = subprocess.run(validation_command, cwd=ROOT)
    artifact_path = directory / "artifact_verification.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8")) if artifact_path.exists() else None
    if artifact is not None:
        artifact = policy_acceptance(artifact, evaluation)
        artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    if run_dir:
        evaluation_step = getattr(model, "completed_episodes", 0)
        write_evaluation(run_dir, evaluation_step, evaluation,
                         sum(stochastic) / len(stochastic), artifact=artifact)
        if result.returncode:
            from torch.utils.tensorboard import SummaryWriter
            with SummaryWriter(str(Path(run_dir) / "evaluation")) as writer:
                writer.add_scalar("independent_validation/export_or_validation_failed", 1, evaluation_step)
    summary = {"target_name": source.name, "target_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "config_sha256": hashlib.sha256((job / "config.yaml").read_bytes()).hexdigest(),
               "action_count": evaluation["action_count"], "deterministic_evaluation": candidates[0]["evaluation"],
               "selected_evaluation": evaluation,
               "selected_policy_rollout": {"seed": selected["seed"], "deterministic": selected["deterministic"]},
               "stochastic_environment_passes": sum(stochastic),
               "stochastic_evaluation_episodes": len(stochastic),
               "validation_exit_code": result.returncode,
               "actual_mesh_comparison": artifact.get("mesh_comparison") if artifact else None,
               "generator": env.policy_interface,
               "status": "PASS" if result.returncode == 0 and evaluation["success"] else "FAIL",
               "result_directory": str(directory)}
    (directory / "evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(prog="train.py", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--episodes", type=int, default=50000,
                        help="Stop PPO after exactly this many completed training episodes (default: 50000)")
    parser.add_argument("--makespan-iou-threshold", type=float, help="Actual mesh IoU required for speed bonus (residual; default .95)")
    parser.add_argument("--makespan-weight", type=float, help="Maximum speed bonus in PPO reward units (residual; default 1)")
    parser.add_argument("--makespan-reference-seconds", type=float, help="Time reference; default computed from target and process")
    parser.add_argument("--validation-bonus", type=float, help="Terminal validation PASS bonus in PPO units (residual; default 10)")
    parser.add_argument("--validation-min-mesh-iou", type=float, help="Actual mesh IoU acceptance threshold (residual; default .95)")
    parser.add_argument("--learning-rate", type=float, default=3e-3,
                        help="Initial PPO learning rate (default: 3e-3)")
    parser.add_argument("--final-learning-rate", type=float, default=1e-5,
                        help="Final learning rate; linear decay by completed episodes (default: 1e-5)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto",
                        help="PPO training and inference device; auto prefers CUDA (default)")
    parser.add_argument("--job-dir", type=Path, required=True,
                        help="Input directory containing config.yaml and one or more STL files")
    parser.add_argument("--eval-episodes", type=int, default=10,
                        help="Stochastic evaluation episodes per STL (default: 10)")
    parser.add_argument("--max-steps", type=int, default=512,
                        help="Maximum policy actions per episode, unrelated to layer count")
    parser.add_argument("--control", choices=("residual", "stroke", "direct"), default=None,
                        help="Residual-guided policy segments (default), legacy stroke segments, or simultaneous raw XYZ/modes")
    parser.add_argument("--collision-penalty", type=float, default=None,
                        help="Raw per-action penalty; default 2 for stroke, 50 for legacy direct")
    parser.add_argument("--grid-size", type=int, default=12,
                        help="Observation grid resolution per axis (4..32)")
    parser.add_argument("--rollout-steps", type=int, default=1024,
                        help="Minimum actions per complete-episode MC rollout; stop at episode limit (default: 1024)")
    parser.add_argument("--output", type=Path, default=ROOT / "output",
                        help="Output parent directory; creates the next trainN inside (default: ./output)")
    parser.add_argument("--model", type=Path, help="Evaluate an existing checkpoint without training")
    parser.add_argument("--tensorboard-log", type=Path,
                        help="Override TensorBoard directory (default: run/tensorboard)")
    parser.add_argument("--run-name", default=None, help="TensorBoard run name; defaults to input job name")
    parser.add_argument("--no-tensorboard", action="store_true", help="Disable TensorBoard logging")
    args = parser.parse_args()
    if args.control is None:
        if args.model:
            checkpoint = EpisodePPO.load(args.model, device="cpu")
            args.control = {(6,): "residual", (7,): "stroke", (3, 4): "direct"}.get(checkpoint.action_space.shape)
            if args.control is None:
                parser.error("Unknown checkpoint action interface")
            del checkpoint
        else:
            args.control = "residual"
    if args.collision_penalty is None:
        args.collision_penalty = 50. if args.control == "direct" else 2.
    env_class = {"residual": ResidualStrokeEnv, "stroke": StrokePPOEnv, "direct": TrajectoryPPOEnv}[args.control]
    terminal_options = {"makespan_iou_threshold": args.makespan_iou_threshold,
                        "makespan_weight": args.makespan_weight,
                        "reference_seconds": args.makespan_reference_seconds,
                        "validation_bonus": args.validation_bonus,
                        "min_mesh_iou": args.validation_min_mesh_iou}
    terminal_options = {k: v for k, v in terminal_options.items() if v is not None}
    if args.control != "residual" and terminal_options:
        parser.error("Makespan/validation reward options require --control residual")
    try:
        terminal_settings = TerminalRewards(**terminal_options) if args.control == "residual" else None
    except ValueError as exc:
        parser.error(str(exc))
    source_job = args.job_dir.expanduser().resolve()
    try:
        sources = discover_targets(source_job)
    except ValueError as exc:
        parser.error(str(exc))
    if args.episodes < 1 or args.eval_episodes < 1:
        parser.error("--episodes and --eval-episodes must be positive")
    if not (math.isfinite(args.learning_rate) and math.isfinite(args.final_learning_rate)
            and 0 < args.final_learning_rate <= args.learning_rate):
        parser.error("Require finite learning rates with 0 < --final-learning-rate <= --learning-rate")
    if args.max_steps < 1 or not 4 <= args.grid_size <= 32 or args.rollout_steps < 2:
        parser.error("--max-steps >= 1, --grid-size in [4,32], --rollout-steps >= 2 required")
    if not math.isfinite(args.collision_penalty) or not 0 <= args.collision_penalty <= torch.finfo(torch.float32).max / 2:
        parser.error("--collision-penalty must be finite, non-negative and fit float32 rewards")
    try:
        device = resolve_device(args.device)
    except ValueError as exc:
        parser.error(str(exc))
    device_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU"
    print(f"PPO device: {device} ({device_name})", flush=True)
    args.run_name = args.run_name or source_job.name
    if not args.no_tensorboard:
        try:
            import tensorboard  # noqa: F401
        except ImportError:
            parser.error("TensorBoard is missing: python -m pip install tensorboard; or use --no-tensorboard")
    output = create_run_directory(args.output)
    model_dir = output / "model"
    result_dir = output / "result"
    for directory in (model_dir, result_dir, output / "tensorboard"):
        directory.mkdir()
    tb_root = (None if args.no_tensorboard else
               str(args.tensorboard_log.expanduser().resolve() if args.tensorboard_log
                   else output / "tensorboard"))
    print(f"Run directory: {output}", flush=True)
    torch.set_num_threads(2)
    started = time.monotonic()
    environments, directories, target_ids = [], [], []
    manifest = []
    for index, source in enumerate(sources):
        target_id = f"{index + 1:03d}_{re.sub(r'[^A-Za-z0-9_-]', '_', source.stem)}"
        directory = result_dir if len(sources) == 1 else result_dir / "targets" / target_id
        job = directory / "job"
        job.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, job / "target.stl")
        shutil.copy2(source_job / "config.yaml", job / "config.yaml")
        print(f"Preparing target {index + 1}/{len(sources)}: {source.name}", flush=True)
        try:
            target_env = env_class(job, max_steps=args.max_steps, grid_size=args.grid_size,
                                  collision_penalty=args.collision_penalty,
                                  **({"terminal_rewards": terminal_settings} if terminal_settings else {}))
            check_env(target_env, warn=True)
        except Exception as exc:
            raise RuntimeError(f"Failed to prepare STL {source.name}: {exc}") from exc
        environments.append(target_env)
        directories.append(directory)
        target_ids.append(target_id)
        manifest.append({"target_index": index, "target_id": target_id, "source": str(source),
                         "result_directory": str(directory)})
    (result_dir / "targets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    env = SampledWaamPPOEnv(environments, [p.name for p in sources])
    check_env(env, warn=True)
    monitor = Monitor(env, str(result_dir / "training.monitor.csv"),
                      info_keywords=("success", "coverage", "overfill", "iou", "target_index", "target_name",
                                     "collision_pass", "reward_collision", "episode_reward_collision", "collision_steps",
                                     "similarity_percent", "reward_similarity", "episode_reward_shape",
                                     "episode_reward_process", "reward_incomplete") +
                                    (("invalid_process_steps", "deposition_commands", "early_finish")
                                     if args.control != "direct" else ()) +
                                    (("episode_reward_overfill", "duplicate_steps", "finish_ready", "makespan_s",
                                      "reward_makespan", "reward_validation_bonus", "terminal_validation_pass", "terminal_mesh_iou")
                                     if args.control == "residual" else ()))
    if args.model:
        try:
            model = EpisodePPO.load(args.model, env=monitor, device=device)
        except ValueError as exc:
            parser.error(f"Checkpoint is incompatible with selected control or grid size. "
                         f"Old layer-choice checkpoints cannot be used. Details: {exc}")
        baseline = None
        parameter_change = None
        run_dir = (str(Path(tb_root) / f"{args.run_name}_eval_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}")
                   if tb_root else None)
    else:
        model = EpisodePPO("MultiInputPolicy", monitor,
                    learning_rate=LinearLearningRate(args.learning_rate, args.final_learning_rate), n_steps=args.rollout_steps,
                    batch_size=min(256, args.rollout_steps), n_epochs=10, gamma=1.0, gae_lambda=1.0,
                    ent_coef=.02 if args.control == "direct" else .005, target_kl=.02,
                    policy_kwargs={"net_arch": dict(pi=[64, 64], vf=[64, 64]),
                                   "log_std_init": 0. if args.control == "direct" else -.7},
                    seed=args.seed, device=device, verbose=1, tensorboard_log=tb_root)
        if args.control != "direct":
            # A nonzero segment at initialization; no STL-specific demonstration.
            # Endpoints, robot and finish remain policy outputs. The residual
            # controller supplies the height; legacy stroke also learns height.
            with torch.no_grad():
                initial = [-.5, 0., .5, 0., 0., 0.] if args.control == "residual" else [-.5, 0., .5, 0., 0., 0., 0.]
                model.policy.action_net.bias.copy_(torch.tensor(initial, device=model.device))
        model.policy_interface = env_class.policy_interface
        model.training_collision_penalty = args.collision_penalty
        model.training_learning_rate_initial = args.learning_rate
        model.training_learning_rate_final = args.final_learning_rate
        model.training_episode_end_rule = "all_F_or_max_steps"
        model.training_collision_penalty_mode = "per_colliding_action"
        model.training_reward_scheme = env_class.reward_scheme
        model.training_reward_scale = env_class.reward_scale
        model.training_terminal_rewards = asdict(terminal_settings) if terminal_settings else None
        baseline = {p.name: rollout(model, target_env)
                    for p, target_env in zip(sources, environments, strict=True)}
        env.episode_counts.fill(0)
        before = torch.cat([p.detach().flatten().clone() for p in model.policy.parameters()])
        model.learn_episodes(total_episodes=args.episodes, tb_log_name=args.run_name,
                    callback=ValidationTensorBoardCallback() if tb_root else None)
        run_dir = model.logger.dir if tb_root else None
        after = torch.cat([p.detach().flatten() for p in model.policy.parameters()])
        parameter_change = float(torch.linalg.vector_norm(after - before))
        model.logger.close()
    training_counts = env.episode_counts.tolist() if not args.model else [0] * len(sources)
    model.save(model_dir / "ppo_model")
    (model_dir / "policy_contract.json").write_text(json.dumps({
        "interface": env_class.policy_interface, "grid_size": args.grid_size, "max_steps": args.max_steps,
        "control": args.control, "action_shape": list(env.action_space.shape),
        "mode_bins": ({"T": [-1, -.8], "D": [-.8, .6], "W": [.6, .9], "F": [.9, 1]}
                      if args.control != "direct" else {"T": [-1, -.5], "D": [-.5, 0], "W": [0, .5], "F": [.5, 1]}),
        "action_coordinates": ("[start_dx,start_dy,end_dx,end_dy,robot,command]; residual-region hint and height from geometry; policy XY endpoints; explicit T/D/T execution"
                               if args.control == "residual" else "[start_x,start_y,end_x,end_y,height,robot,command]; target-local XY, process-grid height; explicit T/D/T execution"
                               if args.control == "stroke" else "Normalized absolute XYZ within xyz_low/high"),
        "observation_keys": list(env.observation_space.spaces),
        "trained_advantage_estimator": getattr(model, "trained_advantage_estimator", "unknown_legacy"),
        "training_collision_penalty": getattr(model, "training_collision_penalty", None),
        "training_progress_unit": "completed_episode",
        "training_completed_episodes": getattr(model, "completed_episodes", None),
        "training_episode_end_rule": getattr(model, "training_episode_end_rule", None),
        "training_collision_penalty_mode": getattr(model, "training_collision_penalty_mode", None),
        "training_reward_scheme": getattr(model, "training_reward_scheme", None),
        "training_reward_scale": getattr(model, "training_reward_scale", None),
        "training_terminal_rewards": getattr(model, "training_terminal_rewards", None),
        "evaluation_terminal_rewards": asdict(terminal_settings) if terminal_settings else None,
    }, indent=2), encoding="utf-8")
    # Export from a reloaded checkpoint, never substitute a hand-picked plan.
    model = EpisodePPO.load(model_dir / "ppo_model.zip", device=device)
    reports = []
    for source, target_env, directory, target_id in zip(sources, environments, directories, target_ids, strict=True):
        target_log = (str(Path(run_dir) / "targets" / target_id) if run_dir else None)
        reports.append(evaluate_target(model, target_env, directory, source, target_log, args.eval_episodes))
    summary = {
        "project_version": __version__, "tensorboard_run": run_dir,
        "run_directory": str(output), "model_path": str(model_dir / "ppo_model.zip"),
        "input_job": str(source_job), "algorithm": "Stable-Baselines3 PPO", "seed": args.seed,
        "trained_advantage_estimator": getattr(model, "trained_advantage_estimator", "unknown_legacy"),
        "gamma": model.gamma, "gae_lambda": model.gae_lambda, "rollout_steps": model.n_steps,
        "training_progress_unit": "completed_episode",
        "training_target_episodes": getattr(model, "target_episodes", None),
        "training_completed_episodes": getattr(model, "completed_episodes", None),
        "training_finished_episodes": getattr(model, "finished_episodes", None),
        "training_truncated_episodes": getattr(model, "truncated_episodes", None),
        "training_learning_rate_initial": getattr(model, "training_learning_rate_initial", None),
        "training_learning_rate_final": getattr(model, "training_learning_rate_final", None),
        "optimizer_learning_rate": model.policy.optimizer.param_groups[0]["lr"],
        "training_collision_penalty": getattr(model, "training_collision_penalty", None),
        "evaluation_collision_penalty": args.collision_penalty,
        "evaluation_episode_end_rule": "all_F_or_max_steps",
        "evaluation_collision_penalty_mode": "per_colliding_action",
        "evaluation_reward_scheme": env_class.reward_scheme,
        "evaluation_reward_scale": env_class.reward_scale,
        "training_terminal_rewards": getattr(model, "training_terminal_rewards", None),
        "evaluation_terminal_rewards": asdict(terminal_settings) if terminal_settings else None,
        "makespan_reference_seconds_per_target": {source.name: env.makespan_reference_s for source, env in zip(sources, environments)},
        "training_reward_scheme": getattr(model, "training_reward_scheme", None),
        "training_episode_end_rule": getattr(model, "training_episode_end_rule", None),
        "training_collision_penalty_mode": getattr(model, "training_collision_penalty_mode", None),
        "device_requested": args.device, "device": str(model.device), "device_name": device_name,
        "sampling": "Uniform random STL selection per episode using Gymnasium seeded RNG",
        "training_episodes_per_target": dict(zip([p.name for p in sources], training_counts, strict=True)),
        "training_timesteps": model.num_timesteps, "baseline": baseline,
        "policy_interface": env_class.policy_interface, "control": args.control,
        "max_steps": args.max_steps, "grid_size": args.grid_size,
        "parameter_change_l2": parameter_change, "makespan_weight": terminal_settings.makespan_weight if terminal_settings else 0.,
        "elapsed_seconds": time.monotonic() - started, "targets": reports,
        "status": "PASS" if all(r["status"] == "PASS" for r in reports) else "FAIL",
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("torch", "stable-baselines3", "gymnasium", "numpy",
                          "trimesh", "shapely", "mapbox-earcut", "manifold3d")},
    }
    if len(reports) == 1:
        summary.update(reports[0])
    (result_dir / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    monitor.close()
    print(json.dumps(summary, indent=2), flush=True)
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
