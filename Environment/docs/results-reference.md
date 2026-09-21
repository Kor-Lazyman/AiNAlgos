# 결과 및 산출물 참조

WAAM Validator 1.0.0의 현재 결과 schema는 `4.0`입니다. 기본 Validation은 판정 재현과
자동 처리에 필요한 핵심 파일만 기록합니다.

## 상태와 출력 폴더

| 상태 | 의미 | 종료 코드 |
| --- | --- | ---: |
| `PASS` | 활성화된 모든 판정 기준 충족 | 0 |
| `FAIL` | 계산은 완료됐지만 XY Reach·충돌·형상·공정 기준 위반 | 1 |
| `ERROR` | 입력·Target·계산·출력 오류로 계산을 완료하지 못함 | 2–5 |

기본 경로는 `<JOB_DIR>/output/YYYY-MM-DD_HHMMSS/`입니다. 같은 초에 다시 실행하면
`_001`, `_002` suffix를 붙입니다. 명시한 `--output`이 비어 있지 않으면 덮어쓰지 않고
종료 코드 5로 거부합니다.

## 기본 파일 집합

| 파일 | 내용 |
| --- | --- |
| `summary.json` | 최종 판정과 일정·XY Reach·충돌·형상 요약 |
| `validation_report.md` | 사람이 읽는 결과 보고서 |
| `robot_metrics.csv` | 로봇별 원시 시간·거리·속도·XY Reach |
| `collision_events.csv` | 병합된 Arm Envelope/TCP Radius 이벤트 |
| `layer_metrics.csv` | 평가 layer별 면적과 형상 지표 |
| `run.log` | 입력, 계산 단계와 판정 로그 |
| `validation_inputs.json` | 세 입력 파일의 SHA-256, 크기, nanosecond 수정 시각과 Validation 당시 Config |

`warnings.csv`, 정적 PNG, 기본 `deposited.stl`, 기본 `replay.html`은 생성하지 않습니다.

## `summary.json`

상위 구조는 다음과 같습니다.

```json
{
  "schema_version": "4.0",
  "validator_version": "1.0.0",
  "status": "PASS",
  "input": {},
  "schedule": {},
  "reach": {},
  "collision": {},
  "shape": {},
  "failure_reasons": [],
  "issues": [],
  "output_directory": "..."
}
```

### `schedule`

- `makespan_s`: 세 로봇 completion의 최댓값
- `robot_completion_s`: Robot ID별 trajectory 종료 시각
- `workload_imbalance_s`: 최대 completion − 최소 completion
- `normalized_imbalance`: imbalance / makespan

상태별 시간과 완료 후 비활성 시간은 `robot_metrics.csv`에 저장합니다.

### `reach`

`reach.distance_basis`는 항상 `"XY"`이며, `reach.passed`와 로봇별 다음 값을 제공합니다.

- `xy_reach_radius_mm`: Config의 허용 XY 반경
- `maximum_xy_distance_mm`: 원본 TCP 절점과 Base 사이의 최대 XY 거리
- `minimum_xy_margin_mm`: 허용 XY 반경 − 최대 XY 거리
- `xy_utilization_ratio`: 최대 XY 거리 / 허용 XY 반경
- `xy_violation_point_count`, `first_xy_violation_s`, `last_xy_violation_s`

### `collision`

`arm_envelope`은 Base–TCP XY 중심선 사이의 최단거리를 사용합니다.

```text
required = arm_radius_A + arm_radius_B + arm_clearance_mm
safety_margin = measured_centerline_distance - required
```

최소 safety margin, 그때의 중심선 거리·요구 거리·pair·시각, closest points와 세
TCP의 XY 위치를 저장합니다. `tcp_radius`는 TCP 끝점 사이 XY 거리와 두 TCP 반경의
합을 같은 방식으로 비교합니다. 검사를 비활성화해도 최소값은 지표로 계산하지만
이벤트와 FAIL은 만들지 않습니다.

`collision_event_count`는 `collision_events.csv`의 전체 행 수이며 각 하위
`event_count`는 유형별 행 수와 같습니다.

### `shape`

`target_volume_mm3`, `deposited_volume_mm3`, `intersection_volume_mm3`,
`underfill_volume_mm3`, `overfill_volume_mm3`는 Layer 단면적을 명목 Layer 높이로
적분한 체적입니다. Coverage·Underfill·Overfill·IoU는 이 체적 합계에서 계산하므로
Layer 크기가 서로 달라도 면적 가중이 유지됩니다. 원본 mesh 체적은
`target_mesh_volume_mm3`, 두 Target 체적의 상대 차이는
`target_volume_discrepancy_ratio`로 별도 기록합니다.

- `coverage = intersection volume / target layer volume`
- `underfill_ratio = underfill volume / target layer volume`
- `overfill_ratio = overfill volume / target layer volume`
- `iou = intersection volume / union volume`
- `failed_layer_count`, `evaluated_layer_count`, `failed_layer_ratio`
- layer 적분 체적과 원본 mesh 체적 및 그 차이 비율

전체 지표는 layer 비율의 단순 평균이 아니라 면적×layer 높이로 누적한 체적 가중값입니다.

### `failure_reasons`와 `issues`

`failure_reasons`는 최종 FAIL을 설명하는 결정론적 요약입니다. 순서는 입력/process,
XY Reach, Arm Envelope, TCP Radius, 형상, 속도입니다.

`issues`는 warning과 정상 FAIL을 만든 비치명 violation을 하나의 구조로 저장합니다.

```json
{
  "severity": "warning",
  "code": "STATIONARY_TRAVEL",
  "message": "...",
  "robot_id": 1,
  "start_s": 10.0,
  "end_s": 11.0
}
```

`severity`는 `warning` 또는 `violation`입니다. 치명적 `ERROR`는 `issues`가 아니라
예외와 `error.json`으로만 표현합니다.

## `robot_metrics.csv`

주요 열:

- `completion_s`
- `deposition_time_s`, `travel_time_s`, `wait_time_s`
- `inactive_after_completion_s = makespan_s - completion_s`
- `deposition_length_mm`, `travel_length_mm`
- `mean_deposition_speed_mm_s`, `mean_travel_speed_mm_s`
- `xy_reach_radius_mm`, `maximum_xy_distance_mm`, `minimum_xy_margin_mm`
- `xy_utilization_ratio`, `xy_violation_point_count`
- `first_xy_violation_s`, `last_xy_violation_s`

항상 다음 관계를 만족해야 합니다.

```text
Deposition + Travel + Wait = completion
completion + inactive_after_completion = makespan
mean mode speed = mode distance / mode time
```

거리와 시간은 모두 같은 left-row mode interval만 사용합니다. Travel 시간이 짧아도
속도가 훨씬 빠르면 Travel 거리가 Deposition 거리보다 클 수 있습니다.

## `collision_events.csv`

각 행은 같은 유형·robot pair의 인접 충돌 sample을 `event_merge_gap_s` 기준으로
병합한 이벤트입니다. 핵심 열은 유형, pair, 시작·종료·지속시간, 측정 최소거리,
요구거리, 최소 safety margin과 그 시각입니다. Arm 이벤트에는 Capsule 표면 간격과
양쪽 중심선 closest point도 기록합니다.

이벤트 범위와 최솟값은 adaptive sample 기반입니다. 연속시간 swept collision의
수학적 보증이 아닙니다.

## `layer_metrics.csv`

각 평가 layer의 Z 범위, Target·Deposition·교집합·Underfill·Overfill 면적,
Coverage·Underfill·Overfill·IoU와 개별 PASS를 기록합니다. Target만 있거나
Deposition만 있는 layer도 평가하며 둘 다 수치적으로 빈 layer만 건너뜁니다.

Target과 trajectory를 동일한 centerline에서 생성한 local consistency benchmark는
모든 layer가 거의 같은 100% 수치를 보이는 것이 정상입니다. 이 데이터는 일관성
검사용이지 알고리즘 간 형상 성능 비교용이 아닙니다. 독립적인 underfill, overfill,
offset 데이터를 사용해야 형상 오차에 따른 지표 변화를 검증할 수 있습니다.

## 치명 오류 결과

가능한 경우 output 폴더에 `error.json`과 `run.log`를 남깁니다.

```json
{
  "schema_version": "4.0",
  "validator_version": "1.0.0",
  "status": "ERROR",
  "code": "MISSING_TARGET",
  "message": "target.stl is required.",
  "input_directory": "..."
}
```

## 주문 생성 산출물

UI의 `산출물` 탭에서 다음 파일을 한 번에 하나씩 생성할 수 있습니다.

| 파일 | 내용 |
| --- | --- |
| `deposited.stl` | layer union polygon을 명목 layer 높이로 extrusion한 형상 |
| `replay.html` | Target·trajectory 3D 장면과 실제 축척 XY Capsule top view |

생성 전 `validation_inputs.json`과 현재 세 입력의 SHA-256 기반 지문을 비교합니다. 다르면 생성을
차단하고 Validation 재실행을 요구합니다. worker는 임시 파일을 완성한 뒤 최종 이름으로
atomic rename합니다. 기존 파일이 있으면 명시적인 `다시 생성` 버튼으로 교체할 수
있습니다.

진행 상태와 생성 manifest는 `.waam_state/` 아래에 저장하며 결과 파일 목록과 artifact
route에는 노출하지 않습니다. UI는 산출물 생성 중에만 이 작은 상태 파일을 polling하고
완료 즉시 중단합니다.

결과 schema `1.1`, `2.0`, `3.0`은 자동 변환하지 않습니다. 파일은 삭제하지 않지만 현재 UI는
재실행이 필요하다고 안내합니다.

[루트 README로 돌아가기](../README.md)
