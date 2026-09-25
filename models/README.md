# PPO 학습

`Project_version_0.0.2` 루트에서 실행합니다. Python 3.11 이상과 기존
`environment`의 의존성이 필요합니다. 추가 학습 패키지는 다음과 같습니다.

```powershell
python -m pip install "stable-baselines3>=2.3,<3" "gymnasium>=0.29,<2"
```

## 설정과 실행

`config.py`의 `CONFIG`에 환경 클래스, 환경 생성 인자, 모델 이름, 학습 횟수,
seed, 장치, 저장 폴더가 있습니다. `PPOConfig`에서 다음 값을 조절합니다.

| 설정 | 의미 | 기본값 |
| --- | --- | --- |
| `lr` | 학습률 (`learning_rate`) | 0.0003 |
| `eps` | Adam optimizer의 수치 안정성 epsilon | 0.00001 |
| `clip_range` | PPO 정책 비율 clipping epsilon | 0.2 |
| `n_steps` | 업데이트당 환경 실행 횟수 | 256 |
| `batch_size` | 미니배치 크기 | 64 |
| `n_epochs` | rollout당 최적화 반복 횟수 | 10 |
| `gamma`, `gae_lambda` | 할인율, GAE 계수 | 0.99, 0.95 |
| `ent_coef` | 탐색을 위한 엔트로피 보상 계수 | 0.0 |
| `hidden_sizes` | MLP 은닉층 크기 | (64, 64) |

PPO에는 epsilon-greedy 탐색률이 없습니다. PPO clipping의 epsilon을 바꾸려면
`clip_range`를 수정하세요. 현재 지원 모델 이름은 `ppo`입니다.

```powershell
# 기본 설정: 100,000 steps 요청 (마지막 rollout을 채우므로 실제 횟수는 더 클 수 있음)
python -m models.learn --model ppo

# 빠른 연결 확인: 64 steps, episode 최대 4 steps
python -m models.learn --model ppo --smoke-test

# 실행 시 일부 설정 변경
python -m models.learn --model ppo --timesteps 10000 --seed 7 --device cpu

# 파일 저장 없이 학습
python -m models.learn --smoke-test --no-save
```

`python models/learn.py`로도 실행할 수 있습니다. `--job-dir`, `--max-steps`,
`--output-dir` 옵션도 지원합니다. CLI는 학습 후 `models/checkpoints/` 아래에
고유한 이름의 SB3 `.zip` 모델을 저장합니다. CSV/JSON 보고서나 파일 로그는
생성하지 않습니다. SB3 표준 zip 안에는 가중치와 재로딩용 메타데이터가 들어갑니다.

## 코드에서 사용

```python
from stable_baselines3 import PPO
from models.config import CONFIG
from models.learn import learn, save_model

env = CONFIG.make_env()  # 직접 생성한 WaamGymEnv를 전달해도 됩니다.
try:
    model = learn(CONFIG.model_name, env, CONFIG)
    checkpoint = save_model(model, CONFIG.output_dir)
    loaded = PPO.load(checkpoint, device=CONFIG.device)
    obs, info = env.reset()
    action, _ = loaded.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
finally:
    env.close()
```

`learn(config=CONFIG)`는 설정에서 모델과 환경을 생성합니다. 이 경우 사용 후
`model.get_env().close()`를 호출하세요. `learn()` 자체는 저장하지 않습니다.

## 래퍼와 보상

관측은 `(3, 5)`의 `[time, x, y, z, mode]`, 행동은 `(3, 4)`의 정규화된
`[x, y, z, mode]`를 유지합니다. SB3 checker는 2차원 관측이 특이하다는 경고를
출력하지만, `MlpPolicy`가 내부에서 15개 값으로 펼쳐 처리합니다.
별도의 이미지 CNN이나 상태 구조 변경은 필요하지 않습니다.

매 단계 makespan 증가량과 충돌을 보상에 반영합니다. 종료 시에만
`check_validation()`과 `check_shape()`를 검사하며, 세 로봇이 모두 F이고
두 검사가 모두 통과해야 성공입니다. 시간 제한 종료는 실패입니다.
F는 검사 입력에서 W로 변환됩니다. 충돌은 별도의 단계별 패널티입니다.

## 실제 학습 연결 테스트

```powershell
python -B -m unittest environment.test_gym_wrapper models.test_learning -v
```

기존 래퍼 테스트에 더해, SB3 환경 검사, 실제 64-step PPO 학습에서 유한한 보상과
loss, 가중치 변경, lr/eps 설정 전달, 모델 저장·재로딩과 동일한 행동 예측을
검증합니다. 검증 함수를 mock으로 대체하지 않은 실제 환경을 사용합니다.
임시 테스트 모델은 테스트 종료 후 정리됩니다.

실제 확인한 조합은 Python 3.12.4, Stable-Baselines3 2.9.0,
PyTorch 2.14.0, Gymnasium 1.3.0입니다. 래퍼 12개와 학습 통합 3개 테스트가
모두 통과했고 CLI의 64-step 학습과 모델 저장도 확인했습니다.

현재 컴퓨터에서는 다음 임시 가상환경에 학습 패키지가 설치되어 있습니다.
기본 `python` 명령이 Microsoft Store로 연결된다면 아래처럼 실행하세요.

```powershell
Set-Location 'C:/Users/lazzyman/Desktop/AI_Algo/Project_version_0.0.2'
$ppoPython = 'C:/Users/lazzyman/AppData/Local/Temp/waam-gym-check-002/Scripts/python.exe'
& $ppoPython -B -m models.learn --model ppo --smoke-test
& $ppoPython -B -m unittest environment.test_gym_wrapper models.test_learning -v
```

임시 폴더는 OS 정리 시 삭제될 수 있으므로 장기 학습에는 별도의 프로젝트
가상환경을 사용하세요. 이 테스트 환경은 기존 `Polars binary is missing!`
경고도 출력하지만, 이번 dict/DataFrame 기반 경로의 테스트는 모두 통과했습니다.

짧은 연결 테스트 통과가 목표 형상 제작 학습의 수렴을 뜻하지는 않습니다.
현재 15개 관측값에는 누적 적층 형상이 없으며, 연속 XYZ 행동에서 유효한 적층을
탐색하고 마지막 형상 보상을 얻는 일은 별도의 장기 학습 평가가 필요합니다.

API 참고: [SB3 PPO 공식 문서](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html).
