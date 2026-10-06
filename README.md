# Three-Robot PPO — 1.0.0

STL 목표 형상에 맞는 로봇 3대의 적층 궤적을 PPO로 계획하고, 독립 검증기로
형상·궤적·충돌을 검사하는 프로젝트입니다. 현재 대상은 `sphere_r-24mm.STL`입니다.
검증 통과를 우선하며 **makespan 보상 가중치는 0**입니다.

프로젝트 버전의 단일 원본은 `VERSION`입니다. 작업 폴더 이름은 기존
`Project_version_0.1.2`를 유지합니다. 내부 WAAM Validator의 자체 버전 1.0.1과
프로젝트 버전 1.0.0은 별도로 관리합니다.

## 1.0.0 변경 사항

- 현재 구현 기준으로 README 교체: 실제 학습·모델 저장·궤적 생성·STL 출력 설명.
- 구형 목표물용 계층형 PPO와 24개 층의 순차 3로봇 작업 지원.
- TensorBoard에 PPO 손실, 에피소드 보상, 최근 100회 통과율, 형상 지표 기록.
- 최종 모델 평가와 독립 검증 결과·STL 검사를 별도 TensorBoard 태그로 기록.
- `--version`, `--tensorboard-log`, `--run-name`, `--no-tensorboard` 옵션 추가.

## 설치와 실행

아래 명령은 프로젝트 루트에서 실행합니다. 이 PC에서는 다음 Python을 사용합니다.

```powershell
$python = 'C:/Users/lazzyman/anaconda3/envs/waam/python.exe'
& $python -m pip install -e ./environment
& $python -m pip install torch gymnasium stable-baselines3 tensorboard mapbox-earcut manifold3d pandas
& $python -m models.sphere_ppo --version
```

입력 STL은 프로젝트의 상위 폴더에 있는
`Smooth Sphere - 115644/files/sphere_r-24mm.STL`을 읽습니다.
원본의 크기와 좌표는 바꾸지 않습니다.

```powershell
# 기존 검증 결과를 보존하도록 새 출력 폴더 사용
& $python -m models.sphere_ppo --timesteps 49152 --output outputs/sphere_v1 --run-name sphere_v1
```

학습 전 모든 층·행동 후보의 적층 형상, 궤적 유효성, 충돌을 계산합니다.
이 준비 단계에는 PPO 학습 로그가 아직 생성되지 않습니다. 이후 PPO를 학습하고,
저장한 모델을 다시 불러와 결정론적 궤적을 생성한 뒤 독립 검증과 STL 출력을 수행합니다.

## TensorBoard

학습 시 기본으로 켜집니다. 다른 터미널에서 실행한 뒤
[http://localhost:6006](http://localhost:6006)을 엽니다.

```powershell
$python = 'C:/Users/lazzyman/anaconda3/envs/waam/python.exe'
& $python -m tensorboard.main --logdir ./tensorboard --port 6006
```

| 로그 위치 / 태그 | 내용 |
| --- | --- |
| `sphere_v1_1/train/*` | PPO의 policy/value loss, entropy, KL 등 SB3 지표 |
| `sphere_v1_1/rollout/*` | 평균 에피소드 보상·길이 |
| `sphere_v1_1/episodes/episode/*` | 매 에피소드 보상·길이·누적 횟수 |
| `…/episodes/validation/cached_success` | 현재 에피소드 통과 여부(0 또는 1) |
| `…/episodes/validation/cached_pass_rate_100` | 최근 최대 100개 에피소드의 통과율(0~1) |
| `…/episodes/shape/*` | coverage, overfill, IoU(0~1) |
| `…/evaluation/evaluation/*` | 저장 모델의 결정론적 평가 및 100회 확률적 평가 통과율 |
| `…/evaluation/independent_validation/pass` | 전체 출력 CSV에 대한 독립 검증 결과 |
| `…/evaluation/artifact/*` | STL 폐곡면 여부, 적층 부피와의 상대 오차 |

학습 중 통과율은 캐시된 후보 안전 검사와 누적 형상 지표에 기반합니다.
전체 궤적을 다시 검사하는 최종 독립 검증 결과와 구분해서 해석해야 합니다.
같은 실행 이름의 재학습 로그에는 SB3가 `_2`, `_3` 등을 붙입니다.
TensorBoard 가로축은 실제 학습 스텝입니다. `training_summary.json`에 실행 로그 경로를 기록합니다.

```powershell
# 로그 경로·실행 이름 지정
& $python -m models.sphere_ppo --output outputs/another_run --tensorboard-log ./tensorboard --run-name sphere_trial
# TensorBoard 비활성화
& $python -m models.sphere_ppo --output outputs/no_tb_run --no-tensorboard
```

기존 학습에 대한 손실 로그는 소급 생성하지 않습니다. 기존 체크포인트는 다음 명령으로
재학습 없이 새로 평가하고 평가 결과만 TensorBoard에 기록할 수 있습니다.

```powershell
& $python -m models.sphere_ppo --model outputs/sphere_r-24mm_ppo/ppo_sphere.zip --output outputs/sphere_replay --run-name sphere_replay
```

## PPO가 선택하는 것

관측은 층 진행률, 목표 단면의 면적·둘레, 누적 coverage·overfill,
실패 층 비율, 현재 로봇을 담은 9개 정규화 값입니다.
행동은 외곽선 안쪽 오프셋 4종과 내부 채움 간격 3종을 조합한 12가지 선택입니다.

PPO는 층별 적층 파라미터를 선택합니다. 결정론적 경로 생성기가 STL 단면에 맞는
외곽·래스터 좌표, 이동 속도, T/D/W 모드와 로봇 순서를 생성합니다.
로봇은 층마다 교대하며 작업 후 홈으로 복귀합니다. 24개 층을 각 로봇이 8개씩 담당합니다.
임의의 XYZ 좌표나 로봇 병렬 작업 순서를 직접 학습하는 모델은 아닙니다.

기존 저수준 환경 `environment/gym_wrapper.py`는 별도로 유지합니다.
구형 PPO는 `environment/sphere_wrapper.py`의 `SpherePPOEnv`를 사용합니다.

## 보상과 검증 기준

안전한 층의 중간 보상:

```text
2 × IoU − 20 × max(0, 0.95 − coverage) − 20 × max(0, overfill − 0.05)
```

안전 검사를 실패한 선택에는 -100을 지급합니다. 에피소드 종료 시 전체 조건을
통과하면 +100, 실패하면 -100을 추가합니다. 할인율 gamma는 1.0이며 시간 패널티는 없습니다.

| 검증 기준 | 조건 |
| --- | --- |
| 전체 coverage | 95% 이상 |
| 전체 overfill | 5% 이하 |
| 전체 IoU | 90% 이상 |
| 층별 IoU | 80% 이상 |
| 실패 층 비율 | 5% 이하 |
| 충돌 | Arm Envelope·TCP Radius 모두 검사, 0건 |
| 속도·도달 범위·적층 높이·대기 모드 | 설정된 궤적 규칙 준수 |

샘플 설정의 로봇 크기, 비드 폭 4 mm, 층 높이 2 mm, 작업 속도를 사용합니다.
검증 문턱을 낮추지 않았으며 `fail_on_speed_violation: true`로 속도 검사를 강화했습니다.
최종 검증은 별도 프로세스에서 `validator/src`를 로드해 실제 출력 CSV를 재검사합니다.

## 출력 파일

| 파일 | 내용 |
| --- | --- |
| `ppo_sphere.zip` | 학습된 PPO 체크포인트 |
| `job/target.stl`, `job/config.yaml` | 원본 목표물 복사본과 검증 설정 |
| `job/trajectory.csv` | 검증기용 T/D/W 궤적 |
| `trajectory_robot_modes.csv` | 로봇별 T/D/W/F 궤적 |
| `deposited_sphere.stl` | 실제 적층 형상을 합친 watertight STL |
| `deposited_layers.stl` | 기존 검증기의 층별 STL 출력(내부 공유 면 포함) |
| `selected_actions.json` | 층별 PPO 행동과 담당 로봇 |
| `training.monitor.csv`, `training_summary.json` | 학습·평가 기록과 프로젝트 버전 |
| `artifact_verification.json` | 독립 검증 보고서 위치와 STL 검사 |
| `validation/`, `validation_2/` 등 | 독립 검증 보고서; 재실행 시 기존 보고서 보존 |

궤적 열은 `robot_id,time_s,x_mm,y_mm,z_mm,mode`입니다.
시간 단위는 초, 좌표 단위는 mm입니다. T=이동, D=적층, W=대기, F=작업 완료입니다.
검증기는 F를 받지 않으므로 검증기용 파일에서는 마지막 F를 W로 표현합니다.

## 기존 확인 결과와 테스트

기존 49,152스텝 학습 결과는 `outputs/sphere_r-24mm_ppo`에 보존되어 있습니다.
이 결과는 TensorBoard 추가 전의 실행이며, 새 버전에서 재학습한 결과가 아닙니다.
coverage 99.999229%, IoU 96.325360%, overfill 3.814021%, 충돌 0건,
실패 층 0/24로 독립 검증을 통과했습니다.

```powershell
& $python -B -m unittest environment.test_gym_wrapper models.test_sphere_ppo models.test_tensorboard_reporting -v
& $python models/validate_sphere.py outputs/sphere_r-24mm_ppo/job outputs/sphere_r-24mm_ppo/revalidation
```

`test_sphere_ppo`는 기존 출력 파일을 사용합니다. 정상 통과뿐 아니라 적층 제거,
잘못된 높이, 강제 충돌을 실패로 감지하는지 검사합니다.
TensorBoard 테스트는 짧은 실제 PPO 학습에서 이벤트를 읽어 학습 손실·에피소드·평가 태그를 확인합니다.

검증기는 공칭 적층 형상과 단순화된 충돌 모델을 검사합니다.
열변형, 오버행 지지, 전체 관절 로봇 기구학은 검증 범위에 포함하지 않습니다.

자세한 구현 설명: [models/SPHERE_PPO.md](models/SPHERE_PPO.md).
