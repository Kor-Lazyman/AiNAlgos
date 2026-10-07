"""PPO with complete-episode Monte Carlo returns and a learned value baseline.

The environment must end every episode (including its task action limit).
Truncations are terminal task outcomes here, not continuing-task timeouts.
"""
import numpy as np
import torch
from gymnasium import spaces
from stable_baselines3.common.buffers import DictRolloutBuffer, RolloutBuffer


class _MonteCarloBuffer:
    def _resize(self, size):
        """Resize before flattening, preserving all collected transitions."""
        if self.generator_ready:
            raise RuntimeError("Reset the MC buffer before collecting again")

        def resize(array):
            result = np.zeros((size, *array.shape[1:]), dtype=array.dtype)
            count = min(self.pos, size)
            result[:count] = array[:count]
            return result

        if isinstance(self.observations, dict):
            self.observations = {key: resize(value) for key, value in self.observations.items()}
        else:
            self.observations = resize(self.observations)
        for name in ("actions", "rewards", "returns", "episode_starts", "values", "log_probs", "advantages"):
            setattr(self, name, resize(getattr(self, name)))
        self.buffer_size = size
        self.full = self.pos == size

    def add(self, *args, **kwargs):
        if self.pos == self.buffer_size:
            self._resize(max(2 * self.buffer_size, 1))
        super().add(*args, **kwargs)

    def compute_returns_and_advantage(self, last_values, dones):
        # Deliberately do not use last_values: no terminal/bootstrap value.
        if self.pos == 0 or not np.all(dones) or not np.all(self.episode_starts[0]):
            raise ValueError("Monte Carlo updates require complete episodes")
        self._resize(self.pos)
        future_return = np.zeros(self.n_envs, dtype=np.float32)
        for step in reversed(range(self.buffer_size)):
            if step + 1 < self.buffer_size:
                future_return *= 1.0 - self.episode_starts[step + 1]
            future_return = self.rewards[step] + self.gamma * future_return
            self.returns[step] = future_return
        self.advantages = self.returns - self.values


class MonteCarloRolloutBuffer(_MonteCarloBuffer, RolloutBuffer):
    pass


class MonteCarloDictRolloutBuffer(_MonteCarloBuffer, DictRolloutBuffer):
    pass

