# 검증 방법과 판정 기준

이 문서는 Validator가 입력을 어떤 순서와 수식으로 처리하는지 설명합니다. 설정값의
타입과 범위는 [Config 참조](config-reference.md), 결과 필드는
[결과 및 산출물 참조](results-reference.md)를 함께 확인하십시오.

## 전체 처리 흐름

```text
세 입력 파일 확인
  → Config/CSV/STL 로딩과 의미 검사
  → 원본 interval 일정·거리·XY Reach 계산
  → adaptive timeline 충돌 검사
  → Deposition interval의 layer polygon 생성
  → Target STL layer slicing
  → layer/전체 형상 지표 계산
  → PASS/FAIL 결정과 산출물 생성
```

치명적 입력·Target·계산·출력 오류가 발생하면 `ERROR`로 중단합니다. 계산이 끝났지만
XY Reach, 충돌, 형상 또는 설정된 공정 기준을 위반하면 정상 결과인 `FAIL`을 기록합니다.

## Trajectory interval 해석

각 행의 `mode`는 **그 행의 시간·위치에서 다음 행까지** 적용됩니다. 따라서 로봇별
행이 `N`개이면 계산 interval은 `N-1`개이고 마지막 행은 종료 상태를 나타냅니다.

- `D`: Deposition(재료를 적층하며 이동) interval
- `T`: Travel(재료를 적층하지 않는 이동) interval
- `W`: Wait(허용 오차 안에서 위치를 유지하며 대기) interval

로봇별 첫 timestamp는 `0`, 시간은 엄격히 증가하며 마지막 mode는 `W`여야 합니다.
좌표 보간은 원본 두 절점 사이의 선형 보간입니다.

### 사전 의미 검사

- Deposition은 XY 길이가 있어야 하며 layer 허용 오차를 넘는 수직 이동을 할 수 없습니다.
- Deposition의 대표 Z는 설정한 `top` 또는 `center` 규칙으로 유효한 layer를 가리켜야 합니다.
- Deposition 명목 bead 외곽이 원형 workspace 밖으로 나가면 입력 오류입니다.
- Wait 이동량이 허용 오차보다 크면 실행 가능한 정상 FAIL입니다.
- 정지 상태의 Travel은 warning입니다.
- Deposition/Travel 속도 위반은 `fail_on_speed_violation`에 따라 warning 또는 정상 FAIL입니다.
- 모든 Deposition/Travel/Wait 원본 절점은 XY Reach 평가 대상이며 Z는 제외됩니다.

## Schedule과 경로 통계

일정 지표는 충돌용 sample이 아닌 **원본 trajectory interval**에서 정확히 계산합니다.
한 interval의 시간과 3D 길이는 다음과 같습니다.

```text
dt = time[i+1] - time[i]
distance = ||xyz[i+1] - xyz[i]||₂
```

현재 행의 mode에 따라 `dt`와 `distance`를 Deposition/Travel/Wait bucket에
누적합니다. Wait는 시간만 집계하고 거리 지표는 제공하지 않습니다.

```text
deposition mean speed = deposition length / deposition time
travel mean speed     = travel length / travel time
completion            = robot의 마지막 timestamp
makespan              = max(R1 completion, R2 completion, R3 completion)
workload imbalance    = max(completion) - min(completion)
normalized imbalance  = workload imbalance / makespan
```

결과 CSV에는 completion 기준 ratio를 중복 저장하지 않습니다. UI는 공통 비교를 위해
makespan을 100%로 사용하고 `Deposition + Travel + Wait + 완료 후 비활성`을
로봇마다 100%로 표시합니다. 완료 후 비활성은 `makespan - completion`이며 Wait와
구분합니다.

시간 비율과 거리 비율은 같을 필요가 없습니다. 예를 들어 Travel 시간이 짧아도
Travel 속도가 Deposition보다 훨씬 빠르면 Travel 거리가 더 클 수 있습니다.

## Robot XY Reach

각 로봇의 Base를 XY 평면에 투영하고 반경 `xy_reach_radius_mm`인 원을 정의합니다.

```text
xy_reach(t) = sqrt((TCP_x(t) - Base_x)² + (TCP_y(t) - Base_y)²)
xy_utilization = maximum XY distance / configured XY reach radius
xy_margin = configured XY reach radius - maximum XY distance
```

모든 원본 절점을 검사하며 `xy_reach > radius + geometry_epsilon_mm`인 절점 수와 최초·최종 위반 시간을
기록합니다. XY 원은 convex이고 trajectory는 절점 사이 선형 보간이므로 두 끝점의
XY 좌표가 원 안에 있으면 그 interval 전체도 원 안에 있습니다. 경계와 동일한 점은
통과하며 수치 오차를 위한 `geometry_epsilon_mm` 이내의 미세 초과도 통과합니다. 한 점이라도
이 범위를 초과하면 해당 로봇과 전체 XY Reach 판정이 `FAIL`입니다.

XY Reach는 Z 높이, 기구학적 자세나 관절 제한을 고려하지 않는 Base–TCP 수평거리
기반의 1차 계획 검사입니다.

`base_xyz_mm`은 로봇이 World 좌표계에 고정 설치된 기준점이며 모든 XY Reach와 Arm Capsule
계산의 원점입니다. `home_xyz_mm`은 입력 시작·종료 등에 사용할 수 있는 선택적 명목
TCP 대기점일 뿐이며, Base를 대신하거나 Reach 중심을 바꾸지 않습니다.

## Adaptive 충돌 검사

세 로봇의 원본 timestamp 합집합을 breakpoint로 사용합니다. 각 breakpoint 구간을
다음 두 조건을 모두 만족하도록 균등 세분합니다.

```text
sample dt <= max_time_step_s
각 로봇의 sample 사이 TCP 이동량 <= max_tcp_step_mm
```

전체 timeline을 메모리에 보관하지 않고 streaming batch로 처리합니다. 매 sample의
세 robot pair `(1,2)`, `(1,3)`, `(2,3)`에 대해 다음을 계산합니다.

### ARM_ENVELOPE

각 Robot Base와 현재 TCP를 잇는 유한 XY 선분을 중심선으로 하고, Robot별
`arm_envelope_radius_mm`만큼 둥글게 확장한 2D Capsule을 정의합니다. 두 중심선의
최단거리와 가장 가까운 양쪽 점을 proper crossing, 평행, 공선 overlap, endpoint 접근,
Base=TCP인 degenerate 선분까지 포함해 계산합니다.

```text
required centerline distance = radius_A + radius_B + arm_clearance_mm
capsule surface clearance    = centerline distance - radius_A - radius_B
safety margin                = centerline distance - required centerline distance
```

`touching_is_collision: true`이면 `safety margin <= geometry_epsilon_mm`, false이면
`safety margin < -geometry_epsilon_mm`일 때 충돌입니다. 즉 물리 Capsule이 겹치지 않아도
표면 사이 공통 안전거리가 부족하면 `ARM_ENVELOPE` event가 발생합니다. 로봇별 반경이
다른 경우에도 pair별 요구 거리를 따로 계산합니다.

검사를 꺼도 전체 sample에서 최소 safety margin과 최악 시점·pair는 기록하지만 event와
FAIL은 만들지 않습니다. 이 검사는 Z 높이, 관절 자세와 실제 링크 형상을 고려하지
않습니다.

### TCP_RADIUS

두 TCP의 XY 거리를 두 로봇 `tcp_radius_mm`의 합과 비교합니다.

```text
required distance = radius_a + radius_b
```

`touching_is_collision: true`이면 `distance <= required`, false이면
`distance < required`일 때 충돌입니다. 전체 최소 TCP 거리는 이 검사가 꺼져 있어도
항상 지표로 계산됩니다.

### Event 병합

동일 `(type, robot_a, robot_b)`의 연속 true sample을 한 event로 묶습니다.
중간 false gap이 `event_merge_gap_s` 이하면 하나로 병합하고, event 범위는 첫 true
시각부터 마지막 true 시각까지 기록합니다. 결과 event는 시작 시각, 종류, pair
순으로 정렬한 뒤 안정적인 ID를 부여합니다.

먼저 trajectory가 끝난 로봇은 최종 TCP 위치에 정지한 Capsule로 계속 검사합니다.
UI의 `완료 후 비활성`은 일정 상태를 뜻하며 충돌체가 작업 공간에서 제거되었다는 뜻이
아닙니다. Adaptive timeline은 sample 기반이므로 연속시간 swept collision을 수학적으로
보증하지 않습니다.

## 적층 형상 생성

각 Deposition interval을 XY centerline으로 보고 `bead_width_mm / 2`만큼 round-cap
buffer해 명목 비드 polygon을 만듭니다. Deposition 양 끝 Z의 평균으로 layer를 정하고
같은 layer의 polygon을 모두 union합니다.

Polygon은 다음 정규화 과정을 거칩니다.

- 설정 precision으로 좌표 snapping
- invalid geometry의 유효화
- 작은 polygon 제거
- Polygon/MultiPolygon과 hole 보존

이 결과를 layer 높이만큼 extrusion한 합이 `deposited.stl`입니다. 겹치는 비드의
중복 체적은 layer union 단계에서 제거됩니다.

## Target STL slicing

Target STL 또는 Scene을 하나의 mesh로 읽고, 설정에 따라 제한적인 repair를
시도합니다. `require_watertight_target: true`이면 유효한 watertight mesh가
필수입니다. Target과 trajectory가 같은 World/mm 좌표 범위에 있는지도 검사합니다.

Target 또는 deposition이 존재할 수 있는 모든 layer를 평가 대상으로 잡고 layer
중앙 Z에서 단면 polygon을 만듭니다. Coplanar 등으로 중앙 slice가 불안정하면
`정확한 Z → +epsilon → -epsilon` 순서로 fallback하며 warning을 기록합니다.

## 형상 지표

```text
Coverage        = intersection area / target area
Underfill ratio = (target - deposition) area / target area
Overfill ratio  = (deposition - target) area / target area
IoU             = intersection area / union area
```

Coverage, Underfill와 IoU처럼 이론상 단위 구간에 속하는 비율은 기하 연산의 미세한
부동소수점 오차가 0 또는 1을 넘지 않도록 `[0, 1]`로 제한합니다. Overfill ratio는
Target보다 바깥 적층 면적이 더 클 수 있으므로 1을 초과할 수 있으며 상한을 제한하지
않습니다.

Target이 비어 있고 deposition만 있는 layer도 평가하며 FAIL입니다. Target은 있지만
deposition이 없으면 Coverage 0, Underfill 1, IoU 0으로 FAIL입니다. 개별 layer의
PASS는 `minimum_layer_iou` 기준으로 결정합니다.

전체 지표는 단순한 layer 평균이 아니라 각 면적에 `layer_height_mm`를 곱한 체적
합계로 계산합니다.

```text
overall Coverage = total intersection volume / total target volume
overall Overfill = total overfill volume / total target volume
overall IoU      = total intersection volume / total union volume
failed ratio     = failed layer count / evaluated layer count
```

형상 PASS에는 다음 조건을 모두 만족해야 합니다.

- Coverage `>= minimum_overall_coverage`
- Overfill ratio `<= maximum_overall_overfill_ratio`
- IoU `>= minimum_overall_iou`
- Failed-layer ratio `<= maximum_failed_layer_ratio`

## 최종 PASS/FAIL

다음 중 하나라도 있으면 정상 `FAIL`입니다.

- Wait 위치 위반 또는 `fail_on_speed_violation: true`인 속도 위반
- Robot XY Reach 초과
- 활성화된 ARM_ENVELOPE 또는 TCP_RADIUS event
- 전체 Coverage, Overfill, IoU 또는 failed-layer ratio 기준 위반

Failure Reasons는 입력/process, XY Reach, ARM_ENVELOPE, TCP_RADIUS, 형상 threshold,
속도 위반의 고정 순서로 생성합니다. Warning만 있고 위 조건이 없으면 PASS가
가능합니다.

## 해석 한계

- Base–TCP XY Capsule은 실제 링크와 joint configuration을 표현하지 않습니다.
- XY Capsule 안전 여유가 부족하면 실제 Z 분리 여부와 관계없이 ARM_ENVELOPE로 봅니다.
- TCP radius는 공구·토치·케이블의 실제 3D 형상을 대체하지 않습니다.
- 일정한 bead 폭과 layer 높이를 가정합니다.
- 시작·정지, 가감속, 열이력, 비드 단면 변화, 용융풀, 변형과 잔류응력을 계산하지
  않습니다.
- Validator는 경로를 생성하거나 수정하지 않습니다.

`PASS`는 이 모델과 설정의 검증 기준을 만족한다는 뜻이지 실제 장비 운전 승인이나
품질 보증을 뜻하지 않습니다.

[루트 README로 돌아가기](../README.md)
