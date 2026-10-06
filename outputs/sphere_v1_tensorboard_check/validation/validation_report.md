# WAAM Validator Report

## Overall Result

**PASS**

- WAAM Validator version: 1.0.1

## Input Summary

- Directory: `C:\Users\lazzyman\Desktop\AI_Algo\Project_version_0.1.2\outputs\sphere_v1_tensorboard_check\job`
- Trajectory rows: 4562
- Target watertight: True

## Schedule

- Makespan: 1902.47 s
- R1: completion 1902.47 s; Deposition 454.38 s; Travel 183.51 s; Wait 1264.57 s
- R2: completion 1902.47 s; Deposition 450.76 s; Travel 180.29 s; Wait 1271.41 s
- R3: completion 1902.47 s; Deposition 452.80 s; Travel 180.62 s; Wait 1269.05 s

## Robot XY Reach

- Passed: True
- R1: max XY distance 1221.51 / 2500.00 mm; XY margin 1278.49 mm; violating points 0
- R2: max XY distance 1180.61 / 2500.00 mm; XY margin 1319.39 mm; violating points 0
- R3: max XY distance 1198.61 / 2500.00 mm; XY margin 1301.39 mm; violating points 0

## Collision

- Arm Envelope events: 0
- Minimum Arm Envelope safety margin: 886.07 mm
- Arm centerline distance at worst case:
  1136.07 mm
- Arm required centerline distance at worst case:
  250.00 mm
- TCP_RADIUS events: 0
- Minimum TCP distance: 1136.07 mm

## Shape

- Target layer-integrated volume: 57798.245 mm³
- Deposited volume: 60002.236 mm³
- Intersection volume: 57797.799 mm³
- Underfill volume: 0.446 mm³
- Overfill volume: 2204.437 mm³
- Coverage: 100.00%
- Underfill: 0.00%
- Overfill: 3.81%
- IoU: 96.33%
- Failed layers: 0 / 24

## Failure Reasons

None

## Warnings

None

## Validation Violations

These findings contribute to a normal `FAIL`; they do not mean that the pipeline ended with
the fatal status `ERROR`.

None

## Output Files

- `summary.json`
- `validation_report.md`
- `robot_metrics.csv`
- `collision_events.csv`
- `layer_metrics.csv`
- `run.log`
- `validation_inputs.json`

## Interpretation Limitations

본 검증기는 각 로봇을 폭이 고정된 Base–TCP 2D Capsule로 단순화하고, XY 평면상 Capsule 안전 여유와 TCP 허용 원 침범만을 로봇 간 충돌로 판단한다. 검사는 adaptive sample 기반이며 연속시간 swept collision을 보증하지 않는다. 실제 로봇 링크, 관절 자세, Z 방향 분리, 지그 및 환경 충돌은 반영하지 않는다. 형상 검증은 일정한 비드 폭과 layer 높이를 가정한 명목 기하 모델이며 열변형, 비드 형상 변화, 용융풀 거동 및 공정 불안정성을 예측하지 않는다.
