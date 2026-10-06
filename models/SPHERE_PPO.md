# Sphere PPO for project version 1.0.0

Project version is read from `VERSION`; the checkout folder remains
`Project_version_0.1.2`. The embedded validator has its own version.
See the [Korean README](../README.md) for the current quick start.

TensorBoard is enabled by default. Run `python -m tensorboard.main --logdir
./tensorboard --port 6006`, then open http://localhost:6006. Use
`--tensorboard-log PATH`, `--run-name NAME`, or `--no-tensorboard` to configure it.
SB3 records training losses; the episode callback records reward, coverage,
overfill, IoU and rolling cached-validation pass rate. Final evaluation and
independent validation/export metrics are recorded under the evaluation run.
Old checkpoints do not contain historical TensorBoard loss events.

Train a Stable-Baselines3 PPO policy on the original `sphere_r-24mm.STL`, then
export its deterministic rollout and run the separate, unchanged validator.
The source STL is copied byte-for-byte, without scaling or moving it.

From `Project_version_0.1.2` in PowerShell:

```powershell
& C:/Users/lazzyman/anaconda3/envs/waam/python.exe -m models.sphere_ppo --timesteps 49152
& C:/Users/lazzyman/anaconda3/envs/waam/python.exe -B -m unittest environment.test_gym_wrapper models.test_sphere_ppo -v
```

Dependencies: the environment's validator dependencies plus `torch`,
`gymnasium`, `stable-baselines3`, `tensorboard`, `mapbox-earcut`, `manifold3d`, and `pandas` for
the original regression tests.
CPU is intentional for this small MLP. The training summary records actual
timesteps, parameter changes, baseline, and evaluation results.

## Policy and reward

This is a hierarchical PPO planner. The learned policy chooses one of 12
contour-inset/infill-spacing combinations for each of 24 layers. It observes
layer progress, normalized target area/perimeter, accumulated coverage/overfill,
failed-layer fraction, and the active robot. Geometry is sliced from the STL,
not approximated as an ideal mathematical sphere.

The deterministic compiler supplies the contour and raster paths, T/D/W mode
transitions, configured motion speeds, and a serial three-robot schedule.
Robots alternate layers and return home before the next robot starts. Every
candidate is checked for trajectory validity and both kinds of collision.
PPO does not learn arbitrary XYZ moves, robot assignment, or parallel motion.
The existing low-level `WaamGymEnv` is preserved; `SpherePPOEnv` is the new
target-conditioned Gym interface.

For a safe layer, dense reward is:

```
2 * IoU - 20 * max(0, 0.95 - coverage) - 20 * max(0, overfill - 0.05)
```

An unsafe option receives -100. A complete passing episode receives +100;
a failing episode receives -100. PPO gamma is 1.0. Makespan weight is exactly
zero. Training uses exact cached deposited geometry computed from compiled
float32 trajectories. Layer areas are additive under the validator's slab
model. Final acceptance always recomputes the entire exported trajectory in a
fresh process using `validator/src`, independently of the training cache.

Shape thresholds remain coverage >=95%, overfill <=5%, overall IoU >=90%,
layer IoU >=80%, and failed layers <=5%. Both arm-envelope and TCP-radius
collision checks remain enabled. Robot dimensions, bead width (4 mm), layer
height (2 mm), and speeds remain the sample job's values. The only config
change is `fail_on_speed_violation: true`, making speed checks stricter.

## Outputs

All artifacts default to `outputs/sphere_r-24mm_ppo/`:

- `ppo_sphere.zip`: trained and reloadable PPO checkpoint.
- `job/target.stl`: unchanged original target.
- `job/trajectory.csv`: validator-ready robot_id, time_s, x_mm, y_mm, z_mm, mode.
- `job/config.yaml`: complete reproduction configuration.
- `trajectory_robot_modes.csv`: same trajectory with final F for each robot.
  The validator accepts T/D/W only, so its CSV ends in W instead.
- `deposited_sphere.stl`: actual bead-union geometry extruded for each layer
  and boolean-unioned into a watertight solid. It retains the layer steps.
- `deposited_layers.stl`: original validator export, concatenating slabs with
  internal faces; use the watertight `deposited_sphere.stl` for downstream work.
- `artifact_verification.json`: exported STL watertightness and volume checks.
- `selected_actions.json`: PPO choices and assigned robot for each layer.
- `training.monitor.csv`, `training_summary.json`: training/evaluation evidence.
- `validation/`: standalone validator's summary, layer metrics, and reports.

To regenerate outputs from a checkpoint without further training (use a new
output directory to preserve the original training evidence):

```powershell
& C:/Users/lazzyman/anaconda3/envs/waam/python.exe -m models.sphere_ppo --model outputs/sphere_r-24mm_ppo/ppo_sphere.zip --output outputs/sphere_replay
```

To rerun only independent validation:

```powershell
& C:/Users/lazzyman/anaconda3/envs/waam/python.exe models/validate_sphere.py outputs/sphere_r-24mm_ppo/job outputs/sphere_r-24mm_ppo/revalidation
```

Acceptance tests check all three validators, actual STL volume, robot modes,
PPO parameter updates, and cache/final-metric agreement. Negative controls remove
deposition, corrupt a deposition height, and force a collision to verify that
failures are detected. Stochastic evaluation measures shape and cached safety
on this same target; it is not a claim of generalization to unseen parts.

A nominal validator PASS does not model thermal behavior, support/overhang
feasibility, or full articulated robot kinematics. Those remain outside this
repository's validation model.
