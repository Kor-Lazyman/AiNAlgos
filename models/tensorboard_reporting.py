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

    def _on_step(self):
        for done, info in zip(self.locals["dones"], self.locals["infos"], strict=True):
            if not done:
                continue
            self.episodes += 1
            success = float(info["success"])
            self.recent_successes.append(success)
            values = {
                "episode/count": self.episodes,
                "episode/reward": info["episode"]["r"],
                "episode/length": info["episode"]["l"],
                "validation/cached_success": success,
                "validation/cached_pass_rate_100": sum(self.recent_successes) / len(self.recent_successes),
                "shape/coverage": info["coverage"],
                "shape/overfill": info["overfill"],
                "shape/iou": info["iou"],
                "reward/makespan_weight": info["makespan_weight"],
            }
            for tag, value in values.items():
                self.writer.add_scalar(tag, value, self.num_timesteps)
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
        writer.add_scalar("evaluation/stochastic_cached_pass_rate", stochastic_pass_rate, step)
        if artifact is not None:
            writer.add_scalar("independent_validation/pass", float(artifact["validation_status"] == "PASS"), step)
            writer.add_scalar("artifact/stl_watertight", float(artifact["stl_watertight"]), step)
            writer.add_scalar("artifact/stl_volume_relative_error", artifact["stl_volume_relative_error"], step)
