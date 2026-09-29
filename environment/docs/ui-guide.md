# UI 사용 안내

WAAM Validator UI는 여러 작업을 관리하는 목록 화면이 아니라 **한 작업의 입력 확인,
Validation, 결과 해석을 끝까지 이어 가는 로컬 인터페이스**입니다.

## 실행

```powershell
waam-validator ui C:\data\my_job
```

`JOB_DIR`은 화면의 폴더 입력란에 미리 채워집니다. 기본 브라우저가
`http://127.0.0.1:8050`을 열며 다음 옵션을 사용할 수 있습니다.

```powershell
waam-validator ui C:\data\my_job --port 8051
waam-validator ui C:\data\my_job --no-browser
```

기본 host는 loopback인 `127.0.0.1`입니다. 이 UI에는 인증이 없으므로 신뢰할 수
없는 네트워크에 공개하는 용도로 사용하지 마십시오.

## 화면 1: 입력 준비

### 폴더 지정

세 입력 파일이 함께 있는 폴더 하나를 지정합니다.

```text
my_job/
├── config.yaml
├── trajectory.csv
└── target.stl
```

Windows에서는 `찾아보기`를 사용하거나 경로를 직접 붙여 넣을 수 있습니다. 폴더를
바꾼 뒤에는 반드시 `입력 확인`을 다시 누릅니다. 원본 파일은 복사하거나 덮어쓰지
않습니다.

### 입력 확인

`입력 확인`은 버튼을 누른 시점에 세 파일을 **한 번만** 읽습니다. 유휴 상태에서
주기적으로 trajectory나 STL을 다시 읽지 않습니다. 이 단계에서는 다음을 확인하고
preview를 만듭니다.

- 파일 절대 경로, 크기, 수정 시각
- Config 필드·타입과 로봇·공정·workspace·threshold
- Robot별 Arm Capsule 반경·전체 폭, 공통 안전거리와 pair별 요구 중심선 간격
- Trajectory 전체 행 수, makespan, 로봇별 시간·XYZ 범위, D/T/W 시간·거리·속도
- Target의 정점·면·body 수, 경계·치수·체적·watertight 상태
- Trajectory 의미, XY Reach 예상 위반, Target/trajectory 좌표 일관성

충돌 시뮬레이션, Target layer slicing, 전체 형상 비교와 결과 산출물 생성은 이때
실행하지 않습니다.

### 입력 상태

| 상태 | 의미 | Validation 버튼 |
| --- | --- | --- |
| `READY` | 검사 항목에 문제가 없음 | 활성화 |
| `WARNING` | 비치명 이슈가 있으나 실행 가능 | 활성화 |
| `EXPECTED_FAIL` | XY Reach·Wait·설정된 속도 기준 등 정상 FAIL 예상 | 활성화 |
| `BLOCKED` | 파싱·Config·좌표·Deposition layer 등 치명 오류 | 비활성화 |

`EXPECTED_FAIL`은 실행 오류가 아닙니다. 전체 계산과 결과 저장이 가능하지만 최종
상태가 FAIL일 가능성이 있다는 의미입니다.

입력 확인 시 파일별 SHA-256, 크기와 수정 시각으로 signature를 만듭니다. 이후 파일이
변경되거나 폴더 경로가 바뀌면 기존 검사 context를 무효화하고 Validation을
차단합니다. 최신 내용을 기준으로 `입력 확인`을 다시 실행하십시오.

### Preview 해석

#### 3D 작업 공간

- Target STL
- Robot Base와 Base XY 삼각형
- 설정한 경우, Base와 구분되는 명목 Home TCP 위치
- 각 Base 중심의 열린 반투명 XY Reach 원통과 Base Z 위치의 footprint 원
- World XY의 원형 workspace
- 로봇별 Deposition, Travel, Wait trajectory

브라우저 응답성을 위해 Target preview는 최대 50,000 face, trajectory는 로봇당
최대 10,000점으로 제한합니다. 시작·종료와 mode 전환점을 우선 보존하고, Target
단순화가 실패하면 결정론적 face sampling을 사용합니다. 이 제한은 **화면 표시만**
위한 것이며 Validation은 원본 전체 데이터를 사용합니다.

#### 작업 Gantt

R1/R2/R3을 각각 하나의 가로 막대로 표시하고, 원본 interval에서 연속된 같은 mode를
하나의 run으로 합쳐 실제 시작·종료 시간에 맞춰 색상을 전환합니다. Hover에서 각
상태의 시작, 종료와 지속시간을 확인할 수 있습니다.

- Deposition: 재료를 적층하며 이동하는 구간
- Travel: 적층하지 않고 다음 위치로 이동하는 구간
- Wait: trajectory가 지정한 위치를 유지하며 대기하는 구간
- 완료 후 비활성: 해당 로봇의 trajectory 종료부터 전체 makespan까지

네 상태는 시간축에서 서로 겹치지 않습니다. 모든 로봇의 첫 timestamp는 0이므로
별도의 `작업 전 비활성` 상태는 현재 입력 schema에 필요하지 않습니다.

수십 시간짜리 작업의 수만 개 상태 구간을 그대로 브라우저에 보내지 않습니다. 최초
전체보기는 최대 2,000개 시간 bin으로 요약하며 hover에는 각 bin 안의 실제
Deposition/Travel/Wait/완료 후 비활성 시간을 표시합니다. 각 bin의 가장 긴 상태만
선택하면 짧고 반복적인 Deposition과 Wait가 사라지므로, 인접 bin 전체에서 실제
상태시간 비율이 보존되도록 색상을 결정론적으로 분배합니다. 전체보기의 개별 색 cell은
순간 상태가 아니라 시간 비율 요약이며, 범위를 확대하면 선택 구간의 정확한 원본 상태
run을 서버에서 한 번 불러옵니다. 막대 외곽선은 사용하지 않습니다.

#### 로봇별 상태 시간 비율

공통 makespan을 100%로 놓고 각 로봇의 Deposition/Travel/Wait 시간을 표시합니다.
각 로봇이 makespan보다 먼저 끝났다면 남은 부분은 Wait가 아니라
`완료 후 비활성`입니다.
그래프에 기준 makespan의 초·분·시간 환산값을 함께 표시합니다.

#### 로봇별 경로 길이

Deposition과 Travel interval의 3D 누적 TCP 거리입니다. 시간이 짧은 Travel이라도
설정 속도가 Deposition보다 크면 Travel 거리가 더 길 수 있습니다. 정확한 값은
trajectory 정보와 hover에서 확인합니다.

#### 로봇별 XY Reach 사용률

`Base에서 가장 먼 TCP까지의 XY 거리 / 설정 XY Reach 반경`입니다. Z는 계산에서
제외됩니다. 100%는 설정 한계, 100% 초과는 XY Reach FAIL을 뜻하며 경로 길이와는
다른 지표입니다. 3D 화면의 원통은 표시 중인 Z 범위만 관통하지만 판정 자체에는
상·하한이 없습니다.

## 화면 2: Validation 진행

입력 상태가 실행 가능하고 signature가 그대로이면 `Validation 실행`이 활성화됩니다.
누르면 입력 확인에서 만든 동일한 canonical 작업 context를 별도 Python process에
직접 전달합니다.

진행 화면에는 다음을 표시합니다.

- 전체 진행률과 현재 단계 진행률
- 처리한 simulation 시간, interval 또는 layer 수
- 경과 시간과 실측 속도 기반 예상 잔여 시간
- 제한된 최신 실행 로그

단계별 전체 진행률 구간은 다음과 같습니다.

| 단계 | 전체 진행률 |
| --- | --- |
| 입력 로딩 | 0–5% |
| 충돌 검사 | 5–45% |
| 적층 layer 형상 | 45–60% |
| Target slicing | 60–85% |
| 형상 지표 | 85–95% |
| 핵심 결과 기록 | 95–100% |

UI는 실행 중에만 상태 파일의 작은 진행 정보와 제한된 log tail을 1초 간격으로
확인합니다. 이 과정에서 trajectory, STL, 결과 CSV나 그래프를 다시 읽지 않습니다.
프로세스가 끝나면 polling을 즉시 끄고 정확히 그 process의 output 폴더로 결과
화면을 한 번 갱신합니다. 중단 버튼은 제공하지 않습니다.

## 화면 3: 결과

상단에는 결론에 필요한 네 항목만 표시합니다. 전체 작업시간, Robot XY Reach, 로봇 간
충돌 안전, 적층 형상입니다. 최종 PASS/FAIL과 실행 폴더·시각은 바로 위 결과 배너에서
확인합니다.

### 판정 요약

FAIL 사유와 추가 확인사항만 모아서 보여줍니다. XY Reach, 2D 충돌 안전, Layer 형상 비교의
결론은 위쪽 핵심 카드에 이미 있으므로 이 탭에서 반복하지 않습니다. Warning은 결과를
무조건 FAIL로 만들지 않으므로 FAIL 사유와 구분됩니다. 정상 FAIL을 만든 violation
기록은 치명적인 실행 `ERROR`와 혼동하지 않도록 `FAIL 세부 판정 기록` 펼침 영역에
표시합니다.

### 로봇·일정

상태 시간 그래프는 공통 Makespan을 100%로 두고 Deposition + Travel + Wait +
완료 후 비활성을 합해 로봇마다 정확히 100%가 되도록 표시합니다. 상세 표에는
completion의 초 값과 시·분·초 표현, D/T/W 시간, D/T 거리·평균속도,
최대/한계 XY Reach와 XY margin을 표시합니다.

### 충돌 안전

Arm Envelope와 TCP Radius는 반원형 gauge 대신 `측정 최소거리`, `요구 최소거리`,
`안전 여유`를 직접 비교합니다. 안전 여유가 양수면 요구거리보다 떨어져 있다는 뜻입니다.
각 항목에는 최악 robot pair·시각과 event 수가 함께 표시됩니다. Event가 없으면 비어 있는
시간축과 표를 반복하지 않고 “충돌 이벤트 없음” 상태 하나만 표시합니다.
이벤트가 있으면 종류와 Robot pair별 한 줄에 전체 이벤트를 표시하며 1,000건 이후를
조용히 생략하지 않습니다. 순간 이벤트는 별도 marker로 표시하고 정확한 전체 행은
페이지 방식 상세 표와 `collision_events.csv`에서 확인합니다.

최악 시점 XY Snapshot은 실제 Arm Capsule을 채움 영역으로, 각 Capsule에 공통
`arm_clearance_mm / 2`를 더한 판정 외곽선을 점선으로 표시합니다. Closest points와
그 사이 거리선은 실제 mm 축척으로 그리며 PASS/FAIL과 수치를 색상 외 텍스트로도
제공합니다. 데스크톱에서는 패널 전체 폭과 확대된 높이를 사용하고, 화면이 좁아지면
반응형으로 축소됩니다. 화면의 Plotly snapshot이 단일 시각화 원본이며 정적 PNG는
만들지 않습니다.

### 형상

전체 Coverage·IoU, 최대 Layer Underfill·Overfill과 실패 Layer 수를 우선 표시합니다.
Layer 그래프의 위쪽은 Coverage·IoU이고 아래쪽은 작은 Underfill·Overfill·IoU 손실을
확대한 그래프입니다. 따라서 모든 값이 100%에 가까운 샘플에서도 미세한 차이를 확인할
수 있습니다. 정확한 값은 Layer별 수치 표에서 네 자리 백분율로 확인합니다. 형상
임계값은 핵심 지표 아래에 항상 표시됩니다.

각 지표의 Layer 간 편차가 표시 허용오차 안이면 동일 범위라고 명시하고 반복되는 평면
그래프도 접지 않고 항상 표시합니다. Target과 trajectory를 같은 centerline에서 만든
local consistency benchmark는 거의 100%가 의도된 결과입니다. 실제 알고리즘 평가는
독립적으로 만든 Target과 trajectory로 수행해야 합니다.

### 산출물

결과 파일 영역은 데스크톱에서 전체 폭의 3열 카드로 핵심 JSON·CSV·보고서·로그를
표시하며, 태블릿에서는 2열, 모바일에서는 1열로 바뀝니다. 정적 PNG는 생성하지
않습니다. `deposited.stl`과 Replay는 별도 카드에서 예상 시간·용량을 확인한 뒤 하나씩
주문 생성합니다. 생성된 Replay는 이 탭의 확장된 가로 영역에 표시되며, 화면 높이에
맞춰 기존보다 큰 3D·XY 화면을 제공합니다.

## Replay를 나중에 생성하기

기본 Validation에는 `replay.html`이 없습니다. `산출물` 탭에서 만듭니다.

1. frame 간격을 입력합니다.
2. 예상 frame 수, 생성 시간 범위와 파일 크기 범위를 확인합니다.
3. `Replay 생성`을 누릅니다.
4. 별도 process가 끝나면 같은 탭에서 Replay를 표시합니다. Replay는 3D 장면과
   실제 축척 XY Capsule top-view를 함께 제공하며 ARM_ENVELOPE는 적색, TCP_RADIUS는
   황색으로 구분합니다.

일반 frame 상한은 2,000개입니다. 매우 긴 작업에서는 몇 초 이상의 간격이 권장될
수 있습니다. Replay 생성 전에도 입력 signature를 다시 확인하므로 Validation 이후
원본 세 파일이 바뀌었다면 기존 결과에 Replay를 붙이지 않습니다.

`deposited.stl`도 같은 입력 지문 검사 후 별도 process에서 생성합니다. Replay와 STL은
동시에 만들지 않으며 임시 파일을 완성한 뒤 최종 파일명으로 atomic rename합니다.
기존 파일이 있으면 버튼이 `다시 생성`으로 표시됩니다.
재생성 도중 오류가 나면 이미 완성되어 있던 파일은 덮어쓰지 않으며, 상태 카드에
새 생성 시도의 실패와 기존 파일 유지 여부를 함께 표시합니다.

현재 UI는 interactive `replay.html`만 생성하며 GIF, Animated WebP, MP4 변환 기능은
포함하지 않습니다. 애니메이션 이미지가 필요하면 브라우저에서 Replay frame을 캡처한
뒤 별도 encoder로 결합해야 합니다. 긴 작업은 먼저 Replay frame 간격을 늘려 전체
프레임 수를 줄이는 것이 좋습니다.

## 결과 이후 동작

- `처음으로 돌아가기`: 입력 준비 화면으로 돌아가 폴더를 다시 확인하거나 새 폴더 지정
- `최근 결과 보기`: 현재 입력 signature와 지원하는 결과 schema가 일치하는 완료 결과가 있을 때만 표시

정상 Validation 결과에는 `validation_inputs.json` 입력 지문이 항상 기록됩니다. 기존
결과 폴더는 자동 삭제하거나 덮어쓰지 않습니다. 결과 schema `1.1`, `2.0`, `3.0`은 현재
schema `4.0` 형식이 아니므로 최근 결과로 열거나 추가 산출물을 붙이지 않고 재실행을
안내합니다.

## 문제 해결

### 입력 확인 버튼을 눌러도 진행되지 않는 것처럼 보임

큰 STL을 읽고 preview를 만드는 동안 버튼에 loading 상태가 표시됩니다. 완료 후에도
변화가 없다면 화면의 입력 오류 카드와 서버 콘솔을 확인하고, 세 고정 파일명이
정확한지 점검합니다.

### Validation 버튼이 비활성화됨

- 입력 확인 결과가 `BLOCKED`인지 확인합니다.
- 폴더 입력값을 검사 후 수정하지 않았는지 확인합니다.
- 파일을 생성 프로그램이 다시 저장해 내용 hash, size 또는 mtime이 바뀌지 않았는지 확인합니다.
- `입력 확인`을 다시 실행합니다.

### Validation 버튼을 눌러도 화면이 바뀌지 않음

서버 콘솔과 입력 카드의 실행 오류를 확인합니다. 이미 Validation 또는 추가 산출물
process가 실행 중이면 동시에 새 Validation을 시작하지 않습니다. UI를 다시 띄울
때는 기존 port가 사용 중인지 확인하고 다른 `--port`를 지정할 수 있습니다.

### 결과에 Replay가 없음

정상 동작입니다. `산출물` 탭에서 필요한 frame 간격으로 생성하십시오.

[루트 README로 돌아가기](../README.md)
