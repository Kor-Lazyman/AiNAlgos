# WAAM PPO 학습

프로젝트 루트의 `Models/PPO`는 `Environment/src/waam_validator/rl_env.py`에 있는
`WaamPPOEnv`를 Stable-Baselines3(SB3)의 PPO와 연결합니다. Gym API는 SB3와 호환되는
`gymnasium`을 사용합니다. 기존 `gym` 패키지는 설치하지 않아도 됩니다.

```text
Project_version_0.0.1/
├── Environment/          # 복사한 WAAM 시뮬레이터와 샘플 입력
├── Models/
│   └── PPO/
│       ├── common.py     # 환경 연결, 경로 및 공통 함수
│       ├── train.py      # PPO 학습 및 모델 저장
│       ├── evaluate.py   # 저장한 모델 평가
│       ├── requirements.txt
│       └── runs/         # 실행 시 생성되는 결과 폴더
└── validator/
```

## 설치

Python 3.11 이상이 필요합니다. 아래 명령은 프로젝트 최상위 폴더의 PowerShell에서
실행합니다. `python`이 Microsoft Store만 실행한다면 Python을 먼저 설치해야 합니다.

```powershell
python -m venv Models/PPO/.venv
.\Models\PPO\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "./Environment[rl]"
python -m pip install -r Models/PPO/requirements.txt
```

`Environment`의 설치 설정에 정의된 검증기 의존성도 필요합니다. 코드에서는 이 저장소의
`Environment/src`를 직접 선택하므로 다른 위치에 설치된 `validator`를 잘못 가져오지 않습니다.

## 학습

```powershell
python -m Models.PPO.train --total-timesteps 100000
```

기본 입력은 `Environment/examples/sample_job`입니다. 다른 작업을 학습하려면
`config.yaml`과 `target.stl`이 있는 폴더를 지정합니다. `trajectory.csv`는 환경이 생성합니다.

```powershell
python -m Models.PPO.train --job "C:/data/my_job" --total-timesteps 200000 --max-steps 256 --movement-step-mm 10 --tensorboard
```

직접 파일 실행도 가능합니다: `python Models/PPO/train.py --help`.
기본 입력과 결과 경로는 실행 위치와 관계없이 이 저장소를 기준으로 계산합니다.
사용자가 지정한 상대 경로는 현재 작업 디렉터리를 기준으로 계산합니다.

| 설정 | 기본값 | 의미 |
| --- | ---: | --- |
| `--total-timesteps` | 100000 | 요청한 총 환경 행동 횟수 |
| `--max-steps` | 128 | 에피소드당 행동 횟수 |
| `--n-steps` | 1024 | PPO 업데이트 전 수집할 행동 횟수 |
| `--batch-size` | 64 | 업데이트 미니배치 크기 |
| `--learning-rate` | 0.0003 | 학습률 |
| `--n-epochs` | 10 | 수집한 데이터의 업데이트 반복 횟수 |
| `--eval-freq` | 5000 | 별도 평가 환경을 실행할 간격 |
| `--checkpoint-freq` | 10000 | 중간 모델 저장 간격 |
| `--seed` | 42 | 난수 시드 |
| `--device` | cpu | 학습 장치 (`cpu`, `cuda`, `auto`) |

단일 학습 환경과 별도의 평가 환경을 사용합니다. `batch-size`는 `n-steps`의 약수여야
합니다. SB3는 rollout 단위로 학습하므로 실제 행동 횟수가 `total-timesteps`보다 조금
많을 수 있습니다. 실행마다 새 결과 폴더가 만들어집니다.

```text
runs/<실행시각_고유번호>/
├── config.json             # 환경 및 PPO 설정, 라이브러리 버전
├── final_model.zip         # 정상 종료 시 최종 모델
├── interrupted_model.zip   # Ctrl+C로 학습을 중단한 경우
├── train.monitor.csv       # 학습 에피소드 보상/길이
├── eval.monitor.csv        # 평가 에피소드 보상/길이
├── logs/progress.csv       # PPO 업데이트 통계
├── checkpoints/            # 설정한 간격의 중간 모델
├── best/best_model.zip     # 주기적 평가에서 최고 평균 보상을 얻은 모델
└── evaluation/             # 주기적 평가 기록
```

학습 길이가 평가/저장 간격보다 짧으면 `best_model.zip`이나 체크포인트는 생성되지
않을 수 있습니다. 최종 모델은 정상 종료 시 저장됩니다. TensorBoard 사용 시:

```powershell
tensorboard --logdir Models/PPO/runs
```

## 저장한 모델 평가

`<실행폴더>`를 실제 생성된 폴더 이름으로 바꿉니다.

```powershell
python -m Models.PPO.evaluate --model "Models/PPO/runs/<실행폴더>/final_model.zip" --episodes 5
python -m Models.PPO.evaluate --model "Models/PPO/runs/<실행폴더>/best/best_model.zip" --output evaluation.json
```

학습 때 저장한 `config.json`에서 환경 설정을 자동으로 읽습니다. 모델을 다른 위치로
옮겼다면 `--config "경로/config.json"`을 지정합니다. `--job`으로 평가 입력을 변경할 수
있습니다. 평균 보상 외에도 에피소드별 검증 결과와 검증 오류 수를 출력합니다.
기존 보고서 파일은 덮어쓰지 않습니다.

## 짧은 연결 확인

```powershell
python -m Models.PPO.train --total-timesteps 16 --n-steps 8 --batch-size 4 --n-epochs 1 --max-steps 4 --eval-freq 8 --eval-episodes 1 --checkpoint-freq 8
```

이 명령은 환경 검사, PPO 업데이트, 주기적 평가와 모델 저장이 연결되는지 확인하는
용도입니다. 유효한 적층 경로를 학습했다는 의미는 아닙니다.

## 현재 환경의 동작 범위

행동은 로봇 3대의 `(dx, dy, 적층 요청)`을 합친 9차원 연속값이고, 관측은 로봇 XYZ
위치와 진행률을 합친 10차원 값입니다. 적층은 현재 환경이 제공하는 첫 번째 층에
한정됩니다. 에피소드 마지막에 전체 검증을 실행합니다.

현재 보상은 중간 단계의 적층 이동 거리와 마지막 단계의 형상·충돌·도달 범위 검증
점수를 사용합니다. 따라서 평균 보상이 올라가도 검증 `PASS`를 보장하지 않습니다.
샘플 입력에서 무작위 초기 정책은 작업 영역 밖 적층으로 검증 오류가 날 수 있으며,
평가 보고서의 `validation_error_count`와 `pass_count`를 함께 확인해야 합니다.
타깃 형상이나 누적 적층 지도가 관측에 포함되지 않아 여러 형상에 대한 일반화와
다층 경로 최적화에는 환경 확장이 필요합니다.

참고: [SB3의 사용자 정의 환경 인터페이스](https://stable-baselines3.readthedocs.io/en/master/guide/custom_env.html),
[Gymnasium Env API](https://gymnasium.farama.org/api/env/).
