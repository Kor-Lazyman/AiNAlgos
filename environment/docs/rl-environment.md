# PPO Environment

The optional `WaamPPOEnv` adapts Stable-Baselines3 actions into the validator's
standard three-robot `trajectory.csv` format. It keeps `config.yaml` and
`target.stl` from the source job unchanged and creates an isolated temporary
job for each episode.

Install the optional dependencies:

```powershell
python -m pip install -e ".[rl]"
```

Create and train a PPO policy:

```python
from stable_baselines3 import PPO

from waam_validator import WaamPPOEnv

environment = WaamPPOEnv("examples/sample_job", max_steps=128)
model = PPO("MlpPolicy", environment, verbose=1)
model.learn(total_timesteps=10_000)
model.save("waam-ppo")
environment.close()
```

The action has nine continuous values, grouped as `(dx, dy, deposition_request)`
for robots 1, 2, and 3. Movement values are normalized to `[-1, 1]` and scaled
by `movement_step_mm`. A positive deposition request moves to the configured
first-layer height and uses `D` once the robot is at that height; other movement
uses `T`, and zero movement uses `W`.

The observation has ten values: normalized XYZ positions for all three robots
followed by the episode progress fraction. On the final step, or on every step
when `validate_each_step=True`, the reward is computed from the full validator
result: shape coverage, overfill, collision events, reach violations, and a
bonus for a `PASS` result. Validation errors are returned in the step `info`
dictionary instead of escaping the Gymnasium loop.