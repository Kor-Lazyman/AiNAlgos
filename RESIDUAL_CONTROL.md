# 현재 출력에 기반한 개선: residual 제어

기존 `output/train4`에서 box는 22.17%가 미충전됐습니다. islands는 coverage 72.07%, 과적층/타깃 체적 19.63%였으며, 떨어진 두 부품 사이를 잇는 선분이 문제였습니다. 두 결과 모두 64-step 제한에서 끝나 F 완료가 없었습니다.

## 제어기의 역할과 정책의 역할

`--control residual`은 기하 안내를 사용하는 PPO입니다. 목표 형상과 현재 적층 형상의 차이를 계산하여, 새로 채울 면적이 큰 영역의 **중심 힌트·공정 높이·연결 성분 범위**를 제어기가 정합니다. 후보 중심 주변 원판과 미적층 영역의 교차 면적으로 위치를 고르며 이미 생성한 경로 목록은 사용하지 않습니다. 계산한 위치는 다음 행동의 관측 `guidance`에 제공합니다.

정책의 6차원 행동은 `[start_dx, start_dy, end_dx, end_dy, robot, command]`입니다. 정책이 양 끝점의 XY 오프셋, 로봇, 명령을 정합니다. 오프셋은 비드 폭의 2배 범위이며 양 끝점은 해당 연결 성분의 bounding box 안쪽 비드 중심 범위로 제한합니다. D 명령은 실제 T 접근 → D 선분 → T 홈 복귀로 실행하고, 그 모든 동작을 기록·검사합니다.

**이 방식에서 공정 높이와 미충전 영역 선택은 기하 제어기의 역할입니다.** PPO가 STL slicing 자체나 영역 선택까지 학습했다고 주장하지 않습니다. 기존 `plan.py`의 윤곽/채움 경로를 가져오거나 결과 경로를 치환하는 방식도 아닙니다. `policy_actions.json`에 모델의 원래 행동과 사용한 기하 힌트를 함께 기록합니다.

연결 성분 구분은 islands 사이의 빈 공간을 가로지르는 행동을 줄입니다. 다만 오목한 부품이나 구멍에서는 bounding box 안의 선분도 밖으로 나갈 수 있습니다. 그런 선분을 타깃 경계로 잘라 숨기지 않고, 실제 과적층으로 기록하고 벌점을 줍니다.

`guidance`의 완료 가능 표시는 nominal 형상 기준 충족 여부입니다. 표시가 켜져도 자동 종료하지 않습니다. **정책이 F를 출력해야 종료**되며, 제한에 도달한 경로에는 F를 추가하지 않습니다. 충돌 후에도 행동을 계속하고, 해당 episode의 실패 이력은 끝까지 유지합니다.

PPO 출력의 `artifact_verification.json`은 독립 형상/공정 판정을 `independent_geometry_process_status`에 보존하고, `policy_completed`와 합쳐 최종 `validation_status`를 기록합니다. STL 형상이 통과했어도 정책이 F로 완료하지 않으면 최종 FAIL입니다.

## 보상

현재 보상 버전은 `residual_validated_makespan_v2`입니다. **아래는 0.01 스케일링 후 PPO가 실제 받는 단위**입니다. `I`는 nominal 단면 IoU, `O`는 과적층/타깃 비율입니다.

```text
매 행동:
  (I_now - I_before)
  - 0.02 * 공정 위반 여부
  - 0.02 * 충돌 여부                         # collision-penalty 기본 2의 0.01배
  - 2 * max(0, O_now - O_before)
  - 0.005 * (D를 요청했지만 IoU 개선량이 1e-6 이하)

episode 종료 시 추가:
  + 2 * I_final - 1
  - 1 * (과거 공정 위반 또는 충돌이 있었던 경우)
  - 0.25 * (F 없이 max-steps에 도달한 경우)
  + 10 * (F 완료 및 최종 검증 통과)
  + R_makespan

R_makespan = 1 / (1 + T / T_ref)
  단, F 완료 + 최종 검증 통과 + 실제 STL IoU >= 0.95일 때만 지급.
  조건을 만족하지 않으면 정확히 0.
```

검증 통과 보너스를 기존 +1에서 **+10**으로 올렸습니다. Makespan 보상은 0~1로 제한해 검증 보상보다 작게 유지합니다. `T`는 초 단위 실제 시뮬레이션 makespan이며 T/D/W·홈 복귀·F 구간을 포함합니다. 빠를수록 큰 보상을 받고, 중간 행동마다 누적 지급하지 않고 종료 시 한 번만 지급합니다. gamma=1인 완전 episode MC를 유지합니다.

최종 검증은 F 완료·누적 공정/충돌 검사·nominal 형상 검사를 통과한 후보에만 실행합니다. **전체 trajectory를 다시 검사하고 적층 STL을 메모리에서 생성·재로딩하여 폐곡면/체적 및 실제 3D IoU를 확인**합니다. 실제 IoU 합격 기본값은 0.95입니다. 이 추가 검사에서 실패하거나 예외가 발생하면 검증/시간 보상은 0이고 환경 success도 false입니다. 별도 `validate.py`의 최종 검증도 유지하며 동일한 STL 합집합 생성 함수를 사용합니다.

`T_ref`는 타깃별 기준 시간입니다. 기본은 nominal 타깃 총 단면적 `A`, 비드 폭 `w`, 적층 속도 `v_D`, 이동 속도 `v_T`에서 `A/(w*v_D) + max(1,A/(2*w*w)) * 평균 홈↔타깃 중심 왕복시간`으로 계산합니다. 최적 시간의 증명이 아니라 크기가 다른 타깃의 보상 스케일을 맞추기 위한 기준입니다. 설정값과 타깃별 실제 기준 시간은 `training_summary.json`에 저장합니다.

옵션은 residual 모드에 적용됩니다.

| 옵션 | 기본값 | 의미 |
|---|---:|---|
| `--episodes` | 50000 | 완료 episode 예산 |
| `--makespan-iou-threshold` | 0.95 | 시간 보상을 허용하는 실제 STL IoU |
| `--makespan-weight` | 1 | 시간 보상 최대값, PPO 단위 |
| `--makespan-reference-seconds` | 자동 | 타깃별 계산 대신 사용할 양수 기준 시간 |
| `--validation-bonus` | 10 | 최종 검증 성공 보너스, PPO 단위 |
| `--validation-min-mesh-iou` | 0.95 | 최종 실제 STL 합격 기준 |

`0 <= makespan-weight < validation-bonus`를 요구합니다. 시간 보상 기준을 0.98로 높이면, 실제 IoU 0.97의 검증 성공 경로는 +10만 받고 시간 보상은 받지 않습니다.

```powershell
python train.py --job-dir ./job --device cuda --episodes 50000 --makespan-iou-threshold 0.95 --makespan-weight 1 --validation-bonus 10
```

TensorBoard의 `reward/reward_makespan_ppo_units`, `reward/reward_validation_bonus_ppo_units`는 PPO에 전달하는 단위입니다. `terminal/makespan_s`, `terminal/makespan_reference_s`, `terminal/terminal_mesh_iou`, `terminal/terminal_validation_pass`로 조건을 확인합니다. 기존 개별 형상/공정 보상 성분은 원시 단위인 점에 유의하세요.

TensorBoard에 `diagnostics/finish_ready`, `diagnostics/duplicate_steps`, `reward/episode_reward_overfill`을 추가했습니다. x축은 계속 완료 episodes입니다.

## 실행과 호환성

```powershell
python train.py --job-dir ./job --control residual --device cuda
tensorboard --logdir ./output
```

학습 기본 예산은 10,000에서 **50,000 episodes**로 늘렸습니다. 초기 학습률 3e-3 → 1e-5, 자동 `output/trainN` 생성은 유지합니다. residual 관측/행동 공간은 이번 보상 변경으로 달라지지 않았습니다. 기존 모델은 `--model` 평가 시 원래 제어 방식으로 자동 선택되며, 추가 학습 없이 새 보상으로 평가합니다. 기존 방식으로 새 학습을 하려면 `--control stroke`, 원시 XYZ 제어는 `--control direct`입니다.

이번 시험은 기본 전체 예산보다 짧은 256 episodes였습니다.

```powershell
python train.py --job-dir ./job --control residual --device cuda --episodes 256 --rollout-steps 1024 --max-steps 128 --grid-size 8 --eval-episodes 10 --run-name residual_check
```

평가는 deterministic 1개와 같은 seed 0~9의 확률 정책 경로 10개를 생성합니다. 최종 출력은 그 후보에서 선택한 실제 정책 경로입니다. 학습용 입력 두 개에 대한 결과이며, 미학습 타깃 일반화나 반복 성공을 보증하는 결과가 아닙니다. 기존 모델과의 비교도 동일한 128-step 제한을 사용합니다.

기하 안내만으로 생기는 향상과 학습 효과를 구분하려고 새 wrapper의 초기 정책도 같은 조건으로 따로 평가했습니다. 원시 기록은 `diagnostics/residual_initial_policy.json`, 최종 비교는 `diagnostics/residual_comparison.json`입니다.

## 측정 결과

아래 성능 표는 makespan 보상 도입 **이전**에 학습한 모델의 기록입니다. 새 보상으로 50,000 episodes 학습을 완료한 결과가 아닙니다. 이번 변경에서는 CUDA 8-episode smoke 학습(`output/train8`), 기존 성공 경로의 실제 검증/새 보상 재계산(`diagnostics/makespan_reward_check.json`), 조건별 회귀 테스트를 수행했습니다.

동일한 128-step 제한 및 확률 seed 0~9로 비교했습니다. 표의 실제 IoU는 선택된 경로의 출력 STL을 원본과 Boolean 체적으로 비교한 값입니다.

| 타깃 | 기존 모델 실제 IoU | 개선 모델 실제 IoU | 개선 모델 최종 판정 |
|---|---:|---:|---|
| box | 83.93% | 97.84% | PASS, 정책 F 완료 |
| islands | 64.41% | 97.30% | FAIL, 형상 통과지만 F 없이 timeout |

새 wrapper를 고정한 초기/학습 정책 비교의 평균 nominal IoU는 box **49.68% → 95.02%**, islands **44.12% → 81.75%**였습니다. 초기 정책의 환경 성공은 0/10, 0/10이고 학습 후에는 5/10, 0/10이었습니다. 따라서 기하 안내에 따른 개선과 그 위에서의 학습 효과를 함께 보고합니다.

F 미완료를 확인하기 위해 **동일 모델**의 평가 제한만 256 steps로 늘린 별도 실행(`output/train7`)도 수행했습니다.

| 타깃 | 선택 경로 실제 IoU | 선택 경로 행동 수 | 최종 판정 | 확률 후보 환경 성공 |
|---|---:|---:|---|---:|
| box | 99.137517% | 213 | PASS, F 완료·충돌 0 | 7/10 |
| islands | 98.552316% | 213 | PASS, F 완료·충돌 0 | 3/10 |

확률 후보 성공은 환경 기준이며, 선택된 각 경로에는 추가로 독립 실제 STL 검증을 수행했습니다. 이 결과를 동일한 128-step 조건의 개선 폭으로 표시하지 않습니다. 선택한 두 경로 모두 seed=0의 실제 정책 샘플이며, 임의로 F를 덧붙이지 않았습니다. 모든 타깃·모든 실행에서의 성공이나 원본과 100% 동일함을 보장하지 않습니다.

모델은 `output/train5/model/ppo_model.zip`, 최종 STL/CSV는 `output/train7/result/targets/{001_box,002_islands}`에 있습니다.

```powershell
python train.py --job-dir ./job --model output/train5/model/ppo_model.zip --device cuda --grid-size 8 --max-steps 256 --eval-episodes 10
```

## 검증 항목

미적층 영역, 과적층, F 완료, MC, 충돌, 출력 STL 검사에 더해 IoU 임계값 경계, 검증 실패 시 보너스 차단, 대기 시간에 따른 보상 감소, 실제 STL 검증 보너스, reset 초기화를 검사했습니다. 49개 테스트가 통과했습니다.
