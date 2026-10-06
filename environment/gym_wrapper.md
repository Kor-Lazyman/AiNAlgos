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

**중간 보상은 0이며, 종료 시 한 번만 지급합니다. 상위 조건 실패 시 하위 보상을 차단합니다.**
검사 결과와 실제 지급되는 점수는 구분합니다. 모든 검사 결과와 원래 coverage %는
리포트에 남기지만 실패한 에피소드에는 양의 형상·완료 보상을 주지 않습니다.

| 종료 조건 | 형상 보상 | 충돌 항목 | makespan 항목 | 완료/실패 항목 |
| --- | --- | --- | --- | --- |
| 미완료·시간 제한 또는 궤적/형상 검사 실패 | 0 | 0 | 0 | `-P` |
| 위 조건 통과 후 에피소드 중 충돌 있음 | 0 | `-collision_penalty` | 0 | 0 |
| 모두 통과 | `shape_weight × floor(coverage %)` | 0 | 정규화된 시간 패널티 | `+terminal_reward` |

형상 실패에는 coverage가 100%로 계산되어도 부분 점수를 주지 않습니다.
형상·궤적이 통과하더라도 이전 step에서 충돌한 적이 있으면 충돌 패널티만 줍니다.
실패한 경로가 빠르거나 coverage가 높아도 실패 점수를 줄일 수 없습니다.

성공 플래그와 리포트의 PASS는 **세 로봇 모두 F + 궤적 검사 통과 + 형상 검사 통과
+ 에피소드 전체 충돌 검사 통과**를 모두 요구합니다. 충돌이 있으면 FAIL입니다.
모두 통과한 경로끼리는 형상 완성도(1%p 단위)가 우선하고, 같은 형상 점수에서는
makespan이 짧을수록 유리합니다.

```text
B = 100 × shape_weight + collision_penalty + makespan_weight + terminal_reward
P = max(configured terminal_penalty, 10 × (B + 1))

if not all_finished or not trajectory_pass or not shape_pass:
    score = -P
elif any_episode_collision:
    score = -collision_penalty
else:
    score = shape_weight × floor(shape_percentage) + terminal_reward
            - makespan_weight × makespan / (makespan + makespan_reference_s)

reward = 0                              # 중간 step
reward = score / gamma^(N - 1)           # 마지막 step N에서 한 번
```

기본값은 형상 가중치 2, 충돌 패널티 1, makespan 가중치 0.1, 기준 시간 100초,
완료 보너스 10, `gamma=0.9999`입니다. 기본 실패 패널티 `P=2121`입니다.
실패에는 음수 패널티만 지급하며, 하위 점수를 합산하지 않습니다.
설정 제약 `shape_weight > collision_penalty + makespan_weight`와
`collision_penalty > makespan_weight >= 0`은 유지합니다.

형상 평가와 궤적 검사는 종료 시 각각 한 번 호출합니다. 충돌 검사는 단계별로
계속 수행해 누적합니다. 검사 자체를 생략하는 것이 아니라 **보상 계산을 차단**합니다.
`shape_percentage`와 `shape_score_percentage`는 실패해도 진단용으로 남습니다.

종료 보상은 할인 보정되어 에피소드 시작에서의 할인 Return이 `terminal_score`와
같습니다. 실패를 늦춰 음수 패널티를 줄일 수 없습니다. 길이가 다른 에피소드는
`terminal_score`로 비교하세요. 환경과 모델은 같은 gamma를 사용해야 합니다.
시간 제한은 환경에서 `truncated=True`이며, 학습 래퍼는 추가 가치 추정을 막기 위해
terminal로 전달합니다. 리포트에서는 TIME_LIMIT로 표시합니다.

`info`와 TensorBoard의 `reward_shape`, `reward_collision`, `reward_makespan`,
`reward_terminal`에는 차단된 항목의 0과 실제 지급된 보정 후 값이 기록됩니다.
`collision_pass`는 현재 step, `episode_collision_pass`는 reset 이후 전체 결과입니다.
`terminal_penalty`와 `return_bound`는 할인 보정 전 점수 단위입니다.
CSV/JSON 파일은 생성하지 않습니다.

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
    from models.config import CONFIG
    from models.learn import build_model
    model = build_model("ppo", env, CONFIG)
    model.learn(total_timesteps=100_000)
finally:
    env.close()
```

SB3의 기본 MLP는 `(3, 5)` 관측을 펼쳐 사용합니다. 위치·시간 관측은 실제 단위이므로
학습 시 필요에 따라 관측 정규화를 추가할 수 있습니다. 요청한 15개 상태에는 적층
이력이나 목표 형상이 포함되지 않으므로 부분 관측 환경이며, 학습 성능은 별도로
확인해야 합니다. 연속 행동을 구간으로 나누는 모드 선택 역시 이 환경의 설계 선택입니다.

## 테스트

`test_gym_wrapper.py`는 Gymnasium 규약, 상태/행동 변환, F 유지, 로봇 간 대기 시간,
보상 분리, 마지막 단계 검사, 실제 충돌 및 형상 계산을 검사합니다. DataFrame 호환
테스트에는 pandas가 필요합니다. 프로젝트 0.0.2 루트에서 실행합니다.

```powershell
python -B -m unittest environment.test_gym_wrapper -v
```

참고: [SB3 사용자 정의 환경](https://stable-baselines3.readthedocs.io/en/master/guide/custom_env.html),
[Gymnasium Env API](https://gymnasium.farama.org/api/env/).
