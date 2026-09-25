"""학습 설정. 경로는 실행 위치가 아니라 프로젝트 위치를 기준으로 합니다."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
import torch
from environment.gym_wrapper import WaamGymEnv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PPOConfig:
    lr: float = 3e-4
    eps: float = 1e-5  # Adam epsilon; epsilon-greedy 탐색률이 아님
    clip_range: float = 0.2  # PPO 정책 비율 clipping epsilon
    n_steps: int = 256
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    ent_coef: float = 0.0
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    target_kl: float | None = None
    hidden_sizes: tuple[int, ...] = (64, 64)

    def sb3_kwargs(self) -> dict[str, Any]:
        return {
            "learning_rate": self.lr,
            "n_steps": self.n_steps,
            "batch_size": self.batch_size,
            "n_epochs": self.n_epochs,
            "gamma": self.gamma,
            "gae_lambda": self.gae_lambda,
            "clip_range": self.clip_range,
            "ent_coef": self.ent_coef,
            "vf_coef": self.vf_coef,
            "max_grad_norm": self.max_grad_norm,
            "target_kl": self.target_kl,
            "policy_kwargs": {
                "net_arch": list(self.hidden_sizes),
                "optimizer_kwargs": {"eps": self.eps},
            },
        }


@dataclass(frozen=True)
class TrainConfig:
    model_name: str = "ppo"
    env_class: type = WaamGymEnv
    env_kwargs: dict[str, Any] = field(default_factory=lambda: {
        "job_dir": PROJECT_ROOT / "environment/examples/sample_job",
        "max_steps": 256,
        "wait_time_s": 0.1,
        "makespan_weight": 0.01,
        "collision_penalty": 1.0,
        "terminal_reward": 10.0,
        "terminal_penalty": 10.0,
    })
    ppo: PPOConfig = field(default_factory=PPOConfig)
    total_timesteps: int = 100_000
    seed: int = 42
    device: str = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    torch_num_torchreads: int = 1
    verbose: int = 1
    check_env: bool = True
    output_dir: Path = PROJECT_ROOT / "models/checkpoints"

    def make_env(self):
        return self.env_class(**self.env_kwargs)


CONFIG = TrainConfig()

# 실행 연결 확인용이며, 학습 성능을 평가하기 위한 설정은 아닙니다.
SMOKE_CONFIG = replace(
    CONFIG,
    total_timesteps=64,
    env_kwargs={**CONFIG.env_kwargs, "max_steps": 4},
    ppo=replace(CONFIG.ppo, n_steps=16, batch_size=8, n_epochs=2),
)
