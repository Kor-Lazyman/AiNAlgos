"""Episode validation reports without rerunning checks or writing CSV/JSON."""

from collections import deque

from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import TensorBoardOutputFormat


class TrainingReportCallback(BaseCallback):
    """PASS means env success: all F + trajectory and shape checks passing.

    Collision remains a separate episode statistic, as in the environment's
    reward. This is not the original file validator's combined PASS/FAIL.
    Read terminal info directly: SB3 has already auto-reset the environment.
    """

    def __init__(self):
        super().__init__()
        self.episodes = 0
        self.passed = 0
        self.last_episode = None
        self.recent = deque(maxlen=100)
        self._collision_steps = []
        self._lengths = []
        self._writers = []

    @property
    def summary(self):
        return {
            "episodes": self.episodes,
            "pass_count": self.passed,
            "fail_count": self.episodes - self.passed,
            "pass_rate": self.passed / self.episodes if self.episodes else 0.0,
            "unfinished_episodes": sum(length > 0 for length in self._lengths),
            "last_episode": self.last_episode,
        }

    def _on_training_start(self):
        self._collision_steps = [0] * self.training_env.num_envs
        self._lengths = [0] * self.training_env.num_envs
        self._writers = [
            output.writer for output in self.logger.output_formats
            if isinstance(output, TensorBoardOutputFormat)
        ]

    def _on_step(self):
        for index, (done, info) in enumerate(zip(self.locals["dones"], self.locals["infos"], strict=True)):
            self._lengths[index] += 1
            self._collision_steps[index] += int(info["collision_pass"] == 0)
            if not done:
                continue

            success = int(info["success"] == 1)
            record = {
                "result": "PASS" if success else "FAIL",
                "success": success,
                "trajectory_pass": int(info["validation_pass"]),
                "shape_pass": int(info["shape_pass"]),
                "collision_steps": self._collision_steps[index],
                "collision_free": int(self._collision_steps[index] == 0),
                "makespan_s": float(info["makespan_s"]),
                "reward": float(info["episode"]["r"]),
                "length": self._lengths[index],
                "truncated": int(info.get("TimeLimit.truncated", False)),
            }
            self.episodes += 1
            self.passed += success
            self.last_episode = record
            self.recent.append(record)
            self._collision_steps[index] = 0
            self._lengths[index] = 0

            status = lambda flag: "PASS" if flag else "FAIL"
            line = (
                f"[Episode {self.episodes} | step {self.num_timesteps}] "
                f"validation={record['result']} "
                f"trajectory={status(record['trajectory_pass'])} "
                f"shape={status(record['shape_pass'])} "
                f"collision={status(record['collision_free'])} "
                f"collision_steps={record['collision_steps']} "
                f"makespan_s={record['makespan_s']:.3f} "
                f"reward={record['reward']:.3f} "
                f"end={'TIME_LIMIT' if record['truncated'] else 'FINISHED'}"
            )
            self.logger.info(line)
            # Write each episode directly, so multiple completions in a rollout
            # are not overwritten by SB3's per-rollout logger.record().
            for writer in self._writers:
                for key, value in record.items():
                    if key != "result":
                        writer.add_scalar(f"episode/{key}", value, self.num_timesteps)
                writer.add_text("episode/validation_result", record["result"], self.num_timesteps)
                writer.add_text("episode/report", line, self.num_timesteps)
                writer.flush()
        return True

    def _record_summary(self):
        for key, value in self.summary.items():
            if key != "last_episode":
                self.logger.record(f"validation/{key}", value)
        if self.recent:
            self.logger.record("validation/last_result", self.last_episode["result"])
            for key in ("success", "trajectory_pass", "shape_pass", "collision_free", "makespan_s"):
                mean = sum(record[key] for record in self.recent) / len(self.recent)
                self.logger.record(f"validation/{key}_mean_100", mean)

    def _on_rollout_end(self):
        self._record_summary()

    def _on_training_end(self):
        self._record_summary()
        # SB3 logs before its update. Dump once more to include the last loss
        # and the final report even if a user callback stops a partial rollout.
        self.logger.dump(self.num_timesteps)
        self.logger.info(
            f"[Validation summary] episodes={self.episodes} PASS={self.passed} "
            f"FAIL={self.episodes - self.passed} pass_rate={self.summary['pass_rate']:.1%}"
        )
