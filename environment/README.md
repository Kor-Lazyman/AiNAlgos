# 3대 로봇 Gymnasium 환경

`gym_wrapper.py`의 `WaamGymEnv`를 SB3 PPO에서 사용할 수 있습니다.
기존 `env.py`의 검사 함수들을 호출하며 실행 중 CSV·JSON·보고서를 생성하지 않습니다.
`step()`의 `info`는 Gymnasium API가 요구하는 메모리상의 딕셔너리입니다.

## 관측과 행동

관측은 `float32`, 크기 `(3, 5)`입니다. 행 순서는 Robot 1, 2, 3입니다.

```text
[[현재 시간(s), x(mm), y(mm), z(mm), mode],
 [현재 시간(s), x(mm), y(mm), z(mm), mode],
 [현재 시간(s), x(mm), y(mm), z(mm), mode]]
```

모드 코드는 `T=0`, `D=1`, `W=2`, `F=3`입니다. 관측의 모드는 직전 행동에서 선택한
모드이며, `F`는 유지됩니다. 세 로봇의 시간은 동기화된 현재 시각입니다.

행동은 `(3, 4)` 크기의 `[-1, 1]` 연속값입니다. 첫 세 값은 **절대 목표 XYZ 좌표**로
변환하고, 네 번째 값은 다음 구간으로 모드를 선택합니다.

| 행동의 네 번째 값 | 모드 |
| --- | --- |
| `[-1, -0.5)` | T: 이동 |
| `[-0.5, 0)` | D: 적층 이동 |
| `[0, 0.5)` | W: 대기 |
| `[0.5, 1]` | F: 완료 |

XYZ의 기본 범위는 로봇 초기 위치, 작업 영역, STL 경계를 포함합니다.
`xyz_bounds=(최소_XYZ, 최대_XYZ)`로 직접 지정할 수 있습니다. 실제 좌표와 모드로
행동을 만들려면 `action_from_targets()`를 사용합니다. W/F는 XYZ를 무시하고 현재
위치를 유지합니다. F가 된 로봇에 이후 T/D 행동을 주어도 다시 움직이지 않습니다.

```python
from environment.gym_wrapper import WaamGymEnv

env = WaamGymEnv()
observation, info = env.reset(seed=42)
action = env.action_from_targets(observation[:, 1:4], ["W", "W", "F"])
observation, reward, terminated, truncated, info = env.step(action)
trajectory = env.get_trajectory()  # 열별 리스트 딕셔너리. F는 W로 변환됨.
env.close()
```

## 시간과 종료

세 로봇은 각 단계에서 동시에 행동을 시작합니다. T/D의 소요 시간은 이동 거리와
config.yaml의 해당 속도로 결정합니다. 먼저 도착한 로봇은 가장 늦은 로봇까지
기다립니다. W/F만 있는 단계도 `wait_time_s`(기본 0.1초)만큼 시간이 흐릅니다.
종료한 로봇도 그 위치에 계속 존재하므로 다른 로봇과의 충돌 검사에 포함됩니다.

세 로봇이 모두 F이면 `terminated=True`입니다. 아직 미완료인데 `max_steps`에
도달하면 `truncated=True`이며 성공 보상을 주지 않습니다. 종료 후에는 다시
`reset()`해야 합니다. 단순히 세 로봇 모두 W인 상태는 종료가 아닙니다.

검증기에는 각 구간의 시작 행에 T/D/W를 기록합니다. 내부 F는 입력 딕셔너리로
변환할 때만 W로 바뀝니다. 진행 중인 경로는 메모리에 누적되며 파일로 저장하지 않습니다.
XYZ를 임의로 보정하거나 D를 T로 바꾸지 않습니다. D의 높이·작업 영역·이동 조건을
위반한 경로는 마지막 검사에서 실패합니다.

## 보상

```text
매 단계 = -makespan_weight × 이번 단계 소요 시간
          -collision_penalty × 이번 단계 충돌 여부

마지막 단계에만 추가:
  세 로봇 모두 F이고 check_validation=1 및 check_shape=1: +terminal_reward
  그 외: -terminal_penalty
```

기본값은 `makespan_weight=0.01`, `collision_penalty=1`,
`terminal_reward=10`, `terminal_penalty=10`입니다. 시간 보상은 누적 makespan을 매번
중복 차감하지 않고 증가량만 차감합니다. 충돌 검사는 이번 단계의 이동·대기 구간만
검사하여 과거 충돌을 반복 차감하지 않습니다. 두 마지막 검사는 자연 종료 또는
단계 제한에 의한 종료 시 각각 한 번만 호출합니다.

최종 검증 보상은 궤적 규칙과 목표 형상으로 결정하며, 충돌은 별도의 단계별 보상입니다.
`info`에는 makespan, 완료 상태, 검사 결과, 보상 항별 값이 들어 있습니다.

## SB3 PPO 연결

검증기의 기존 의존성과 `gymnasium`, `stable-baselines3`가 필요합니다.
프로젝트 0.0.2 루트에서 실행합니다.

```python
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from environment.gym_wrapper import WaamGymEnv

env = WaamGymEnv(max_steps=256)
try:
    check_env(env, warn=True)
    model = PPO("MlpPolicy", env, verbose=1)
    model.learn(total_timesteps=100_000)
finally:
    env.close()
```

SB3의 기본 MLP는 `(3, 5)` 관측을 펼쳐 사용합니다. 위치·시간 관측은 실제 단위이므로
학습 시 필요에 따라 관측 정규화를 추가할 수 있습니다. 요청한 15개 상태에는 적층
이력이나 목표 형상이 포함되지 않으므로 부분 관측 환경이며, 학습 성능은 별도로
확인해야 합니다. 연속 행동을 구간으로 나누는 모드 선택 역시 이 환경의 설계 선택입니다.

참고: [SB3 사용자 정의 환경](https://stable-baselines3.readthedocs.io/en/master/guide/custom_env.html),
[Gymnasium Env API](https://gymnasium.farama.org/api/env/).
