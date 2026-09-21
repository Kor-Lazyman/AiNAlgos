# Config 참조

`config.yaml`은 한 WAAM 작업의 로봇 배치, 계산 해상도, 공정 기준값과 충돌·형상
합격 기준을 정의합니다. Config 자체에는 버전 필드를 두지 않습니다.
WAAM Validator 애플리케이션 버전과 Config 항목은 독립적으로 관리하며,
`schema_version`을 포함한 알 수 없는 필드는 오타로 간주해 거부합니다. 숫자에는
`NaN`과 무한대를 사용할 수 없습니다.

공식 참조 설정 파일은 저장소 루트의 [config.yaml](../config.yaml)입니다. 실행 가능한
소형 입력 묶음은 별도의 [sample job](../examples/sample_job/config.yaml)을 참고하십시오.

## 최상위 구조

```yaml
simulation: { ... }
robots: [ ... ]
process: { ... }
workspace: { ... }
collision: { ... }
validation: { ... }
shape_validation: { ... }
```

별도 설명이 없으면 거리와 좌표는 밀리미터(mm), 시간은 초(s), 속도는
밀리미터/초(mm/s), 면적은 제곱밀리미터(mm²)입니다.

## `simulation`: 충돌 계산 해상도와 처리량

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `max_time_step_s` | float, `> 0` | 충돌 검사용 인접 샘플 사이의 최대 시간입니다. 원본 timestamp 사이가 이 값보다 길면 선형 보간 샘플을 추가합니다. 작게 할수록 짧은 충돌을 찾기 쉬워지지만 계산량이 증가합니다. Replay의 프레임 간격과는 무관합니다. |
| `max_tcp_step_mm` | float, `> 0` | 충돌 검사용 인접 샘플 사이에서 각 로봇 TCP(Tool Center Point)가 움직일 수 있는 최대 3차원 거리입니다. 빠르게 이동하는 구간을 거리 기준으로 추가 분할합니다. 작게 할수록 공간 검출 해상도와 계산량이 증가합니다. |
| `event_merge_gap_s` | float, `>= 0` | 같은 충돌 종류와 같은 로봇 쌍에서 충돌이 잠깐 끊겼다가 다시 발생했을 때 하나의 이벤트로 합칠 최대 비충돌 시간입니다. 개별 샘플의 충돌 판정은 바꾸지 않고 `collision_events.csv`의 이벤트 묶음만 바꿉니다. `0`이면 실제로 이어진 구간만 합칩니다. |
| `batch_size` | int, `>= 1000` | 충돌 샘플을 메모리에 한 번에 올려 벡터 연산하는 개수입니다. 작으면 반복 처리 오버헤드가 늘고 크면 최대 메모리가 늘어납니다. 샘플 간격이나 판정 결과를 바꾸는 설정은 아닙니다. |

Validator는 세 로봇의 원본 timestamp 합집합을 모두 보존한 뒤
`max_time_step_s`와 `max_tcp_step_mm`을 **동시에** 만족할 때까지 각 구간을 나눕니다.
따라서 둘 중 더 촘촘한 조건이 실제 샘플 간격을 결정합니다. 이 방식은 이산 샘플
검사이므로 값을 줄이면 누락 가능성을 낮추지만 연속시간 충돌의 수학적 보증은 아닙니다.

예를 들어 기준 이동 속도가 150 mm/s일 때 `max_time_step_s: 0.1`만 적용하면 한
샘플에서 15 mm를 이동합니다. `max_tcp_step_mm: 5.0`도 함께 설정하면 거리 조건이 더
엄격하므로 약 0.033초 이하 간격으로 나뉩니다.

## `robots`: 로봇 설치점, 대기점과 안전영역

정확히 세 항목이어야 하며 ID `1`, `2`, `3`이 각각 한 번씩 있어야 합니다.

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `id` | `1`, `2`, `3` | `trajectory.csv`의 `robot_id`와 Config 로봇을 연결하는 식별자입니다. |
| `base_xyz_mm` | float 3개 | World 좌표계에서 움직이지 않는 **로봇 설치 기준점(Base)**입니다. XY Reach 거리는 이 점의 XY 좌표부터 TCP의 XY 좌표까지 계산하고, 2D Arm Capsule 중심선의 고정 끝점으로 사용합니다. trajectory의 시작 위치가 아닙니다. |
| `home_xyz_mm` | float 3개 또는 생략 | World 좌표계에서 공구 기준점인 **TCP의 명목 대기 위치(Home)**입니다. 경로 생성기가 작업 시작·종료점이나 안전 대기점으로 사용할 수 있고 UI에 별도 표식으로 표시됩니다. Base와 달리 로봇 본체의 설치점이 아니며, 현재 Validator는 trajectory 시작·종료 좌표가 Home과 같은지를 강제하지 않습니다. |
| `tcp_radius_mm` | float, `> 0` | TCP 주변의 충돌 판정용 XY 안전 반경입니다. 실제 점의 물리적 반지름이 아니라 토치·엔드 이펙터와 안전 여유를 대표합니다. 두 로봇의 요구 중심 간격은 두 `tcp_radius_mm`의 합입니다. 적층 비드 폭이나 Reach에는 영향을 주지 않습니다. |
| `arm_envelope_radius_mm` | float, `> 0` | Base에서 현재 TCP까지의 XY 중심선을 둘러싸는 Capsule의 물리적 대표 반경입니다. 전체 폭은 이 값의 2배입니다. 관절 자세를 재현하는 링크 반경이 아니라 팔이 점유한다고 보수적으로 가정할 평면 폭입니다. 공통 추가 안전거리와는 분리해 설정합니다. |
| `xy_reach_radius_mm` | float, `> 0` | Base의 XY 투영을 중심으로 TCP가 수평면에서 도달할 수 있다고 허용하는 원의 반경입니다. 모든 Deposition·Travel·Wait 절점의 XY 거리를 검사하고 Z는 무시하며, 초과하면 실행 가능한 정상 `FAIL`입니다. 구형 `reach_radius_mm`는 거부합니다. |

Base와 Home의 핵심 차이는 다음과 같습니다.

```text
Base = 고정된 로봇 설치 기준점
Home = 이동 가능한 TCP의 명목 대기 좌표
XY Reach 거리 = sqrt((TCP_x - Base_x)² + (TCP_y - Base_y)²)
```

세 Base 좌표는 서로 달라야 하고, XY 투영이 면적을 갖는 삼각형을 이루어야 합니다.
현재 XY Reach, Arm Capsule과 TCP 안전 반경 검사는 XY 평면에서 수행합니다. 따라서 Z가 다른
공구도 XY가 가까우면 보수적으로 충돌 판정을 받을 수 있습니다.

## `process`: 공정과 경로 생성 기준값

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `deposition_speed_mm_s` | float, `> 0` | Deposition(재료를 적층하며 이동) 구간의 기준 속도입니다. 실제 구간 평균속도와 비교합니다. |
| `travel_speed_mm_s` | float, `> 0` | Travel(재료를 적층하지 않고 이동) 구간의 최대 기준 속도입니다. 실제 Travel 속도가 허용 상한을 넘는지 검사합니다. |
| `layer_height_mm` | float, `> 0` | 한 적층 레이어의 명목 높이입니다. Deposition 좌표를 레이어 번호에 대응시키고 `deposited.stl`을 압출할 때 사용합니다. |
| `bead_width_mm` | float, `> 0` | Deposition 중심선을 좌우로 확장해 명목 적층 영역을 만드는 비드 폭입니다. 중심선 양쪽에 절반씩 적용하며 `tcp_radius_mm`과는 무관합니다. |
| `build_plane_z_mm` | float | 첫 레이어가 쌓이는 기준 평면의 World Z 좌표입니다. Target STL과 trajectory가 같은 World 좌표계를 사용해야 합니다. |
| `tcp_z_reference` | `top` 또는 `center` | Deposition 경로의 TCP Z를 적층 레이어의 상면(`top`)으로 볼지 중심면(`center`)으로 볼지 지정합니다. 레이어 번호와 예상 Z 계산에 직접 사용됩니다. |
| `safe_travel_z_mm` | float 또는 생략 | 외부 경로 생성기가 Travel 구간의 안전 상승 높이로 사용할 수 있는 참조값입니다. 현재 Validator는 trajectory를 생성·수정하지 않으므로 이 값만으로 경로를 올리거나 별도 판정을 수행하지 않습니다. |
| `arc_on_time_s` | float, `>= 0`, 또는 생략 | 외부 경로 생성기가 Deposition 시작 전 아크 점화 대기를 만들 때 사용할 참조시간입니다. 기존 trajectory의 시간을 자동 변경하지 않습니다. |
| `arc_off_time_s` | float, `>= 0`, 또는 생략 | 외부 경로 생성기가 Deposition 종료 후 아크 소호 대기를 만들 때 사용할 참조시간입니다. 기존 trajectory의 시간을 자동 변경하지 않습니다. |

`deposition_speed_mm_s`는 기준값보다 빠르거나 느린 양쪽 편차를 검사합니다.
`travel_speed_mm_s`는 상한으로 사용하므로 느린 Travel은 위반이 아닙니다. 허용 범위와
위반을 경고 또는 `FAIL`로 처리할지는 `validation`에서 정합니다.

## `workspace`: 적층 허용 영역

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `shape` | `circle_xy` | 현재 지원하는 작업영역 형상입니다. World XY 평면의 원만 지원합니다. |
| `center_xy_mm` | float 2개 | 원형 적층 작업영역 중심의 World X, Y 좌표입니다. |
| `radius_mm` | float, `> 0` | 적층이 허용되는 원의 반경입니다. 로봇 Reach 반경이나 TCP 안전 반경이 아닙니다. |

Workspace 원 전체가 세 Robot Base의 XY 삼각형 내부에 있어야 합니다. 모든
Deposition(재료를 적층하며 이동) 구간은 중심선뿐 아니라 명목 비드 외곽까지 원 안에
있어야 하므로, 허용 중심선 반경은 대략 `radius_mm - bead_width_mm / 2`입니다.

## `collision`: 로봇 간 충돌 기준

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `check_arm_envelope` | bool | Base–TCP XY 중심선에 `arm_envelope_radius_mm` 폭을 준 Capsule 사이의 안전 여유를 충돌로 판정할지 정합니다. 꺼도 최소 안전 여유는 지표로 계산합니다. |
| `arm_clearance_mm` | float, `>= 0` | 두 물리 Capsule 표면 사이에 추가로 요구하는 공통 안전거리입니다. Pair의 요구 중심선 거리는 `radius_A + radius_B + arm_clearance_mm`입니다. 시각화의 점선 판정 외곽선에는 각 Capsule에 절반씩 더해 표시합니다. |
| `check_tcp_radius` | bool | 두 TCP의 XY 거리가 각 로봇 `tcp_radius_mm` 합보다 가까운지 검사할지 정합니다. 꺼도 최소 TCP 거리는 지표로 계산합니다. |
| `touching_is_collision` | bool | Arm 안전 여유 또는 TCP 거리가 정확히 판정 경계와 같을 때 충돌로 포함할지 정합니다. `true`이면 경계 접촉도 충돌입니다. |
| `geometry_epsilon_mm` | float, `> 0` | Arm Capsule 접촉 경계와 XY Reach 경계 계산에서 부동소수점 오차를 흡수하기 위한 길이 허용치입니다. 물리적 안전 여유 대신 사용하면 안 됩니다. |

검사를 끄면 해당 항목은 `FAIL` 원인이 되지 않고 비활성화 경고가 기록됩니다. 예를
들어 Arm 반경이 각각 100 mm이고 공통 안전거리가 50 mm라면 요구 중심선 간격은
250 mm입니다. 실제 Capsule 표면 간격이 50 mm일 때 안전 여유가 0 mm입니다.

구형 `check_arm_crossing` 또는 `arm_envelope_radius_mm`이 없는 Robot 설정은 자동
변환하지 않고 Config 오류로 거부합니다. 기존 생성 알고리즘은 각 Robot의 대표 폭과
공통 안전거리를 명시하도록 연동을 갱신해야 합니다.

## `validation`: 입력 의미와 공정 허용 오차

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `wait_position_tolerance_mm` | float, `>= 0` | Wait(현재 위치를 유지하며 대기) 구간에서 노이즈로 허용할 최대 3차원 이동거리입니다. 초과하면 실행 가능한 정상 `FAIL`입니다. |
| `layer_z_tolerance_mm` | float, `>= 0` | Deposition 구간 양 끝의 Z 변화와 계산된 레이어 기준 Z의 차이에 허용하는 오차입니다. 레이어를 결정할 수 없으면 입력 오류로 중단합니다. |
| `speed_relative_tolerance` | float, `>= 0` | 기준 속도 대비 허용 상대오차입니다. `0.1`은 10%를 뜻합니다. Deposition은 양방향 편차, Travel은 상한 초과에 적용됩니다. |
| `fail_on_speed_violation` | bool | `true`이면 속도 위반을 정상 `FAIL` 원인으로, `false`이면 경고로 기록합니다. |
| `require_watertight_target` | bool | `target.stl`이 구멍 없이 밀폐된 체적 mesh여야 하는지 정합니다. `true`인데 밀폐되지 않았으면 입력 오류입니다. |
| `attempt_target_repair` | bool | Target mesh가 유효하지 않을 때 제한적인 자동 repair를 시도할지 정합니다. 원본 STL 파일 자체는 수정하지 않습니다. |
| `target_volume_discrepancy_warning_ratio` | float, `>= 0` | STL mesh 체적과 레이어 단면 적분 체적의 상대 차이가 이 비율을 넘을 때 경고합니다. `0.02`는 2%입니다. |

정지한 Travel 구간은 경고입니다. Deposition 구간의 길이가 0이거나, 수직 이동이
허용치를 넘거나, 레이어에 대응할 수 없거나, 적층 비드가 Workspace 밖으로 나가면
후속 형상 계산을 신뢰할 수 없어 입력 오류로 중단합니다.

## `shape_validation`: Target 대비 적층 형상 합격 기준

| 필드 | 타입·제약 | 상세 의미 |
| --- | --- | --- |
| `polygon_buffer_resolution` | int, `>= 1` | Deposition 중심선 끝의 둥근 cap과 곡선 buffer를 근사할 때 사분원당 사용하는 선분 수입니다. 높이면 곡선이 부드러워지지만 형상 연산량이 증가합니다. |
| `polygon_snap_tolerance_mm` | float, `> 0` | 레이어 폴리곤 좌표를 정밀도 격자에 맞추는 간격입니다. 미세한 수치 틈과 겹침을 안정화하며 지나치게 크게 잡으면 작은 형상이 사라질 수 있습니다. |
| `minimum_overall_coverage` | float, `0..1` | 전체 Target 면적 중 적층과 겹친 면적의 최소 비율입니다. `0.95`는 95% 이상을 요구합니다. |
| `maximum_overall_overfill_ratio` | float, `>= 0` | Target 밖에 추가로 적층된 전체 면적을 Target 면적으로 나눈 값의 최대치입니다. `0.05`는 5% 이하를 요구합니다. |
| `minimum_overall_iou` | float, `0..1` | 전체 Target과 적층 형상의 IoU(Intersection over Union, 교집합/합집합) 최소값입니다. |
| `minimum_layer_iou` | float, `0..1` | 개별 레이어를 통과시키는 IoU 최소값입니다. |
| `maximum_failed_layer_ratio` | float, `0..1` | `minimum_layer_iou`를 충족하지 못한 레이어 수를 평가 레이어 수로 나눈 비율의 최대치입니다. |
| `area_epsilon_mm2` | float, `> 0` | 이 값 이하의 미소 폴리곤을 제거하고 면적이 비었다고 판단하는 수치 허용치입니다. |

전체 형상 `PASS`는 Coverage, Overfill ratio, 전체 IoU, 실패 레이어 비율 조건을
모두 만족해야 합니다. Underfill은 Coverage와 같은 교집합을 반대 관점에서 나타내며
`Underfill ratio = 1 - Coverage`입니다.

## 결과 파일 정책

Config는 결과 파일 생성을 제어하지 않습니다. Validation은 schema 4.0의 핵심
JSON·CSV·보고서·로그·입력 지문을 항상 기록합니다. 화면과 중복되는 정적 PNG는
지원하지 않습니다. `deposited.stl`과 `replay.html`은 Validation 완료 후 UI의
`산출물` 탭에서 필요한 경우에만 생성합니다.

구형 Config에 `output:` 블록이 남아 있으면 오타를 조용히 무시하지 않고
`INVALID_CONFIG_SCHEMA`로 중단합니다. 블록 전체를 삭제하십시오. 파일 목록과 주문
생성 절차는 [결과 참조](results-reference.md)를 확인하십시오.

## Config 참조 기준

아래 내용은 저장소 루트의 [config.yaml](../config.yaml)과 같은 공식 참조 기준입니다.
모든 필수 항목과 선택적인 Home·경로 생성 참조값을 함께 보여줍니다. 수치는 장비와
공정에 맞게 변경해야 하며, 참조값 자체가 안전을 보증하지 않습니다.

```yaml
simulation:
  max_time_step_s: 0.1
  max_tcp_step_mm: 5.0
  event_merge_gap_s: 0.2
  batch_size: 10000
robots:
  - id: 1
    base_xyz_mm: [-1400.0, 0.0, 0.0]
    home_xyz_mm: [-1000.0, 0.0, 1000.0]
    tcp_radius_mm: 100.0
    arm_envelope_radius_mm: 100.0
    xy_reach_radius_mm: 1500.0
  - id: 2
    base_xyz_mm: [700.0, 1212.4356, 0.0]
    home_xyz_mm: [500.0, 866.025404, 1000.0]
    tcp_radius_mm: 100.0
    arm_envelope_radius_mm: 100.0
    xy_reach_radius_mm: 1500.0
  - id: 3
    base_xyz_mm: [700.0, -1212.4356, 0.0]
    home_xyz_mm: [500.0, -866.025404, 1000.0]
    tcp_radius_mm: 100.0
    arm_envelope_radius_mm: 100.0
    xy_reach_radius_mm: 1500.0
process:
  deposition_speed_mm_s: 8.0
  travel_speed_mm_s: 150.0
  layer_height_mm: 2.0
  bead_width_mm: 8.0
  build_plane_z_mm: 0.0
  tcp_z_reference: center
  safe_travel_z_mm: 1000.0
  arc_on_time_s: 1.0
  arc_off_time_s: 1.0
workspace:
  shape: circle_xy
  center_xy_mm: [0.0, 0.0]
  radius_mm: 700.0
collision:
  check_arm_envelope: true
  arm_clearance_mm: 50.0
  check_tcp_radius: true
  touching_is_collision: true
  geometry_epsilon_mm: 1.0e-6
validation:
  wait_position_tolerance_mm: 0.001
  layer_z_tolerance_mm: 0.25
  speed_relative_tolerance: 0.1
  fail_on_speed_violation: true
  require_watertight_target: true
  attempt_target_repair: true
  target_volume_discrepancy_warning_ratio: 0.02
shape_validation:
  polygon_buffer_resolution: 8
  polygon_snap_tolerance_mm: 0.0001
  minimum_overall_coverage: 0.80
  maximum_overall_overfill_ratio: 0.30
  minimum_overall_iou: 0.90
  minimum_layer_iou: 0.80
  maximum_failed_layer_ratio: 0.05
  area_epsilon_mm2: 1.0e-6
```

[루트 README로 돌아가기](../README.md)
