"""Uniform seeded STL sampling, once per complete episode."""
import gymnasium as gym
import numpy as np


class SampledWaamPPOEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, environments, target_names):
        super().__init__()
        if not environments or len(environments) != len(target_names):
            raise ValueError("Provide a nonempty environment list with matching target names")
        self.environments = list(environments)
        self.target_names = list(target_names)
        self.observation_space = self.environments[0].observation_space
        self.action_space = self.environments[0].action_space
        if any(e.observation_space != self.observation_space or e.action_space != self.action_space
               for e in self.environments):
            raise ValueError("All targets must share policy observation/action spaces")
        self.active_index = None
        self.episode_counts = np.zeros(len(environments), dtype=np.int64)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.active_index = int(self.np_random.integers(len(self.environments)))
        observation, info = self.environments[self.active_index].reset(seed=seed)
        return observation, {**info, **self._target_info()}

    def _target_info(self):
        return {"target_index": self.active_index,
                "target_name": self.target_names[self.active_index]}

    def step(self, action):
        if self.active_index is None:
            raise gym.error.ResetNeeded("Call reset before step")
        obs, reward, terminated, truncated, info = self.environments[self.active_index].step(action)
        if terminated or truncated:
            self.episode_counts[self.active_index] += 1
        return obs, reward, terminated, truncated, {**info, **self._target_info()}

    def close(self):
        for environment in self.environments:
            environment.close()
