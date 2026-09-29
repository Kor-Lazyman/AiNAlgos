# Python API

패키지는 CLI와 같은 계산 모듈을 Python 코드에서 사용할 수 있도록 주요 함수를
`waam_validator` 최상위 namespace에 노출합니다.

## 전체 Validation 실행

```python
from pathlib import Path

from waam_validator import ValidationProgress, run_validation


def show_progress(event: ValidationProgress) -> None:
    print(f"{event.stage}: {event.overall_progress:.1%} ({event.message})")


result = run_validation(
    Path(r"C:\data\my_job"),
    progress_callback=show_progress,
)

print(result.status)
print(result.output_dir)
print(result.failure_reasons)
```

Signature:

```python
run_validation(
    input_dir: Path,
    output_dir: Path | None = None,
    *,
    progress_callback: Callable[[ValidationProgress], None] | None = None,
) -> ValidationResult
```

이 함수는 계산뿐 아니라 설정된 산출물을 실제 output 폴더에 기록합니다. 정상
FAIL은 예외를 발생시키지 않고 `ValidationResult(status="FAIL")`을 반환합니다.

## 진행 event

`ValidationProgress`는 immutable `slots=True` dataclass입니다.

| 필드 | 의미 |
| --- | --- |
| `stage` | `loading_inputs`, `collision`, `deposition`, `target_slicing`, `shape_metrics`, `results`, `completed` |
| `message` | 현재 작업의 사용자용 설명 |
| `stage_progress` | 현재 단계의 0..1 진행률 |
| `overall_progress` | 전체 pipeline의 0..1 진행률 |
| `completed_units` | 처리한 simulation second, interval 또는 layer 수 |
| `total_units` | 해당 단계의 전체 단위 수 |
| `unit` | `simulation_s`, `intervals`, `layers` 등 |

Callback은 계산 thread/process에서 동기적으로 호출되므로 오래 걸리는 작업을 넣지
마십시오. 필요한 상태만 queue 또는 작은 파일로 전달하는 방식이 적합합니다. Callback
자체에서 예외가 발생하면 Validator는 첫 예외를 `run.log`에 기록한 뒤 해당 callback만
비활성화하고 Validation 계산과 결과 기록은 계속합니다.

## 단계별 API

```python
from pathlib import Path

from waam_validator import (
    build_deposited_layers,
    compute_reach_metrics,
    compute_schedule_metrics,
    iter_simulation_samples,
    load_config,
    load_trajectory_csv,
    run_collision_simulation,
    validate_trajectory_set,
)

job = Path(r"C:\data\my_job")
config = load_config(job / "config.yaml")
trajectories = load_trajectory_csv(job / "trajectory.csv", config)
messages = validate_trajectory_set(trajectories, config)

schedule = compute_schedule_metrics(trajectories)
reach = compute_reach_metrics(trajectories, config)
events = run_collision_simulation(trajectories, config)
deposited_layers = build_deposited_layers(trajectories, config)
```

`validate_trajectory_set()`은 warning과 실행 가능한 process violation을
`ValidationMessages`로 반환합니다. Deposition layer/workspace처럼 계속 계산할 수 없는 문제는
`InputValidationError`를 발생시킵니다. 단계별 API를 직접 조합할 때는 반환 메시지를
무시하지 말아야 합니다.

## 공개 함수 목록

| 함수 | 입력 | 반환·역할 |
| --- | --- | --- |
| `load_config` | Config `Path` | immutable Pydantic `Config` |
| `load_trajectory_csv` | CSV `Path`, `Config` | compact NumPy 배열의 `TrajectorySet` |
| `validate_trajectory_set` | trajectory, config | `ValidationMessages` 또는 치명 입력 예외 |
| `interpolate_robot_state` | `RobotTrajectory`, time | 보간된 float32 XYZ와 left-row mode |
| `iter_simulation_samples` | trajectory set, config | adaptive `SimulationSample` iterator |
| `compute_schedule_metrics` | trajectory set | `ScheduleMetrics` |
| `compute_reach_metrics` | trajectory set, config | `ReachMetrics` |
| `run_collision_simulation` | trajectory set, config | 병합된 `CollisionEvent` list |
| `build_deposited_layers` | trajectory set, config | layer index → Shapely geometry |
| `slice_target_layers` | Trimesh, layer indices, config | layer index → Target geometry |
| `compute_shape_metrics` | deposited/target mapping, config | `ShapeMetrics`, `LayerMetrics` list |
| `run_validation` | 입력·출력 경로와 progress callback | 전체 `ValidationResult`와 핵심 결과 파일 |

`build_deposited_layers`, `slice_target_layers`, `compute_shape_metrics`,
`run_collision_simulation`은 선택적인 단계 진행 callback도 받습니다. 이 callback의
형태는 `(fraction, completed, total)`입니다.

`compute_reach_metrics()`는 Base와 원본 TCP 절점 사이의 XY 거리만 계산하며 Z는
무시합니다. `RobotReachMetrics`는 `xy_reach_radius_mm`,
`maximum_xy_distance_mm`, `minimum_xy_margin_mm`, `xy_utilization_ratio`,
`xy_violation_point_count`, `first_xy_violation_s`, `last_xy_violation_s`를 제공합니다.

충돌 결과의 Arm event 유형은 `ARM_ENVELOPE`입니다. 전체 결과의
`CollisionSimulationResult`는 event 외에도 최소 Arm safety margin, 그때의 중심선
거리·요구 거리·pair·시각·closest points·세 TCP XY 위치와 최소 TCP 거리를 보존합니다.
낮은 수준의 `check_arm_envelope_xy()`와 batch 함수는 Base–TCP 유한 선분, 각 Robot의
Capsule 반경, 공통 안전거리와 접촉 정책을 받아 같은 판정 수식을 사용합니다.

## Runtime 데이터 타입

Trajectory는 대형 CSV의 메모리 사용량을 줄이기 위해 다음 dtype을 사용합니다.

| 배열 | dtype |
| --- | --- |
| `RobotTrajectory.time_s` | NumPy `float64` |
| `RobotTrajectory.xyz_mm` | NumPy `float32` |
| `RobotTrajectory.mode` | NumPy `uint8` (`T=0`, `D=1`, `W=2`) |

주요 결과 객체는 typed `slots=True` dataclass입니다. `ValidationResult`에는 schedule,
reach, collision, shape, layer metrics, warning/violation과 Failure Reasons가 포함됩니다.
`summary_dict()`는 `summary.json`과 같은 직렬화 구조를 반환합니다.

Validation 당시 Config는 `validation_inputs.json`에 입력 파일 SHA-256 지문과 함께
snapshot으로 기록됩니다. UI는 이후 원본 `config.yaml`이 바뀌더라도 완료된 결과의
임계값과 충돌 장면을 이 snapshot 기준으로 표시합니다.

`run_validation()`은 정적 PNG, `deposited.stl`, `replay.html`을 만들지 않습니다.
추가 산출물은 UI worker의 입력 지문 확인과 atomic rename 절차를 통해 생성됩니다.

## 예외와 종료 코드 대응

Python API는 `WaamValidatorError` 계열 예외를 사용합니다.

```python
from waam_validator.errors import WaamValidatorError

try:
    result = run_validation(job)
except WaamValidatorError as exc:
    print(exc.code, exc.message, exc.exit_code, exc.output_dir)
```

| 예외 | `exit_code` | 범주 |
| --- | --- | --- |
| `InputValidationError` | 2 | 입력 파일·Config/CSV 구조·trajectory 문제 |
| `TargetValidationError` | 3 | Target mesh 문제 |
| `ComputationError` | 4 | 수치·기하 계산 문제 |
| `OutputWriteError` | 5 | output 경로·파일 쓰기 문제 |

`exc.output_dir`에는 생성된 run 폴더가 연결될 수 있으며, 그 안에 `error.json`과
`run.log`가 남을 수 있습니다.

## 버전 확인

```python
import waam_validator

print(waam_validator.__version__)
```

애플리케이션 버전은 `waam_validator._version` 한 곳에서 관리되고 빌드 metadata와
`waam_validator.__version__`이 같은 값을 사용합니다. Config에는 별도 버전 필드가
없습니다. 공개 API나 동작에 호환성이 깨지는 변경을 할 때는 애플리케이션 버전과
문서를 함께 갱신하십시오.

[루트 README로 돌아가기](../README.md)
