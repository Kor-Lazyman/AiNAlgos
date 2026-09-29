# WAAM Validator: 입력물 인터페이스

## 1. 문서 목적

이 문서는 경로 계획, 스케줄링, 최적화, RL, 휴리스틱 등 어떤 알고리즘을 사용하더라도 최종 WAAM 작업 계획을 WAAM Validator 1.0.0에 입력할 수 있도록 공통 산출물 계약을 정의한다.

알고리즘의 내부 표현은 자유롭다. 다만 검증 전에 알고리즘 결과를 본 문서의 `trajectory.csv`로 변환하는 Exporter/Adapter를 제공해야 한다.

## 2. 입력 패키지

Validator에 전달하는 하나의 작업 디렉터리에는 다음 세 파일이 모두 필요하다.

```text
validation_job/
├── config.yaml
├── trajectory.csv
└── target.stl
```

파일명은 대소문자를 포함해 위와 같아야 한다. 알고리즘의 로그, 체크포인트, 학습 결과 및 기타 진단 파일은 검증 작업 디렉터리 밖에 보관하는 것을 권장한다.

### 2.1 산출물 책임

| 대상 | 원본 소유자 | 알고리즘/Exporter의 책임 |
|---|---|---|
| `config.yaml` | 검증 시나리오 제공자 | 제공받은 파일을 변경하지 않고 복사 |
| `target.stl` | 검증 시나리오 제공자 | 제공받은 목표 형상을 변경하지 않고 복사 |
| `trajectory.csv` | 알고리즘 제공자 | 알고리즘의 최종 계획을 시간 지정 TCP trajectory로 변환해 생성 |

`config.yaml`의 충돌 반경이나 형상 합격 기준을 알고리즘이 자신에게 유리하게 변경해서는 안 된다. 알고리즘 비교 시에는 모든 알고리즘에 동일한 `config.yaml`과 `target.stl`을 사용한다.

## 3. 좌표계와 단위

`config.yaml`, `trajectory.csv`, `target.stl`은 모두 동일한 World 좌표계를 사용해야 한다.

- 길이 및 좌표 단위: mm
- 시간 단위: s
- `trajectory.csv`의 XYZ: 로봇 관절값이 아닌 TCP의 World 좌표
- `config.yaml`의 `base_xyz_mm`: 움직이지 않는 로봇 설치 기준점의 World 좌표
- `config.yaml`의 `home_xyz_mm`: 선택적인 TCP 명목 대기 위치의 World 좌표
- `target.stl`의 vertex: World 좌표의 mm 단위 점

Base는 XY Reach와 단순 팔 선분의 시작점이고, Home은 TCP가 대기하는 위치다. 두 좌표를
같은 개념으로 사용하면 안 된다. 현재 Validator는 Home을 시각적·경로 생성 참조로
사용하며 trajectory 시작·종료 좌표와의 일치를 강제하지 않는다.

Validator 1.0.0은 STL scale 추정이나 trajectory–target 자동 registration을 하지 않는다. 좌표계가 다르면 입력 오류 또는 형상 검증 실패로 처리된다.

## 4. `trajectory.csv` 계약

### 4.1 고정 스키마

CSV는 UTF-8로 저장하고 정확히 다음 6개 컬럼만 사용한다.

```csv
robot_id,time_s,x_mm,y_mm,z_mm,mode
```

| 컬럼 | 입력값 | 의미 |
|---|---|---|
| `robot_id` | 정수 `1`, `2`, `3` | 로봇 ID |
| `time_s` | 유한한 실수 | waypoint 시간 |
| `x_mm` | 유한한 실수 | TCP World X |
| `y_mm` | 유한한 실수 | TCP World Y |
| `z_mm` | 유한한 실수 | TCP World Z |
| `mode` | `T`, `D`, `W` 중 하나 | 현재 행에서 다음 행까지의 동작 |

다음은 허용하지 않는다.

- 추가 컬럼과 잘못된 컬럼 순서
- 빈 셀, 주석 행
- `NaN`, `Inf`, `-Inf`
- `R1`, `robot1` 등의 문자열 로봇 ID
- `TRAVEL`, `DEPOSIT`, `WAIT` 등의 긴 mode 이름
- `t`, `d`, `w` 등의 소문자 mode
- 소수점 구분자로 `,`를 사용한 숫자

### 4.2 mode 정의

| mode | 이름 | 의미 |
|---|---|---|
| `T` | TRAVEL | 적층하지 않고 TCP 이동 |
| `D` | DEPOSIT | TCP가 이동하는 동안 적층 |
| `W` | WAIT | 같은 위치에서 대기 |

### 4.3 시간구간 해석

각 행의 `mode`는 그 행의 시각부터 같은 로봇의 다음 행 시각 직전까지의 구간에 적용된다.

```text
row k:     time=t_k,     position=P_k,     mode=M_k
row k+1:   time=t_(k+1), position=P_(k+1), mode=M_(k+1)

[t_k, t_(k+1)) 구간의 동작 = M_k
```

구간 내 TCP 위치는 두 waypoint 사이를 선형 보간한다. 따라서 선분 `A → B`를 적층하려면 A 행의 mode를 `D`로 지정해야 한다. B 행의 mode는 B에 도착한 후의 동작을 정의한다.

```csv
robot_id,time_s,x_mm,y_mm,z_mm,mode
1,0.0,-1000.0,-600.0,100.0,T
1,4.0,0.0,0.0,2.0,D
1,14.0,80.0,0.0,2.0,T
1,18.0,-1000.0,-600.0,100.0,W
```

위 예제의 의미는 다음과 같다.

- `0.0 ≤ t < 4.0`: 적층 시작점으로 `T`
- `4.0 ≤ t < 14.0`: `(0, 0, 2) → (80, 0, 2)` 선분을 `D`
- `14.0 ≤ t < 18.0`: 안전 주차 위치로 `T`
- `18.0` 이후: 마지막 TCP 위치에 주차

### 4.4 로봇별 필수 규칙

- 로봇 `1`, `2`, `3`이 모두 존재해야 한다.
- 각 로봇은 최소 2개 행을 가져야 한다.
- 각 로봇의 첫 `time_s`는 `0.0`이어야 한다.
- 같은 로봇 내 `time_s`는 중복 없이 엄격하게 증가해야 한다.
- 행은 `robot_id` 오름차순, 그 안에서 `time_s` 오름차순으로 정렬해야 한다.
- 각 로봇의 마지막 행 mode는 `W`여야 한다.
- 마지막 행의 시각은 해당 로봇의 완료시간이다.
- 로봇별 완료시간은 서로 달라도 된다.
- 먼저 종료한 로봇은 전체 makespan까지 마지막 위치에 주차된 것으로 간주한다.

마지막 TCP 위치는 다른 로봇의 후속 이동을 방해하지 않는 안전한 주차 위치여야 한다.

### 4.5 mode별 필수 규칙

#### `W` 구간

- 시작점과 종료점의 TCP 위치가 같아야 한다.
- 위치 변화는 `validation.wait_position_tolerance_mm` 이내만 허용한다.
- arc on/off, 냉각, 동기화 대기는 필요한 시간을 timestamp에 반영한 `W` 구간으로 표현한다.

#### `D` 구간

- XY 선분 길이가 0보다 커야 한다.
- 정지시간은 `D`가 아닌 `W`로 표현한다.
- 한 구간에서 Z 변화는 `validation.layer_z_tolerance_mm` 이내여야 한다.
- 수직 적층 및 서로 다른 layer를 연결하는 `D` 구간은 허용하지 않는다.
- 다음 구간으로 옮겨 갈 때는 `T`를 사용한다.

#### `T` 구간

- XYZ 방향 이동을 허용한다.
- 위치가 변하지 않는 `T` 구간도 파싱은 가능하지만 warning이 발생한다.
- `T` 구간은 적층 형상 생성에 사용하지 않는다.

### 4.6 시간과 속도

`trajectory.csv`의 `time_s`가 실제 계획 시간의 유일한 기준이다.

- Validator는 설정 속도로 timestamp를 다시 생성하지 않는다.
- 알고리즘 또는 Exporter가 travel, deposition, wait 시간을 모두 timestamp에 반영해야 한다.
- `D` 구간 속도는 `process.deposition_speed_mm_s`와 비교한다.
- `T` 구간 속도는 `process.travel_speed_mm_s`의 허용 상한과 비교한다.
- 속도 위반을 warning으로 남길지 FAIL로 처리할지는 `validation.fail_on_speed_violation`에 따른다.

## 5. Layer와 적층 형상 표현

Validator는 `D` 구간의 각 XY 선분을 명목 `bead_width_mm`로 buffer하여 적층 형상을 생성한다. 로봇 자세나 관절각은 입력하지 않으며, TCP 자세는 지면 normal로 고정된 것으로 간주한다.

### 5.1 `tcp_z_reference: top`

Layer `k`의 `D` 경로 Z는 다음과 같다.

```text
z = build_plane_z_mm + (k + 1) × layer_height_mm
```

예를 들어 build plane이 0 mm이고 layer 높이가 2 mm이면 layer 0, 1, 2의 `D` Z는 각각 2, 4, 6 mm이다.

### 5.2 `tcp_z_reference: center`

Layer `k`의 `D` 경로 Z는 다음과 같다.

```text
z = build_plane_z_mm + (k + 0.5) × layer_height_mm
```

허용오차에 의존하기보다 위 수식의 Z를 정확히 사용하는 것을 권장한다.

### 5.3 곡선 경로

인접한 waypoint 사이는 항상 직선으로 해석한다. 원호, spline 등의 곡선 적층 경로는 chord 오차가 충분히 작도록 여러 `D` 선분으로 분할해야 한다. Validator의 adaptive sampling은 주어진 직선 선분을 세분할 뿐, 생략된 곡률을 복원하지 않는다.

## 6. `config.yaml` 계약

`config.yaml`은 검증 시나리오의 환경과 합격 기준을 정의한다. Config에는 별도의
버전 필드를 두지 않는다. 모든 필수 필드가 존재해야 하고 `schema_version`을 포함한
알 수 없는 추가 필드는 허용하지 않는다.

| 그룹 | 주요 역할 |
|---|---|
| `simulation` | 적응형 충돌 샘플의 시간·TCP 이동 간격, 이벤트 병합과 처리 묶음 크기 |
| `robots` | ID 1·2·3의 고정 Base, 선택적 Home TCP, TCP 반경, 2D Arm Capsule 반경과 XY Reach 반경 |
| `process` | Deposition(적층)·Travel(비적층 이동) 기준 속도, 레이어 높이, 비드 폭, 빌드 평면과 TCP Z 해석 기준 |
| `workspace` | World XY 평면에서 파트를 적층할 수 있는 필수 원형 영역 |
| `collision` | Arm Capsule 활성화·공통 안전거리, TCP 반경, 경계 접촉 및 기하 오차 |
| `validation` | 대기 위치, layer Z, 속도, STL 검사 정책 |
| `shape_validation` | coverage, overfill, IoU 및 실패 layer 기준 |

전체 예제는 [`examples/sample_job/config.yaml`](../examples/sample_job/config.yaml)을 기준으로 삼는다.

`workspace`는 다음 형식을 사용한다. `center_xy_mm`는 World 좌표이고
`radius_mm`는 원의 반경이다. 원 전체는 세 robot base의 XY 좌표가 이루는 삼각형
내부에 있어야 한다.
Validator는 `D` interval의 두 endpoint에 bead 반폭을 더한 적층 외곽이 원 안에
있는지 검사한다. `T`와 `W`는 home 및 safe travel을 위해 원 밖에 있을 수 있다.

각 `robots[]`의 `xy_reach_radius_mm`는 `base_xyz_mm`의 XY 투영을 중심으로 하는
수평면 원의 반경이다. 모든 D/T/W TCP 절점의 XY 거리가 이 반경 안에 있어야 하며,
Z 좌표는 Reach에 사용하지 않는다. 반경을 초과하면 입력 파싱을
중단하지 않고 Validation `FAIL`로 판정한다.

```yaml
workspace:
  shape: circle_xy
  center_xy_mm: [0.0, 0.0]
  radius_mm: 700.0
```

## 7. `target.stl` 계약

- 파일명은 정확히 `target.stl`이어야 한다.
- 알고리즘이 생성한 예상 적층 형상이 아니라, 시나리오가 제공한 목표 형상이어야 한다.
- vertex 좌표는 trajectory와 동일한 World 좌표계의 mm 단위여야 한다.
- 형상은 `build_plane_z_mm` 아래로 내려가지 않아야 한다.
- vertex와 bounds는 유한해야 하며 유효한 triangle mesh여야 한다.
- `require_watertight_target: true`인 경우 watertight closed mesh여야 한다.
- Validator는 `attempt_target_repair: true`인 경우에만 제한적 mesh repair를 시도한다.

## 8. 충돌 해석에 필요한 알고리즘 주의사항

Validator 1.0.0은 각 로봇을 Base에서 TCP까지의 XY 중심선과 폭이 있는 2D Capsule로
단순화한다. 각 Robot의 `arm_envelope_radius_mm`은 물리적 대표 반경이며 전체 폭은
2배다. 두 Robot의 요구 중심선 간격은 다음과 같다.

```text
radius_A + radius_B + collision.arm_clearance_mm
```

- 모드와 관계없이 `T`, `D`, `W` 모든 시간에 충돌을 검사한다.
- 두 Base–TCP 유한 선분의 XY 최단거리에서 Capsule 반경과 공통 안전거리를 뺀
  safety margin 및 TCP 간 XY 거리를 검사한다.
- 이 충돌 모델은 Z 높이 차이를 사용하지 않는 보수적 top-view 판정이다.
- 대기 중인 로봇도 공간에서 사라지지 않는다.
- 먼저 종료한 로봇의 마지막 주차 위치도 전체 makespan까지 충돌 검사 대상이다.

따라서 알고리즘은 적층 순서뿐 아니라 travel 경로, wait 위치, 시간 동기화, 최종 주차 위치까지 결정해야 한다.

구형 `check_arm_crossing` Config나 Robot별 `arm_envelope_radius_mm`이 없는 Config는
자동 변환하지 않고 실행 불가로 처리한다. `Multi_robot_DED_NCO` 등 외부 알고리즘의
Exporter도 새 필수 필드를 내보내도록 별도로 갱신해야 한다.

## 9. 알고리즘 결과를 CSV로 변환하는 방법

### 9.1 권장 중간 표현

알고리즘 내부에서 다음과 같은 시간 지정 segment 목록을 만들면 특정 알고리즘에 의존하지 않고 CSV로 변환할 수 있다.

```python
Segment(
    robot_id=1,
    mode="D",
    start_time_s=4.0,
    end_time_s=14.0,
    start_xyz_mm=(0.0, 0.0, 2.0),
    end_xyz_mm=(80.0, 0.0, 2.0),
)
```

로봇별 segment는 다음을 만족해야 한다.

- 첫 segment의 `start_time_s == 0.0`
- 모든 segment의 `end_time_s > start_time_s`
- 이전 segment의 종료시간과 다음 segment의 시작시간이 같음
- 이전 segment의 종료점과 다음 segment의 시작점이 같음
- 시간 공백은 segment 생략이 아닌 `W` segment로 표현

### 9.2 Export 규칙

1. 각 segment의 시작시각, 시작점, mode를 CSV 행으로 출력한다.
2. 로봇의 마지막 segment 종료점을 mode `W`인 마지막 행으로 추가한다.
3. 모든 행을 `robot_id`, `time_s` 오름차순으로 정렬한다.
4. 고정 헤더를 포함한 UTF-8 CSV로 저장한다.

### 9.3 알고리즘 출력 수준별 필요 변환

| 알고리즘 출력 | Exporter가 추가로 결정해야 할 것 |
|---|---|
| 시간 지정 TCP trajectory | 스키마·mode·정렬 변환 |
| 로봇별 toolpath와 속도 | 구간별 timestamp, wait, 안전 주차 |
| 작업 할당과 순서 | 적층 centerline, travel 경로, 속도, wait, timestamp, 주차 |
| 순수 공정 순서 | 로봇 할당부터 전체 시간 지정 TCP 경로까지 |

작업 할당이나 순서만 제공하는 알고리즘 결과로는 충돌과 적층 형상을 직접 검증할 수 없다. Exporter 또는 후처리 path planner가 반드시 실제 TCP 경로와 시간을 구체화해야 한다.

## 10. Exporter 납품 인터페이스

알고리즘 제공자는 다음과 같은 독립 실행형 Exporter를 제공하는 것을 권장한다.

```text
python export_waam.py \
  --result algorithm_result.json \
  --scenario validation_scenario \
  --output validation_job
```

Exporter는 다음 작업을 수행해야 한다.

1. `algorithm_result.json` 등 알고리즘 고유 결과를 읽는다.
2. 제공된 시나리오의 `config.yaml`과 `target.stl`을 읽는다.
3. 세 로봇의 연속된 `T/D/W` segment를 생성한다.
4. 본 문서의 고정 스키마로 `trajectory.csv`를 생성한다.
5. 원본 `config.yaml`과 `target.stl`을 변경 없이 출력 디렉터리로 복사한다.
6. 생성 후 `waam-validator check` 통과 여부를 확인한다.

## 11. 인수 절차

### 11.1 입력 인터페이스 검사

```powershell
waam-validator check .\validation_job
```

Exit code `0`이어야 한다. 이 검사는 다음을 확인한다.

- 세 필수 파일의 존재
- config 스키마와 값 제약
- CSV 헤더, 자료형, 정렬, 로봇, 시간, mode 제약
- `W`, `D`, `T` 구간의 의미적 유효성
- target mesh 로딩과 watertight 정책
- deposition과 target의 기본 좌표계 일관성

### 11.2 완전 검증

```powershell
waam-validator run .\validation_job --json
```

| Exit code | 의미 |
|---:|---|
| `0` | 입력이 유효하고 충돌·형상 기준 PASS |
| `1` | 입력은 계산 가능하지만 알고리즘 결과가 충돌 또는 형상 기준 FAIL |
| `2` | config 또는 trajectory 입력 오류 |
| `3` | target STL 로딩·유효성·좌표계 오류 |
| `4` | 수치·기하 계산 오류 |
| `5` | 출력 디렉터리 또는 결과 저장 오류 |

`check` 통과는 인터페이스를 올바르게 구현했다는 뜻이다. `run` Exit code `0`은 해당 시나리오에서 알고리즘 결과가 검증 기준까지 통과했다는 뜻이다. 두 개념을 구분해야 한다.

## 12. 납품 체크리스트

- [ ] 제공받은 `config.yaml`과 `target.stl`을 변경하지 않았다.
- [ ] 세 파일을 정확한 파일명으로 하나의 작업 디렉터리에 저장했다.
- [ ] 세 로봇 모두 `0.0` 초에서 시작한다.
- [ ] 모든 waypoint가 TCP World 좌표와 mm 단위를 사용한다.
- [ ] 모든 시간이 초 단위이고 로봇별로 엄격하게 증가한다.
- [ ] mode를 현재 행에서 다음 행까지의 구간 의미로 기록했다.
- [ ] `W` 구간에서 TCP가 이동하지 않는다.
- [ ] `D` 구간이 유효한 layer Z에서 수평으로 이동한다.
- [ ] 곡선 경로를 필요한 정밀도의 직선 선분으로 분할했다.
- [ ] travel, deposition, wait 시간을 timestamp에 모두 반영했다.
- [ ] 각 로봇이 안전한 주차 위치의 `W` 행으로 종료한다.
- [ ] `waam-validator check` Exit code가 `0`이다.
- [ ] `waam-validator run --json`의 결과와 Exit code를 저장했다.

## 13. 요약 요구문

> 각 알고리즘은 세 로봇의 최종 작업 계획을 동일한 World 좌표계의 시간 지정 TCP 선분 집합으로 변환하고, 모든 travel·deposition·wait·parking을 `T`, `D`, `W` 구간으로 표현하는 WAAM Validator Exporter를 제공해야 한다.

참고 파일:

- [`examples/sample_job/config.yaml`](../examples/sample_job/config.yaml)
- [`examples/sample_job/trajectory.csv`](../examples/sample_job/trajectory.csv)
- [루트 README](../README.md)
