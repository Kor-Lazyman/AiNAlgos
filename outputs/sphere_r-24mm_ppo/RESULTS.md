# Sphere PPO result — PASS

Target: original `sphere_r-24mm.STL`, unchanged. Project: 0.1.2.

The reloaded PPO checkpoint's deterministic rollout passed the separate
standalone validator with its original shape and collision thresholds and
stricter speed validation. The final report is
[`validation_3/validation_report.md`](validation_3/validation_report.md).

| Check | Result |
| --- | --- |
| Coverage | 99.999229% |
| Overall IoU | 96.325360% |
| Overfill | 3.814021% |
| Failed layers | 0 / 24 |
| Collision events | 0 |
| Process violations / warnings | 0 / 0 |
| Trajectory rows | 4,562 |
| Simulated makespan | 1,902.468 seconds; no reward penalty |
| Regression and acceptance tests | 26 passed |
| Exported solid | Watertight, 39,614 triangles |

- [Trained PPO checkpoint](ppo_sphere.zip)
- [Watertight deposited STL](deposited_sphere.stl)
- [Trajectory including T/D/W/F robot modes](trajectory_robot_modes.csv)
- [Validator-ready T/D/W trajectory](job/trajectory.csv)
- [Job configuration](job/config.yaml) and [original target STL](job/target.stl)
- [Training evidence](training_summary.json), [test results](tests.txt), and
  [STL verification](artifact_verification.json)
- [Implementation and reproduction instructions](../../models/SPHERE_PPO.md)

PPO trained for 49,152 steps with seed 42. The initial deterministic policy
failed (88.84% coverage); the trained deterministic policy passed. Policy
parameter change L2 was 9.1222. Of 100 stochastic evaluation episodes on this
same target, 98 passed shape and cached candidate-safety checks. These are
distinct from the full standalone validation of the exported deterministic
trajectory.

The learned policy selects contour inset and infill spacing per layer.
A deterministic compiler supplies geometry-following paths, mode transitions,
and serial robot scheduling. All three robots deposit eight layers each.
This is a hierarchical planner, not an unconstrained learned XYZ controller.

`deposited_layers.stl` preserves the validator's raw slab export with internal
faces. Use `deposited_sphere.stl`, the boolean-unioned watertight solid.
Its volume differs from the validator's deposited volume by less than 1e-8%.
Earlier validation reports are preserved; `validation_3` includes the final
successful STL export. Nominal validation does not assess thermal behavior,
overhang support, or full articulated robot kinematics.
