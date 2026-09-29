# 설치 및 시작하기

## 요구 사항

- Python 3.11 이상
- Windows 10/11, Linux 또는 macOS
- 입력 한 건당 `config.yaml`, `trajectory.csv`, `target.stl`
- 대형 STL과 trajectory를 처리할 수 있는 충분한 메모리와 디스크 공간

Windows에서 로컬 UI의 `찾아보기` 버튼은 `tkinter` helper를 사용합니다. 해당 기능을
사용할 수 없는 환경에서도 폴더 경로를 직접 붙여 넣어 실행할 수 있습니다.

## 설치

### Windows PowerShell

```powershell
cd C:\Github\WAAM_Validator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

PowerShell 실행 정책 때문에 활성화가 차단되면 현재 프로세스에서만 정책을 바꾼 후
다시 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

활성화 없이도 가상환경의 실행 파일을 직접 사용할 수 있습니다.

```powershell
.\.venv\Scripts\waam-validator.exe --help
```

### Linux/macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

`requirements.lock`은 애플리케이션과 개발 도구를 포함한 전체 해석 의존성을 고정한
파일입니다. `pip install -e . --no-deps`는 현재 source tree를 editable package로
연결하되 이미 설치한 lock 버전을 바꾸지 않습니다.

## 입력 폴더 만들기

가장 작은 작업 구조는 다음과 같습니다.

```text
my_job/
├── config.yaml
├── trajectory.csv
└── target.stl
```

샘플 설정은 [examples/sample_job/config.yaml](../examples/sample_job/config.yaml)을
복사해 작업 조건에 맞게 수정할 수 있습니다. 입력 파일을 생성하는 프로그램은
[입력물 인터페이스](WAAM_Validator_입력물_인터페이스.md)의 정렬, 단위, mode,
시간 경계 조건을 따라야 합니다.

## 첫 실행

먼저 전체 계산보다 빠른 입력 검사를 실행합니다.

```powershell
waam-validator check C:\data\my_job
```

성공하면 세 입력 파일의 상태와 trajectory 행 수가 출력됩니다. 이 검사는 다음을
수행합니다.

- 고정 파일명과 Config 필드·타입 확인
- CSV header, 타입, robot ID, 시간 순서와 mode 의미 검사
- Deposition/Travel/Wait 구간의 layer, workspace, 정지·속도 규칙 검사
- Target STL 로딩, watertight 설정과 좌표 범위 일관성 확인

충돌 sample 생성, Target layer slicing, 형상 비교, 결과 파일 쓰기는 하지 않습니다.
일부 속도·Wait·XY Reach 문제는 입력 파싱 오류가 아니라 실행 가능한 경고 또는 예상
`FAIL`이므로 `check` 자체는 통과할 수 있습니다.

전체 Validation은 다음과 같이 실행합니다.

```powershell
waam-validator run C:\data\my_job
```

콘솔에 Schedule, XY Reach, Collision, Shape, Failure Reasons와 결과 폴더가 표시됩니다.
기본 출력은 `C:\data\my_job\output\<timestamp>\`에 새로 생성됩니다.

## 실행 옵션

### 폐기 예정 호환 옵션

```powershell
waam-validator run C:\data\my_job --headless
waam-validator run C:\data\my_job --replay
```

`--headless`와 `--replay`는 예전 호출을 즉시 깨뜨리지 않기 위해서만 받습니다.
둘 다 현재 기본 경량 결과를 바꾸지 않으며 폐기 안내가 stderr에 출력됩니다.
Replay는 UI 결과 화면에서 생성합니다.

### JSON stdout

```powershell
waam-validator run C:\data\my_job --json
```

계산 가능한 PASS/FAIL 실행에서는 stdout을 한 개의 압축 JSON 객체로 제한합니다.
파일 생성 동작은 일반 실행과 동일합니다. 치명 오류는 stderr의 오류 블록과 종료
코드로 전달됩니다.

### 출력 경로 지정

```powershell
waam-validator run C:\data\my_job --output C:\results\my_job_run_001
```

지정 경로를 정확히 사용합니다. 폴더가 없으면 생성하지만, 이미 파일이 들어 있는
경로에는 덮어쓰지 않고 출력 오류(종료 코드 `5`)로 중단합니다.

## UI 실행

```powershell
waam-validator ui C:\data\my_job
waam-validator ui C:\data\my_job --port 8051
waam-validator ui C:\data\my_job --no-browser
```

기본 host는 `127.0.0.1`, port는 `8050`입니다. 다른 입력으로 바꾸려면 화면에서
폴더를 선택하고 `입력 확인`을 다시 실행합니다. 자세한 화면 흐름은
[UI 사용 안내](ui-guide.md)를 참고하십시오.

## 결과 확인 순서

1. 프로세스 종료 코드가 `0`인지 `1`인지 확인합니다.
2. `summary.json`의 `status`와 `failure_reasons`를 확인합니다.
3. 실패 영역에 따라 `robot_metrics.csv`, `collision_events.csv`,
   `layer_metrics.csv`를 확인합니다.
4. 경고와 비치명 위반은 `summary.json.issues`, 계산 맥락은 `run.log`에서 확인합니다.
5. 필요하면 UI에서 `deposited.stl`이나 Replay를 주문 생성합니다.

자세한 필드 설명은 [결과 및 산출물 참조](results-reference.md)에 있습니다.

## 흔한 문제

| 증상 | 확인 사항 |
| --- | --- |
| `waam-validator` 명령을 찾지 못함 | 가상환경 활성화 또는 editable install 여부 |
| `schema_version` 오류 | Config에는 이 필드를 사용하지 않으므로 해당 행을 제거했는지 |
| 입력 확인 후 실행 버튼 비활성 | 입력이 BLOCKED인지, 검사 후 파일 내용·크기·수정 시각이 바뀌었는지 |
| UI가 열리지 않음 | port 사용 여부, `--port` 변경, 출력된 URL 직접 접속 |
| `FAIL`인데 결과 파일이 있음 | 정상 동작. 계산 가능한 기준 위반은 결과를 저장하고 종료 코드 1 반환 |
| Replay가 없음 | 기본 미생성. UI의 `산출물` 탭에서 별도 생성 |
| Explicit output directory 오류 | `--output` 대상이 비어 있지 않음 |

[README로 돌아가기](../README.md)
