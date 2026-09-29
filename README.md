# Three-Robot RL Environment — Version 0.1.1

로봇 3대의 이동·적층 행동을 강화학습(RL) 모델이 선택하고, 환경이 시간 진행,
충돌 검사, 궤적 유효성 검사와 목표 형상 평가를 수행하는 프로젝트입니다.
모델은 작업 완료 시간을 줄이면서 충돌을 피하고 목표 형상을 제작하도록 학습합니다.

이 문서는 특정 학습 알고리즘에 종속되지 않는 **RL 모델과 환경의 인터페이스**를
설명합니다. 아래 의사코드는 처리 흐름을 나타내며 그대로 실행하는 Python 코드는
아닙니다. 현재 학습 구현이 모든 RL 알고리즘을 자동 지원한다는 의미는 아닙니다.

## 패치 노트

버전은 기능 개발 단계에 따라 구분합니다. 현재 프로젝트 버전은 **0.1.1**이며,
실제 작업 폴더 이름은 `Project_version_0.0.2`를 유지하고 있습니다.

| 버전 | 구분 | 주요 범위 |
| --- | --- | --- |
| 0.0.1 | 원본 | 기존 프로젝트와 validator 검증 기능 |
| 0.0.2 | 환경 구성 | `models` 폴더 추가 전의 메모리 기반 검사와 RL 환경 |
| 0.1.1 | 현재 | RL 모델 학습, 검증 리포트, TensorBoard 통합 |

### 0.1.1 — RL 모델 학습과 모니터링

- `models` 폴더와 모델·환경·학습 설정을 관리하는 `config.py` 추가.
- 모델 이름, 환경, 설정을 전달받는 `learn.py`와 모델 저장·재로딩 흐름 추가.
- PyTorch 설치, CPU 연산, CUDA 사용 가능 여부와 실제 GPU 연산을 확인하는
  `check_torch_cuda.py` 추가.
- 학습 중 에피소드별 `PASS/FAIL`, 궤적·형상 검사 결과, 충돌 발생 step 수,
  makespan, 누적 보상을 출력하는 리포트 추가.
- TensorBoard에 에피소드 결과, 검증 통과율, 보상과 학습 loss를 기록하는 기능 추가.
- 실제 모델 업데이트, 저장·재로딩, 검증 리포트와 TensorBoard 이벤트를 확인하는
  통합 테스트 추가. 환경 테스트를 포함한 총 17개 테스트 통과.
- RL 환경·학습·최종 궤적 생성 흐름의 의사코드와 실행 설명 문서 추가.

현재 학습 CLI는 모델을 저장합니다. 학습 후 별도 에피소드를 실행하여 최종 궤적을
반환하는 흐름은 의사코드로 설명되어 있으며, CLI에 자동 연결된 기능은 아닙니다.

### 0.0.2 — 모델 추가 전의 RL 환경

- validator의 검증 엔진을 `environment`에 복사하여 재사용.
- CSV 궤적 입력 대신 dictionary 또는 pandas DataFrame을 받는 `env.py` 추가.
- 충돌·형상·궤적 검사를 `check_collision()`, `check_shape()`,
  `check_validation()`으로 분리하고 각각 실패 0 / 통과 1을 반환하도록 구성.
- 로봇 3대의 관측 `(3, 5)`와 행동 `(3, 4)`를 제공하는 Gymnasium 래퍼 추가.
- T/D/W/F 모드, 세 로봇 모두 F일 때 종료, 검사·출력 시 F를 W로 변환하는 규칙 추가.
- 단계별 makespan·충돌 패널티와 마지막 단계의 궤적·형상 검증 보상 구성.
- 궤적을 메모리에서 누적하고 `get_trajectory()`로 반환하도록 구성.

이 버전의 범위는 환경과 검사 기능까지이며, `models` 폴더를 통한 학습 기능은
0.1.1에서 추가되었습니다.

### 0.0.1 — 원본 프로젝트

- 기존 validator를 사용한 로봇 궤적·충돌·형상 검증 기능을 기준으로 시작.
- YAML 설정, CSV 궤적, STL 목표 형상을 입력으로 사용하는 파일 기반 검증 흐름 제공.

## 폴더 구조

```text
Project_version_0.0.2/
├── README.md
├── validator/                     # 원본 검증 코드
├── environment/
│   ├── env.py                     # dict/DataFrame 입력 → 독립적인 0/1 검사
│   ├── gym_wrapper.py             # RL 환경: reset, step, get_trajectory
│   ├── gym_wrapper.md             # 환경 인터페이스 상세 설명
│   ├── test_gym_wrapper.py        # 환경 동작 테스트
│   ├── src/waam_validator/        # validator에서 복사한 검증 엔진
│   ├── config.yaml               # 공통 설정 템플릿
│   └── examples/sample_job/
│       ├── config.yaml           # 기본 학습 환경에서 사용하는 물리·검증 설정
│       └── target.stl            # 목표 형상
└── models/
    ├── config.py                  # 모델·환경·보상·학습 설정
    ├── learn.py                   # 모델 생성, 학습 및 저장
    ├── reporting.py               # 에피소드 검증 리포트와 TensorBoard 지표
    ├── check_torch_cuda.py        # PyTorch 설치 및 CPU/GPU 연산 확인
    ├── test_learning.py           # 실제 학습 연결·저장·재로딩 테스트
    └── checkpoints/               # 실행 시 생성되는 학습 모델
```

`environment/src/waam_validator`는 원본 검증 엔진의 복사본입니다.
`environment/env.py`가 이 복사본의 검사 함수를 호출하므로 원본 `validator`를
수정해도 환경에 자동 반영되지는 않습니다.

## 전체 흐름

```text
환경 설정(config.yaml) + 목표 형상(target.stl)
                     ↓
                 RL Environment
                     ↓ observation
                  RL Model
                     ↓ action
             로봇 상태·시간·궤적 갱신
                     ↓
       충돌 검사 + 보상 + 다음 observation
                     ↓
          종료 시 궤적 유효성·형상 검사
                     ↓
         최종 궤적(dictionary) + 평가 결과
```

궤적 입력·검사·보상 계산은 메모리에서 처리합니다. 이 경로에서는 CSV/JSON을
읽거나 생성하지 않습니다. 환경 초기화에는 YAML 설정과 STL 목표 형상이 필요합니다.
학습 모델을 저장하는 기능은 궤적 출력과 별개입니다.

## 관측과 행동

관측은 `float32`, 크기 `(3, 5)`이며 행 순서는 Robot 1, Robot 2, Robot 3입니다.

```text
observation = [
    [now_s, robot1_x, robot1_y, robot1_z, robot1_mode],
    [now_s, robot2_x, robot2_y, robot2_z, robot2_mode],
    [now_s, robot3_x, robot3_y, robot3_z, robot3_mode]
]
```

시간은 초, 좌표는 mm입니다. 관측에는 누적 적층 형상이나 전체 궤적이 포함되지
않으므로, 이 관측만 사용하는 모델에는 과거 작업 정보가 제한적으로 주어집니다.

| 모드 | 관측 코드 | 의미 |
| --- | --- | --- |
| T | 0 | 이동 |
| D | 1 | 적층 |
| W | 2 | 대기 |
| F | 3 | 해당 로봇 작업 종료 |

행동은 `float32`, 크기 `(3, 4)`이며 모든 값의 범위는 `[-1, 1]`입니다.

```text
action = [
    [normalized_x1, normalized_y1, normalized_z1, mode_value1],
    [normalized_x2, normalized_y2, normalized_z2, mode_value2],
    [normalized_x3, normalized_y3, normalized_z3, mode_value3]
]
```

XYZ는 환경의 좌표 범위에 따라 **절대 목표 좌표**로 변환됩니다.
변위가 아닙니다. 모드 값은 다음 구간으로 해석합니다.

| 행동의 모드 값 | 모드 |
| --- | --- |
| `[-1, -0.5)` | T |
| `[-0.5, 0)` | D |
| `[0, 0.5)` | W |
| `[0.5, 1]` | F |

실제 좌표와 모드 이름을 알고 있다면 `action_from_targets(xyz, modes)`로
환경 입력 행동을 만들 수 있습니다. W/F에서는 목표 좌표를 무시하고 현재 위치를
유지합니다. F를 선택한 로봇은 에피소드가 끝날 때까지 다시 움직이지 않으며,
다른 로봇의 충돌 검사에는 계속 포함됩니다.

## 시간과 궤적 갱신

세 로봇은 한 step을 동시에 시작합니다. T/D의 소요 시간은 이동 거리와 해당
모드의 설정 속도로 계산합니다. 가장 늦게 끝나는 로봇에 맞춰 step이 끝나며,
먼저 도착한 로봇의 나머지 시간은 대기 궤적으로 기록합니다.

```text
FUNCTION ADVANCE(action):
    targets, requested_modes ← DECODE(action)

    FOR EACH robot:
        mode ← F IF robot is already finished ELSE requested_modes[robot]

        IF mode is W or F:
            end_position ← current_position
            duration ← wait_time_s
        ELSE:
            end_position ← targets[robot]
            speed ← deposition_speed IF mode is D ELSE travel_speed
            duration ← distance(current_position, end_position) / speed
            IF distance is zero:
                duration ← wait_time_s

    elapsed ← MAX(wait_time_s, all robot durations)

    FOR EACH robot:
        APPEND movement or waiting interval to trajectory
        IF robot arrives before the common step end:
            APPEND waiting interval until the common step end
        UPDATE position and mode
        UPDATE now_s to the common step end

    RETURN this step's trajectory window
```

## 독립 검사 함수

검사 입력은 열 이름을 키로 하는 dictionary 또는 pandas DataFrame입니다.
필요한 열은 다음과 같습니다.

```text
robot_id, time_s, x_mm, y_mm, z_mm, mode
```

세 로봇 각각 최소 2개 행이 필요하며, 각 로봇의 첫 시간은 0입니다.
행은 `robot_id`, `time_s` 순으로 정렬되어야 합니다. 검사 입력 모드는 T/D/W이며,
환경은 내부 F를 W로 변환해 전달합니다. 입력 오류나 검사 실패는 0으로 반환합니다.

| 함수 | 재사용하는 검증 기능 | 반환값 |
| --- | --- | --- |
| `check_collision(data)` | 활성화된 로봇 암/TCP 충돌 검사 | 충돌 없음 1, 실패 0 |
| `check_shape(data)` | 적층 형상 생성, 목표 단면 비교, 형상 기준 평가 | 통과 1, 실패 0 |
| `check_validation(data)` | 시간·모드·대기·속도·도달 범위·적층 규칙 검사 | 통과 1, 실패 0 |

`check_validation()`은 전체 평가를 합친 함수가 아닙니다. 충돌과 형상 검사는
각각 별도입니다. 속도 초과의 실패 처리 등은 YAML 설정에 따릅니다.

## 보상과 종료 조건

단계별 보상은 makespan 증가량과 현재 step에서 발생한 충돌로 계산합니다.
이전 step의 충돌을 다음 step에서 다시 벌점으로 계산하지 않습니다.

```text
step_reward = -makespan_weight × elapsed_seconds
              -collision_penalty × (1 - collision_pass)
```

세 로봇 모두 F이면 `terminated = True`입니다. 모두 W인 상태는 종료가 아닙니다.
모두 F가 되기 전에 최대 step 수에 도달하면 `truncated = True`입니다.

최종 검사는 terminated 또는 truncated가 된 마지막 step에서만 실행합니다.

```text
FUNCTION STEP(action):
    window ← ADVANCE(action)
    step_count ← step_count + 1
    collision_pass ← CHECK_COLLISION(window with relative time starting at 0)
    reward ← -makespan_weight × elapsed_seconds
              -collision_penalty × (1 - collision_pass)

    terminated ← ALL robot modes are F
    truncated ← step_count >= max_steps AND NOT terminated
    validation_pass, shape_pass, success ← UNDEFINED

    IF terminated OR truncated:
        trajectory ← GET_TRAJECTORY()        # F → W
        validation_pass ← CHECK_VALIDATION(trajectory)
        shape_pass ← CHECK_SHAPE(trajectory)
        success ← terminated AND validation_pass == 1 AND shape_pass == 1
        reward ← reward + (terminal_reward IF success ELSE -terminal_penalty)

    RETURN observation, reward, terminated, truncated, info
```

시간 제한 종료는 성공 보상을 받지 않습니다. 현재 구현에서 충돌은 단계별
패널티이고, 최종 `success` 조건에 직접 포함되지는 않습니다. 따라서 최종 성공
플래그만으로 전체 궤적이 충돌 없이 완료되었다고 판단할 수는 없습니다.

## RL 모델 학습 의사코드

```text
config ← LOAD_MODEL_AND_ENVIRONMENT_CONFIG()
env ← CREATE_ENVIRONMENT(config.environment)
model ← CREATE_RL_MODEL(config.model, env.observation_space, env.action_space)
observation, info ← env.RESET(seed=config.seed)

WHILE training budget remains:
    action ← model.SELECT_ACTION(observation, exploration=True)
    next_observation, reward, terminated, truncated, info ← env.STEP(action)

    model.RECORD_TRANSITION(
        observation, action, reward, next_observation, terminated, truncated
    )
    IF the selected learning method is ready to update:
        model.UPDATE_PARAMETERS()

    IF terminated OR truncated:
        # reset 또는 자동 reset 전에 필요한 최종 궤적을 확보한다.
        episode_trajectory ← env.GET_TRAJECTORY()
        observation, info ← env.RESET()
    ELSE:
        observation ← next_observation

SAVE_MODEL(model)
CLOSE_TRAINING_LOGGER()
env.CLOSE()
```

학습 방법에 따라 경험 수집과 업데이트 방식이 달라집니다. `terminated`와
`truncated`는 학습 시 별도로 전달해야 합니다. 실제 학습 라이브러리는 내부에서
이 루프와 에피소드 초기화를 관리할 수 있습니다.

## 학습 모델로 최종 궤적 생성하기

현재 `models/learn.py`의 CLI는 학습 후 모델을 저장합니다. 학습 완료 뒤 별도
평가 에피소드를 실행해 최종 궤적을 반환하는 기능은 아직 CLI에 연결되어 있지
않습니다. 다음은 이를 구성할 때 사용하는 추론 흐름입니다.

```text
FUNCTION GENERATE_TRAJECTORY(trained_model, environment_config):
    env ← CREATE_ENVIRONMENT(environment_config)
    TRY:
        observation, info ← env.RESET()

        LOOP:
            action ← trained_model.SELECT_ACTION(observation, exploration=False)
            observation, reward, terminated, truncated, info ← env.STEP(action)
            IF terminated OR truncated:
                BREAK

        trajectory ← env.GET_TRAJECTORY()    # reset 전에 가져온다. F는 W로 변환된다.
        full_collision_pass ← CHECK_COLLISION(trajectory, same job configuration)
        RETURN trajectory, info, full_collision_pass
    FINALLY:
        env.CLOSE()
```

`get_trajectory()`는 누적 궤적을 dictionary로 반환하며 파일을 만들지 않습니다.
반환한 궤적은 반드시 성공한 궤적이라는 뜻은 아닙니다. 최종 `info`의 검사 결과와
필요한 경우 전체 궤적의 충돌 결과를 함께 확인하세요.

## 설정 파일 구분

| 파일 | 역할 |
| --- | --- |
| `environment/examples/sample_job/config.yaml` | 기본 로봇 위치, 속도, 작업 영역, 충돌·형상 기준 |
| `environment/examples/sample_job/target.stl` | 목표 형상 |
| `models/config.py` | 모델 설정, 학습률, 학습 횟수, 환경 경로, 보상 가중치, CPU/GPU 장치 |

환경은 `job_dir/config.yaml`과 `job_dir/target.stl`을 읽습니다.
다른 작업을 사용하려면 모델 설정의 `job_dir` 또는 CLI의 `--job-dir`을 변경합니다.
`environment/config.yaml`은 기본 학습 작업의 YAML과 다른 파일입니다.

## 동작 확인

학습 리포트는 에피소드 종료마다 `PASS/FAIL`, 궤적·형상 검사 결과, 충돌 발생
step 수, makespan과 누적 보상을 표시합니다. PASS 기준은 위에 설명한 환경의
최종 성공 조건이며, 충돌은 별도 항목입니다. 원본 validator의 전체 PASS 판정과
같은 의미는 아닙니다. 진행 중인 에피소드는 통과율 분모에 포함하지 않습니다.

TensorBoard 이벤트는 기본적으로 `models/tensorboard/` 아래 실행별 폴더에
기록합니다. 먼저 학습 환경에 추가 패키지를 설치하세요.

```bat
python -m pip install tensorboard
```

학습 중 별도 프롬프트에서 같은 Python 환경과 프로젝트 루트를 사용하여 실행합니다.

```bat
python -m tensorboard.main --logdir models/tensorboard --port 6006
```

브라우저의 `http://localhost:6006`에서 보상, loss, makespan, 검증 통과율을
확인할 수 있습니다. Text의 `episode/validation_result`에는 각 에피소드의
PASS/FAIL이 기록됩니다. CSV/JSON 리포트는 생성하지 않습니다.
`--no-tensorboard` 또는 `models/config.py`의 `tensorboard_log=None`으로
이벤트 기록을 끌 수 있습니다. `--no-save`는 모델 저장만 끕니다.

필요한 패키지가 설치된 Python 환경에서 프로젝트 루트를 작업 폴더로 사용합니다.

```bat
python models/check_torch_cuda.py
python -B -m unittest environment.test_gym_wrapper models.test_learning -v
python -m models.learn --smoke-test
```

GPU 실제 연산을 필수로 확인하려면 다음 명령을 사용합니다.

```bat
python models/check_torch_cuda.py --require-cuda
```

짧은 학습 테스트는 환경 연결, 모델 업데이트, 저장·재로딩을 확인합니다.
목표 형상 제작 성공률이나 학습 수렴은 별도의 충분한 학습과 평가로 확인해야 합니다.
