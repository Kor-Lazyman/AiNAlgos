"""Episode-level logging, separate from SB3 rollout-averaged training metrics."""
from collections import deque
from pathlib import Path

from stable_baselines3.common.callbacks import BaseCallback


class ValidationTensorBoardCallback(BaseCallback):
    def __init__(self):
        super().__init__()
        self.recent_successes = deque(maxlen=100)
        self.episodes = 0
        self.writer = None

    def _on_training_start(self):
        if self.logger.dir is None:
            raise RuntimeError("TensorBoard callback requires an SB3 log directory")
        from torch.utils.tensorboard import SummaryWriter
        self.writer = SummaryWriter(str(Path(self.logger.dir) / "episodes"))
        self.writer.add_text("run/x_axis_unit", "eps: completed episodes. TensorBoard Step = eps; action_steps counts robot actions separately.", 0)

    def _on_step(self):
        for done, info in zip(self.locals["dones"], self.locals["infos"], strict=True):
            if not done:
                continue
            self.episodes += 1
            success = float(info["success"])
            self.recent_successes.append(success)
            values = {
                "episode/count": self.episodes,
                "progress/eps": self.episodes,
                "episode/reward": info["episode"]["r"],
                "episode/length": info["episode"]["l"],
                "episode/action_steps": self.num_timesteps,
                "validation/environment_success": success,
                "validation/environment_pass_rate_100": sum(self.recent_successes) / len(self.recent_successes),
                "shape/coverage": info["coverage"],
                "shape/overfill": info["overfill"],
                "shape/iou": info["iou"],
                "reward/makespan_weight": info["makespan_weight"],
            }
            for tag, value in values.items():
                self.writer.add_scalar(tag, value, self.episodes)
            if "reward_collision" in info:
                self.writer.add_scalar("reward/collision", info.get("episode_reward_collision", info["reward_collision"]), self.episodes)
            if "similarity_percent" in info:
                self.writer.add_scalar("shape/similarity_percent", info["similarity_percent"], self.episodes)
                self.writer.add_scalar("reward/similarity", info["reward_similarity"], self.episodes)
            for key in ("episode_reward_shape", "episode_reward_process", "reward_incomplete", "reward_terminal_adjustment", "episode_reward_overfill"):
                if key in info:
                    self.writer.add_scalar(f"reward/{key}", info[key], self.episodes)
            if "target_index" in info:
                self.writer.add_scalar("sampling/target_index", info["target_index"], self.episodes)
                self.writer.add_scalar(f"targets/{info['target_index']}/success", success, self.episodes)
            for key in ("action_count", "validation_pass", "collision_pass", "shape_pass", "collision_steps"):
                if key in info:
                    self.writer.add_scalar(f"trajectory/{key}", info[key], self.episodes)
            for key in ("deposition_commands", "invalid_process_steps", "early_finish", "reward_scale", "duplicate_steps", "finish_ready"):
                if key in info:
                    self.writer.add_scalar(f"diagnostics/{key}", info[key], self.episodes)
            for key in ("reward_makespan", "reward_validation_bonus"):
                if key in info:
                    self.writer.add_scalar(f"reward/{key}_ppo_units", info[key], self.episodes)
            for key in ("makespan_s", "makespan_reference_s", "terminal_validation_checked", "terminal_validation_pass",
                        "terminal_mesh_iou", "terminal_validation_seconds"):
                if key in info:
                    self.writer.add_scalar(f"terminal/{key}", info[key], self.episodes)
        return True

    def _on_training_end(self):
        if self.writer is not None:
            self.writer.close()


def write_evaluation(log_dir, step, evaluation, stochastic_pass_rate, *, artifact=None):
    """Final rollout/cached evaluation and optional independent validator result."""
    from torch.utils.tensorboard import SummaryWriter
    with SummaryWriter(str(Path(log_dir) / "evaluation")) as writer:
        for key in ("success", "coverage", "overfill", "iou"):
            writer.add_scalar(f"evaluation/{key}", float(evaluation[key]), step)
        for key in ("makespan_s", "reward_makespan", "reward_validation_bonus", "terminal_mesh_iou", "terminal_validation_pass"):
            if key in evaluation:
                writer.add_scalar(f"evaluation/{key}", float(evaluation[key]), step)
        writer.add_scalar("evaluation/stochastic_environment_pass_rate", stochastic_pass_rate, step)
        if "reward_collision" in evaluation:
            writer.add_scalar("evaluation/reward_collision", evaluation.get("episode_reward_collision", evaluation["reward_collision"]), step)
        if "similarity_percent" in evaluation:
            writer.add_scalar("evaluation/similarity_percent", evaluation["similarity_percent"], step)
            writer.add_scalar("evaluation/reward_similarity", evaluation["reward_similarity"], step)
        if artifact is not None:
            writer.add_scalar("independent_validation/pass", float(artifact["validation_status"] == "PASS"), step)
            if "independent_geometry_process_status" in artifact:
                writer.add_scalar("independent_geometry_process/pass", float(artifact["independent_geometry_process_status"] == "PASS"), step)
                writer.add_scalar("policy/completed", float(artifact["policy_completed"]), step)
            for key in ("iou", "similarity_percent", "coverage", "overfill", "symmetric_difference_relative"):
                if key in artifact.get("mesh_comparison", {}):
                    writer.add_scalar(f"actual_mesh/{key}", artifact["mesh_comparison"][key], step)
            for key in ("stl_generated", "stl_watertight", "stl_volume_relative_error"):
                if key in artifact:
                    writer.add_scalar(f"artifact/{key}", float(artifact[key]), step)
