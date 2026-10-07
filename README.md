# WAAM trajectory generation 1.1.1

목표 STL을 재현하는 적층 경로를 만들고, **그 경로에서 생성한 STL**을 원본과 비교하는 프로젝트입니다. 원본 STL을 결과물로 복사해 성공으로 처리하지 않습니다. 이전 `Project_version_0.1.2`는 보존하고 별도 버전으로 구성했습니다.

현재 기본 학습은 **미적층 영역의 기하 안내 + PPO 선분 제어(`residual`)**입니다. 저장 모델을 재로드한 256-step 평가에서 box **99.14%**, islands **98.55%**의 실제 STL IoU를 얻었고, 두 선택 경로 모두 **정책의 F 완료·충돌 0·독립 검증 PASS**입니다. 확률적 평가 10회 중 환경 성공은 각각 7회/3회이며, 모든 타깃·모든 episode가 성공하는 모델은 아닙니다. 100% 동일 형상 판정도 아닙니다.

## 최신 개선과 실행

최신 보상 변경: 기본 학습 예산 **50,000 episodes**, 실제 STL 검증 통과 **+10**, 실제 IoU **95% 이상인 검증 성공 경로에만 makespan 보상 최대 +1**을 지급합니다. 상세 수식과 설정은 [현재 보상 설명](RESIDUAL_CONTROL.md#보상)을 참조하세요. 아래 기존 모델 결과는 새 보상으로 재학습한 결과가 아닙니다.

이전 출력에서 드러난 외곽 미충전, islands 사이의 과적층, F 미완료를 개선했습니다. 미충전 영역·공정 높이는 기하 제어기가 안내하고, 선분 양 끝점·로봇·명령은 PPO가 출력합니다. 경로 생성기 `plan.py`의 경로로 대체하지 않습니다. [역할 구분·보상식·재현 방법](RESIDUAL_CONTROL.md)을 확인하세요.

```powershell
python train.py --job-dir ./job --device cuda
tensorboard --logdir ./output
```

기본 제어는 residual, 예산은 50,000 episodes입니다. 기존 256-episode 실험 모델은 `output/train5/model/ppo_model.zip`, TensorBoard는 `output/train5/tensorboard`에 있습니다. 128-step 비교의 기존 모델은 `output/train6`, 새 모델은 `output/train5`입니다. 이전 출력의 64-step 조건과 혼동하지 마세요.

최종 256-step 평가 결과는 `output/train7/result/targets`에 있습니다. [box STL](output/train7/result/targets/001_box/deposited.stl) · [box trajectory](output/train7/result/targets/001_box/trajectory_robot_modes.csv) · [islands STL](output/train7/result/targets/002_islands/deposited.stl) · [islands trajectory](output/train7/result/targets/002_islands/trajectory_robot_modes.csv). 이 결과는 같은 학습 모델에 더 긴 평가 행동 제한을 허용한 별도 실행이며, 128-step 비교 수치와 구분합니다. 저장 모델과 선택 seed로 행동 및 평가 지표가 정확히 재현됨을 확인했습니다: [재현 기록](diagnostics/policy_replay.json).

같은 새 wrapper와 seed 0~9를 사용한 추가 비교에서 기하 안내의 효과와 학습 효과를 구분했습니다. [비교 원시 데이터](diagnostics/residual_comparison.json)를 제공합니다. 기본 제어 변경으로 관측/행동 공간이 달라졌으므로 새 학습을 시작해야 합니다. `--model` 평가 시에는 체크포인트에 맞는 제어기를 자동 선택합니다.

## 첫 번째 학습 정체 수정 기록 — 2026-10-08

이 절의 `stroke`는 이전 개선 방식입니다. 현재 기본은 위에서 설명한 `residual`이며 `--control stroke`로 이전 방식을 사용할 수 있습니다.

기존 `output/train2`의 10,000 episodes 모두 IoU가 0이었습니다. 마지막 1,000개 중 905개가 첫 행동에서 종료했습니다. 충돌 시 강제 종료되는 버그가 아니라 **적층을 전혀 발견하지 못한 정책이 즉시 F로 종료하여 추가 벌점을 피하는 현상**이었습니다.

원인은 홈 위치까지 포함한 수 m 좌표 영역에서 수십 mm 타깃을 찾아야 했고, 동시에 세 로봇의 충돌 회피와 수평 적층 높이를 맞춰야 했다는 점입니다. 무효 적층과 충돌 벌점만 접한 상태에서 MC return으로 업데이트하면 일찍 끝내는 행동을 선호하게 됩니다.

기본 `--control stroke`에서 정책은 `[start_x,start_y,end_x,end_y,height,robot,command]`를 출력합니다. XY는 타깃 bounding box의 비드 중심 범위이며, 높이는 STL/공정에서 얻은 유효 높이로 양자화합니다. 정책이 D를 요청하면 wrapper가 **선택 로봇의 T 이동 → 정책이 고른 선분 D 적층 → T 홈 복귀**를 실행하고 나머지 로봇은 W입니다. 이동도 모두 CSV·충돌 검사에 포함합니다. 원형 경로나 윤곽 템플릿, `plan.py`의 경로를 사용하지 않습니다. 선분·순서·높이·로봇 선택은 정책의 출력입니다.

한 step은 이 명령 하나입니다. 공정 높이 수는 사용자 입력이 아니며 episode 길이를 결정하지 않습니다. F는 세 로봇 전체 완료 요청이며 빈 형상에서도 즉시 종료할 수 있지만 미완성 벌점을 받습니다. **충돌이나 공정 위반만으로는 종료하지 않고** F 또는 max-steps까지 계속합니다. 충돌 이력은 끝까지 남아 성공을 막습니다.

기존 동작 비교는 `--control direct`로 가능합니다. 행동 공간이 달라서 기존 `(3,4)` 체크포인트를 새 `(7,)` 학습의 초기 모델로 사용할 수 없습니다. 새 학습을 시작하세요. `--model` 평가 시에는 체크포인트의 행동 공간으로 wrapper를 자동 선택합니다.

학습 정체 수정 검증:

| 실행 | Episodes | IoU > 0인 episodes | 첫 행동 종료 | 마지막 100개 평균 nominal IoU |
|---|---:|---:|---:|---:|
| 기존 `train2` | 10,000 | 0 | 5,816 | 0% |
| 수정 후 `train3` | 256 | 254 | 2 | 59.77% |

수정 후 256개 학습 episode에서 검사상 충돌은 0이었습니다. 행동·보상 체계가 바뀌었으므로 위 표는 원인 진단용이며 동일 조건의 알고리즘 성능 비교는 아닙니다. [추가 진단 데이터](diagnostics/stroke_fix.json)에는 같은 새 wrapper·seed·64-step 제한으로 초기 정책과 학습 정책을 비교한 결과도 있습니다.

같은 10개 seed로 평가한 평균 nominal IoU는 box 41.17% → 60.02%, islands 33.79% → 51.13%였습니다. 두 정책의 확률적 출력을 그대로 비교했으며, 이 소규모 비교에서 완전 재현 성공은 모두 0건입니다.

학습 모델: `output/train3/model/ppo_model.zip`, 로그: `output/train3/tensorboard`. 별도 샘플 평가인 `output/train4`의 실제 출력 STL IoU는 box **77.825522%**, islands **60.246302%**입니다. 두 결과 모두 max-steps 종료이고 목표 형상 기준에 못 미쳐 FAIL입니다. 기존 기하 생성기의 99%대 결과와 혼동하지 마세요.

## 빠른 실행

이 폴더에서 기존 `waam` 환경을 사용합니다.

```powershell
conda activate waam
python -m pip install -r requirements.txt
python plan.py --job-dir ./job
```

`job`에는 `config.yaml`과 하나 이상의 STL을 넣습니다. 예제 config를 바탕으로 실제 비드 폭·높이, 로봇 위치·작업공간·속도를 지정해야 합니다. 설정 파일이 없을 때 공정값을 추측해서 생성하지 않습니다. STL은 하위 폴더를 제외한 job 폴더에서 찾습니다.

`plan.py`는 각 STL의 단면에서 윤곽·채움 경로 후보를 만들고, 형상 점수와 공정·충돌 검사를 이용해 경로를 선택합니다. 단면 수는 STL과 공정 높이에서 계산하므로 사용자가 층수를 입력할 필요는 없습니다. 작업시간 최소화보다 재현성과 검증을 우선하고, 로봇을 순차 운용합니다.

```powershell
python plan.py --job-dir examples/generic_jobs/sphere
python plan.py --job-dir examples/generic_jobs/sphere --layer-height 0.5 --min-mesh-iou 0.99
python plan.py --job-dir examples/generic_jobs/ring
```

`--layer-height`는 출력 폴더의 config 복사본에만 적용하며, 변경값과 원본 해시를 `provenance.json`에 남깁니다. 0.5 mm 결과를 실제 제작에 사용할 때는 그 높이를 구현할 수 있는 공정이어야 합니다.

## 생성 결과와 검증 기준

`output/planned/trainN`은 기존 번호의 최댓값 + 1로 생성합니다. 각 타깃 결과 폴더에는 다음 파일이 있습니다.

| 파일 | 의미 |
|---|---|
| `deposited.stl` | 경로의 적층 형상을 합집합한 폐곡면 STL |
| `trajectory_robot_modes.csv` | 로봇별 시간·XYZ·T/D/W/F 모드를 포함한 경로 |
| `job/trajectory.csv` | 독립 validator 입력; F는 정지 구간으로 표현 |
| `job/target.stl`, `job/config.yaml` | 해당 실행 입력의 복사본 |
| `plan.json` | 생성 방식, 선택 로봇, 경로 좌표와 후보 설정 |
| `mesh_comparison.json` | 원본과 출력 STL의 실제 3D 체적 비교 |
| `artifact_verification.json` | 최종 판정, 입력 해시, STL 무결성 검사 |
| `validation/` | 독립 공정·충돌·단면 형상 검사 보고서 |

CSV 열은 `robot_id,time_s,x_mm,y_mm,z_mm,mode`입니다. 단위는 초·mm이며 T=이동, D=적층, W=대기, F=완료입니다. 모드는 해당 행에서 다음 행까지의 구간에 적용됩니다. 각 로봇의 마지막 행은 F입니다.

최종 PASS에는 독립 validator 통과와 실제 3D IoU 임계값 통과가 모두 필요합니다. 기본 실제 IoU 임계값은 0.95이며 `--min-mesh-iou`로 지정할 수 있습니다.

```text
3D IoU = volume(target ∩ deposited) / volume(target ∪ deposited)
```

단면 점수만 높다고 성공으로 처리하지 않습니다. STL 내보내기 후 다시 읽어 watertight 및 체적 보존을 검사하고, 원본과 manifold Boolean 연산으로 실제 겹침을 비교합니다. 완전 일치 여부는 별도 `equal_within_volume_tolerance`로 기록합니다. 이는 대칭 차집합 체적 / 타깃 체적 ≤ 1e-6인지를 보는 수치적 기준이며, 메시 삼각형 배열의 동일성을 뜻하지 않습니다.

**PASS는 원본과 100% 동일하다는 뜻이 아닙니다.** 유한한 비드 폭·공정 높이로 만든 구는 계단형 근사를 포함합니다. 비드 모델 또한 열변형·수축·실제 용융 형상을 반영하지 않으며, 충돌 검사는 설정된 TCP/암 envelope 모델입니다. 실제 로봇의 전체 관절 역기구학이나 제작 품질을 보증하지 않습니다.

## 이 버전에서 직접 실행한 결과

아래는 모두 `geometry_planner_not_ppo` 결과입니다. 원본 STL과 실제 출력 STL을 비교한 수치입니다. 모두 검사상 충돌 0, 최종 PASS이며, 완전 일치 판정은 아닙니다.

| 타깃 | 공정 높이 | 실제 3D IoU | 결과 폴더 |
|---|---:|---:|---|
| box | 2 mm | 99.511920% | `output/planned/train1/result/001_box` |
| islands | 2 mm | 99.121457% | `output/planned/train1/result/002_islands` |
| sphere_r-24mm | 2 mm | 96.914495% | `output/planned/train2/result/001_target` |
| sphere_r-24mm | 0.5 mm | **99.218590%** | `output/planned/train3/result/001_target` |
| ring | 1 mm | 99.934576% | `output/planned/train4/result/001_target` |

Sphere는 2 mm에서 단면 IoU가 약 99.98%인데 실제 3D IoU는 96.91%였습니다. 그래서 별도 0.5 mm 실행으로 차이를 줄였습니다. 원본 형상은 수정하지 않았습니다. 가장 정밀한 구 결과: [STL](output/planned/train3/result/001_target/deposited.stl), [모드 포함 경로](output/planned/train3/result/001_target/trajectory_robot_modes.csv), [실제 형상 비교](output/planned/train3/result/001_target/mesh_comparison.json).

## PPO 학습과 TensorBoard

```powershell
python train.py --job-dir ./job --device cuda
tensorboard --logdir ./output --port 6006
```

TensorBoard 주소는 `http://localhost:6006`입니다. 이벤트 파일은 학습 시 자동 생성하며, 웹 서버는 위 명령으로 실행합니다.

학습 실행마다 기존 `output/trainN`의 최대 번호 다음 폴더를 만들고 `model`, `tensorboard`, `result`를 생성합니다. 입력 STL을 매 episode 균등 무작위로 선택하며, 학습 후에는 모든 입력 STL을 각각 평가합니다. 결과 STL은 실제 적층이 있을 때만 생성됩니다. 평가 실패도 JSON에 기록하고 종료 코드 1을 반환하므로, 학습 완료와 검증 통과를 구분할 수 있습니다.

평균 행동만 사용하는 deterministic 평가는 같은 선분을 반복할 수 있습니다. 평가 시 deterministic 1회와 `--eval-episodes`개의 확률적 정책 출력을 모두 기록하고, 성공 여부·공정/충돌 유효성·nominal IoU·F 완료 순으로 후보를 선택하여 실제 STL을 검증합니다. `policy_candidates.json`에 후보 점수와 선택 seed를, `policy_actions.json`에 실제 출력 행동을 남깁니다. 선택 후 좌표를 보정하거나 F를 추가하지 않습니다. `deterministic_evaluation`과 `selected_evaluation`을 구분하며 확률적 성공률은 전체 확률 후보를 기준으로 기록합니다.

| 항목 | 기본값 / 동작 |
|---|---|
| 알고리즘 | SB3 clipped PPO + Monte Carlo return/value baseline |
| Advantage | `A_t = G_t - V(s_t)`, `G_t = sum(r_t ... r_end)`, gamma=1 |
| 수집 | episode 경계까지 수집, 종료 시 가치 bootstrap 없음 |
| 학습 종료 | 기본 50,000개 episode 완료 후 마지막 batch까지 업데이트 |
| Episode 종료 | 세 로봇 모두 F 또는 `--max-steps` 512 도달 |
| 충돌·공정 위반 | 즉시 종료하지 않고 이후 F/시간 제한까지 계속, 실패 이력 유지 |
| 학습률 | 3e-3 → 1e-5, 완료 episode 비율로 선형 감소 |
| PPO KL 제한 | target_kl=0.02 |
| 장치 | auto는 CUDA 우선, `--device cuda`는 CUDA 부재 시 명시적 오류 |
| 모델 행동 | 기본 residual: 힌트 주변 시작/끝 XY·로봇·명령 `(6,)`; stroke `(7,)`; direct `(3,4)` |
| 관측 | 타깃·현재 적층 voxel, 로봇 상태, 공정 범위, 진행도 |

PPO는 완성 경로 후보 선택기가 아닙니다. 기본 residual wrapper의 기하 안내 역할과 이동/적층 실행 규칙은 [제어 설명](RESIDUAL_CONTROL.md)에 공개했습니다. `--control direct`는 예전처럼 세 로봇의 연속 XYZ·모드를 직접 출력하며 높이를 보정하지 않습니다. GPU는 신경망 계산에 사용하며 기하·충돌 계산은 CPU에서 수행합니다. residual은 추가 미적층 계산 때문에 기존 stroke보다 행동당 CPU 비용이 큽니다.

`--rollout-steps`는 업데이트 전 최소 행동 수입니다. MC이므로 진행 중인 episode를 끝내고 업데이트하며, 지정한 마지막 episode에서는 더 수집하지 않습니다. 최대 행동 수에 도달한 episode도 완료 수에 포함합니다. `ep_len_mean`은 최근 episode들의 평균 **행동 횟수**이며, 층수나 episode 수가 아닙니다.

TensorBoard의 global step은 완료 episode 수입니다. `time/eps`, `time/finished_eps`, `time/truncated_eps`와 보상 성분·충돌·형상 지표를 기록합니다. `diagnostics/early_finish`, `deposition_commands`, `invalid_process_steps`로 즉시 종료와 무효 적층을 확인할 수 있습니다. 행동 수와 처리속도는 별도 지표입니다. `independent_validation` 지표는 학습 이후 독립 검사 결과이며, 학습 중의 nominal IoU와 구분합니다.

### 이전 stroke 모드의 보상식

**현재 기본 residual 보상식은 [별도 설명](RESIDUAL_CONTROL.md#보상)을 따릅니다.** 아래는 `--control stroke`의 호환 동작입니다.

기본 stroke 모드에서 `I_t`는 현재 적층과 타깃의 nominal 단면 기반 IoU(0~1)입니다. 매 명령의 원시 보상:

```text
r_t = 100 * (I_t - I_(t-1))
      - 2 * [해당 명령의 공정 위반]
      - 2 * [해당 명령의 충돌]
```

F 완료 또는 max-steps 종료 시 추가:

```text
r_end += 100 * I_final - 100 * (1 - I_final)
         - 100 * [episode 중 공정 위반 또는 충돌 이력]
         + 25 * [F 완료 및 모든 환경 검증 통과]
```

**PPO에 전달하는 보상은 원시 보상의 0.01배**입니다. 빈 F 종료는 -1, 위반 없이 완전 재현하고 F 완료하면 전체 return 2.25입니다. 중복 선분은 IoU를 높이지 않아 추가 형상 보상을 받지 않습니다. 탐색 중 위반 벌점을 줄이고 terminal 안전 벌점은 유지했으며, 보상 크기를 줄여 value 학습을 안정화했습니다. TensorBoard의 개별 성분은 원시 단위, episode/reward는 PPO에 전달한 합계이며 `diagnostics/reward_scale`에 배율을 기록합니다. Makespan 보상은 0입니다. 충돌 패널티는 `--collision-penalty`로 변경할 수 있습니다.

Legacy `--control direct`에서는 기존 보상을 유지합니다: scale=1, 공정 위반 -10, 충돌 -50, terminal 추가 안전 벌점/완료 보너스 없음. 전체 return은 `300*I_final -100 -10*N_invalid -50*N_collision`입니다.

학습 보상에 사용하는 단면 IoU는 최종 3D IoU와 다를 수 있습니다. 최종 합격은 반드시 독립 STL 비교로 판단합니다. 공정상 무효인 행동도 경로에 그대로 남으며 성공으로 인정하지 않습니다.

### 저장 모델 평가

```powershell
python train.py --job-dir ./job --model output/train5/model/ppo_model.zip --grid-size 8 --max-steps 256 --eval-episodes 10
```

위 명령은 최신 residual 256-episode 모델을 평가합니다. 저장 모델의 `policy_contract.json`에 있는 grid-size를 사용합니다. `--model`은 추가 학습 없이 평가하며 새 run 폴더에 결과를 저장합니다. 기존 레이어 선택형 모델은 호환되지 않습니다.

포함된 `output/train1/model/ppo_model.zip`은 CUDA에서 16 episodes, 74 actions로 실제 학습·저장·재로드했습니다. TensorBoard 로그도 `output/train1/tensorboard`에 있습니다. **box/islands 평가 모두 형상 미생성으로 FAIL**이며, 완성된 제작 모델이 아닙니다. 실행 명령:

```powershell
python train.py --job-dir ./job --control direct --device cuda --episodes 16 --rollout-steps 32 --max-steps 8 --grid-size 4 --eval-episodes 1 --run-name v013_mc_check
```

수정 후 학습 확인에 사용한 명령:

```powershell
python train.py --job-dir ./job --control stroke --device cuda --episodes 256 --rollout-steps 512 --max-steps 64 --grid-size 8 --eval-episodes 3 --run-name stroke_fix_check
```

## 테스트

```powershell
python -B -m unittest models.test_episode_ppo models.test_mc_ppo models.test_tensorboard_reporting models.test_trajectory_env models.test_fast_checks models.test_device models.test_run_directory tests.test_reconstruction tests.test_planner tests.test_stroke_wrapper tests.test_residual_wrapper tests.test_terminal_rewards
```

49개 테스트 통과. MC 예산·경계 처리, 마지막 batch, LR, TensorBoard episode 축, 충돌 이력, 저장/재로드, 실제 STL 비교, 경로 일치, seed 재현, F 완료, 검증 실패 시 보너스 차단, makespan 기준과 시간 단조성을 확인했습니다. 테스트 및 예제 통과가 모든 STL의 제작 가능성을 보장하지는 않습니다.

검증 환경: Windows, Python waam 환경, RTX 3070 Ti Laptop, torch 2.14.0+cu126, SB3 2.9.0, Gymnasium 1.3.0, NumPy 2.4.6, trimesh 5.1.0, Shapely 2.1.2, manifold3d 3.5.4. 설치 의존성 범위는 requirements.txt, 각 학습 실행의 실제 버전은 training_summary.json에 기록합니다.

## 0.1.3 패치노트

- 학습 기본 예산을 50,000 episodes로 늘렸습니다.
- residual 종료 검증에 실제 STL 검사를 연결하고 PASS 보너스를 +10으로 높였습니다.
- 검증 성공 및 실제 IoU 임계값 조건을 만족할 때만 지급하는 makespan 보상(최대 +1)을 추가했습니다.
- 시간 기준·보상 파라미터를 CLI, 모델 메타데이터, Monitor, TensorBoard에 기록합니다.

- 현재 출력 기반 개선: residual 관측에 미적층 영역 힌트·공정 높이·연결 성분 범위·완료 가능 상태를 추가했습니다.
- residual을 기본 제어로 지정하고, 과적층 증가·무개선 D·F 없는 timeout 벌점 및 F 성공 보상을 추가했습니다.
- 동일 128-step 조건의 이전/새 정책 평가와, 기하 안내를 포함한 초기/학습 정책 비교를 기록했습니다.

- 학습 정체 수정: 기본 제어를 타깃 주변의 정책 선분 출력으로 변경하고, 원래 직접 XYZ 제어는 `--control direct`로 보존했습니다.
- 형상을 찾기 전에 F로 종료하던 문제를 줄이도록 탐색 범위·초기 분포·명령 구간·벌점 크기를 조정했습니다.
- MC는 유지하고 value target 규모를 줄였습니다. 충돌은 종료 조건에 추가하지 않았습니다.
- 실제 정책 샘플의 후보 평가·선택·seed 재현·행동 기록을 추가했습니다.

- 목적을 타깃 STL 재현 및 로봇 모드 포함 trajectory 생성으로 정리했습니다.
- 기하 기반 경로 생성 CLI와 실제 출력 STL의 3D 비교를 추가했습니다.
- 단면 검증 PASS와 실제 3D 형상 PASS를 구분하고, 오류·빈 적층을 성공 처리하지 않습니다.
- PPO advantage를 완전한 episode의 MC return 기반으로 변경했습니다.
- 정확한 episode 예산·완료 후 마지막 batch 업데이트·TensorBoard episode 축을 유지했습니다.
- IoU 개선량, 종료 유사도/미완성도, 공정 위반, 충돌로 보상을 구성했습니다.
- 다중 STL 무작위 학습, 직접 XYZ·T/D/W/F 출력, GPU 선택을 유지했습니다.
- sphere 전용 진입점·레이어 후보 선택형 학습·중복 MC 학습기를 제외했습니다.
- 이전 출력과 무관한 새 버전 폴더를 만들고, 이번 버전의 검증 결과와 smoke 모델만 포함했습니다.

Sphere 원본의 출처·라이선스는 `examples/generic_jobs/sphere/SOURCE_LICENSE.txt`를 참조하세요.
