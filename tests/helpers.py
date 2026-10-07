import gymnasium as gym
import numpy as np

class EpisodeEnv(gym.Env):
    def __init__(self, dictionary=False, truncated=False):
        self.dictionary = dictionary
        self.truncated = truncated
        self.action_space = gym.spaces.Box(-1, 1, (1,), dtype=np.float32)
        box = gym.spaces.Box(0, 3, (1,), dtype=np.float32)
        self.observation_space = gym.spaces.Dict({"state": box}) if dictionary else box

    def observation(self):
        obs = np.array([self.position], dtype=np.float32)
        return {"state": obs} if self.dictionary else obs

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.position = 0
        return self.observation(), {}

    def step(self, action):
        self.position += 1
        done = self.position == 3
        return self.observation(), float(self.position), done and not self.truncated, done and self.truncated, {}


