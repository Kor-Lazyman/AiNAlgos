"""SB3 clipped PPO + Monte Carlo, with an exact completed-episode training budget."""
from dataclasses import dataclass
from time import perf_counter, time_ns

import numpy as np
import torch
from gymnasium import spaces
from stable_baselines3 import PPO
from .mc_ppo import MonteCarloDictRolloutBuffer, MonteCarloRolloutBuffer
from stable_baselines3.common.utils import obs_as_tensor, safe_mean


@dataclass(frozen=True)
class LinearLearningRate:
    initial: float = 3e-3
    final: float = 1e-5

    def __call__(self, progress_remaining):
        return self.final + (self.initial - self.final) * float(np.clip(progress_remaining, 0, 1))


class EpisodePPO(PPO):
    """Keep actions as SB3 timesteps internally; log/train budgets in episodes.

    Rollouts contain complete episodes; n_steps is a minimum action count.
    The final batch stops exactly at the completed-episode budget.
    Task max_steps is a terminal failure, so it receives no timeout bootstrap.
    """

    def _setup_model(self):
        if self.n_envs != 1:
            raise ValueError("EpisodePPO requires one environment; multi-STL sampling is supported")
        # Always collect full episodes, including when loading older policy weights.
        self.gae_lambda = 1.0
        self.rollout_buffer_class = MonteCarloDictRolloutBuffer if isinstance(self.observation_space, spaces.Dict) else MonteCarloRolloutBuffer
        super()._setup_model()

    def learn(self, total_episodes=50000, callback=None, log_interval=1, tb_log_name="PPO"):
        """Public training entry point: the budget is completed episodes, not actions."""
        return self.learn_episodes(total_episodes, callback, tb_log_name, log_interval)

    def learn_episodes(self, total_episodes=50000, callback=None, tb_log_name="PPO", log_interval=1):
        if isinstance(total_episodes, bool) or not isinstance(total_episodes, int) or total_episodes < 1:
            raise ValueError("total_episodes must be a positive integer")
        if not isinstance(log_interval, int) or log_interval < 1:
            raise ValueError("log_interval must be a positive integer")
        self.target_episodes = total_episodes
        self.completed_episodes = 0
        self.finished_episodes = 0
        self.truncated_episodes = 0
        self._current_progress_remaining = 1.
        # The base setup initializes callbacks/loggers/reset state. Its action budget
        # is unused: the loop below is explicitly governed by completed episodes.
        _, callback = self._setup_learn(total_episodes, callback, reset_num_timesteps=True, tb_log_name=tb_log_name)
        callback.on_training_start(locals(), globals())
        iteration = 0
        while self.completed_episodes < self.target_episodes:
            if not self.collect_rollouts(self.env, callback, self.rollout_buffer, self.n_steps):
                break
            self._current_progress_remaining = max(0., 1 - self.completed_episodes / self.target_episodes)
            started = perf_counter()
            self.train()  # PPO clipped loss, MC return targets, value baseline.
            self.logger.record("perf/update_seconds", perf_counter() - started)
            self.trained_advantage_estimator = "monte_carlo"
            iteration += 1
            if iteration % log_interval == 0 or self.completed_episodes == self.target_episodes:
                self.dump_logs(iteration)
        callback.on_training_end()
        return self

    def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps):
        if self._last_obs is None or not np.all(self._last_episode_starts):
            raise ValueError("MC collection must begin at an episode boundary")
        self.policy.set_training_mode(False)
        rollout_buffer.buffer_size = n_rollout_steps
        rollout_buffer.reset()
        n_steps = 0
        started = perf_counter()
        policy_seconds = environment_seconds = 0.
        if self.use_sde:
            self.policy.reset_noise(env.num_envs)
        callback.on_rollout_start()
        while self.completed_episodes < self.target_episodes:
            if self.use_sde and self.sde_sample_freq > 0 and n_steps % self.sde_sample_freq == 0:
                self.policy.reset_noise(env.num_envs)
            policy_started = perf_counter()
            with torch.no_grad():
                actions, values, log_probs = self.policy(obs_as_tensor(self._last_obs, self.device))
            actions = actions.cpu().numpy()
            policy_seconds += perf_counter() - policy_started
            clipped_actions = actions
            if isinstance(self.action_space, spaces.Box):
                clipped_actions = (self.policy.unscale_action(actions) if self.policy.squash_output
                                   else np.clip(actions, self.action_space.low, self.action_space.high))
            environment_started = perf_counter()
            new_obs, rewards, dones, infos = env.step(clipped_actions)
            environment_seconds += perf_counter() - environment_started
            self.num_timesteps += env.num_envs
            if dones[0]:
                self.completed_episodes += 1
                if infos[0].get("TimeLimit.truncated", False):
                    self.truncated_episodes += 1
                else:
                    self.finished_episodes += 1
            callback.update_locals(locals())
            if not callback.on_step():
                self._last_obs = new_obs
                self._last_episode_starts = dones
                return False
            self._update_info_buffer(infos, dones)
            if isinstance(self.action_space, spaces.Discrete):
                actions = actions.reshape(-1, 1)
            # A task horizon failure is terminal, including Gymnasium truncations.
            rollout_buffer.add(self._last_obs, actions, rewards, self._last_episode_starts, values, log_probs)
            self._last_obs = new_obs
            self._last_episode_starts = dones
            n_steps += 1
            if n_steps >= n_rollout_steps and np.all(dones):
                break
        rollout_buffer.compute_returns_and_advantage(last_values=None, dones=dones)
        self.logger.record("rollout/actions_collected", n_steps)
        self.logger.record("perf/environment_ms_per_step", 1000 * environment_seconds / n_steps)
        self.logger.record("perf/policy_ms_per_step", 1000 * policy_seconds / n_steps)
        self.logger.record("perf/rollout_steps_per_second", n_steps / (perf_counter() - started))
        callback.update_locals(locals())
        callback.on_rollout_end()
        return True

    def dump_logs(self, iteration=0):
        elapsed = max((time_ns() - self.start_time) / 1e9, 1e-9)
        self.logger.record("time/iterations", iteration, exclude="tensorboard")
        if self.ep_info_buffer:
            self.logger.record("rollout/ep_rew_mean", safe_mean([info["r"] for info in self.ep_info_buffer]))
            self.logger.record("rollout/ep_len_mean", safe_mean([info["l"] for info in self.ep_info_buffer]))
        self.logger.record("time/eps", self.completed_episodes)
        self.logger.record("time/target_eps", self.target_episodes)
        self.logger.record("time/finished_eps", self.finished_episodes)
        self.logger.record("time/truncated_eps", self.truncated_episodes)
        self.logger.record("time/action_steps", self.num_timesteps)
        self.logger.record("time/eps_per_second", self.completed_episodes / elapsed)
        self.logger.record("perf/action_steps_per_second", self.num_timesteps / elapsed)
        self.logger.record("time/time_elapsed", int(elapsed), exclude="tensorboard")
        self.logger.dump(step=self.completed_episodes)
