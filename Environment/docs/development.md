# 개발자 안내

## 저장소 구조

```text
WAAM_Validator/
├── src/waam_validator/
│   ├── config/          # Pydantic Config 모델과 YAML 로딩
│   ├── trajectory/      # CSV 로딩, 의미 검사, 보간, adaptive sampling, XY Reach
│   ├── schedule/        # 원본 interval 기반 시간·거리 통계
│   ├── collision/       # 2D geometry, streaming 검사, event 병합
│   ├── shape/           # D polygon, STL slicing, 형상 지표, mesh export
│   ├── visualization/   # 주문 생성용 Plotly Replay
│   ├── reporting/       # JSON, CSV, Markdown, log와 console 출력
│   ├── dashboard/       # 단일 작업 UI와 worker(내부 경로명은 호환상 유지)
│   ├── cli.py           # Typer CLI
│   ├── _version.py      # 애플리케이션 버전의 단일 원본
│   ├── models.py        # typed runtime/result dataclass
│   ├── pipeline.py      # 전체 Validation orchestration
│   └── progress.py      # 진행 event 계약
├── scripts/             # 로컬 fixture·benchmark 입력 생성기
├── examples/sample_job/
├── docs/
├── pyproject.toml
└── requirements.lock
```

사용자 노출 명칭은 `WAAM Validator` 또는 `UI`입니다. `dashboard`는 기존 코드 이동을
피하기 위해 남긴 내부 module path이며 공개 CLI 명령은 `waam-validator ui`입니다.

## 개발 환경 설치

```powershell
cd C:\Github\WAAM_Validator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

`requirements.lock`에는 runtime과 pytest, Ruff, mypy, psutil 등 개발 도구의 해석
버전이 함께 고정되어 있습니다. `pyproject.toml`의 직접 의존성을 바꾸면 lock도 함께
갱신하고 `pip check`로 충돌을 확인합니다. GitHub Actions도 lock을 먼저 설치한 뒤
package를 `--no-deps`로 연결하므로 임의의 최신 transitive dependency를 다시 해석하지
않습니다.

## 공개 저장소와 로컬 검증 데이터

대용량 STL·trajectory와 연구용 benchmark를 포함하는 `tests/` 전체는 공개 저장소에
포함하지 않으며 `.gitignore`로 제외합니다. 공개 사용 예제는
`examples/sample_job/`에 유지합니다. 로컬 개발 환경에서는 별도로 보관한 테스트
suite와 `scripts/`의 생성기를 사용할 수 있지만, 이를 실행해 만들어진 `tests/`
내용을 커밋하지 마십시오.

GitHub Actions는 공개 저장소에 존재하는 코드만으로 Ruff, strict mypy, `pip check`와
sample job 입력 smoke check를 수행합니다. 아래 pytest 명령은 로컬 테스트 suite가
준비된 개발 환경에서만 사용합니다.

## 품질 검사

### 일반 테스트

```powershell
.\.venv\Scripts\pytest.exe -q -m "not performance"
```

`pyproject.toml`의 기본 pytest 옵션도 performance test를 제외합니다. 공개 저장소에는
대용량 fixture를 포함하지 않으므로, 로컬 suite의 보유 범위와 실제 수집된 테스트 수를
`pytest --collect-only -q`로 먼저 확인하십시오. 최소 suite는 XY Reach와 결과 기록
원자성, 입력 hash, 로봇 ID 시각화, 충돌 시간축 및 주요 UI 회귀를 검증합니다.

### 정적 검사

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m pip check
```

- Ruff target: Python 3.11, line length 100
- mypy: `strict = true`
- Shapely, Trimesh, Plotly, Dash AG Grid는 외부 typing 제약 때문에 ignore override 사용

### Performance test

```powershell
.\.venv\Scripts\pytest.exe -q -m performance
```

2026-09-07 현재 Windows Python 3.11 환경의 100,000행 synthetic 측정값은 peak RSS
약 `180 MiB`, full pipeline 약 `2.7초`, Capsule batch 100,000건 약 `0.034초`였습니다.
이는 절대 성능 보장이 아니라 회귀 비교 기준이며, 장비와 백그라운드 부하에 따라 달라집니다.

런타임은 Matplotlib, NetworkX, SciPy에 의존하지 않습니다. Target normal/body 연결은
Validator의 parity union-find로, 수평 slicing은 Trimesh의 원시 triangle-plane 선분과
Shapely loop 결합으로 처리합니다. 따라서 새 가상환경의 wheel smoke test에도 이 세 패키지가
설치되지 않은 상태에서 `check`와 `run`을 반드시 포함합니다.

대형 synthetic trajectory의 full pipeline 메모리와 실행 시간을 측정하므로 일반
회귀 테스트와 분리되어 있습니다. CI/로컬 자원이 충분할 때 명시적으로 실행합니다.

## 수동 smoke test

```powershell
waam-validator check .\examples\sample_job
waam-validator run .\examples\sample_job --json
waam-validator ui .\examples\sample_job --port 8051
```

UI에서는 입력 확인 → Validation 실행 → 결과 전환 → on-demand STL/Replay 순서를
확인합니다. 입력·결과 화면에서 network 요청이 주기적으로 발생하지 않고, worker가
실행 중일 때만 진행 interval이 활성화되는지도 확인합니다.

## 변경 시 회귀 위험

### Mode 의미

Mode는 현재 행부터 다음 행까지 적용됩니다. 거리와 시간 계산, Gantt, deposition
polygon이 모두 같은 left-row 규칙을 사용해야 합니다. 마지막 행은 `W` 종료 상태로
거리나 지속시간을 만들지 않습니다.

### 정확 통계와 sample 통계 분리

Schedule과 Deposition/Travel 거리·평균 속도는 원본 interval에서 계산해야 합니다. Adaptive
timeline은 충돌 검사용이며, 설정 해상도 변화가 schedule 통계를 바꾸면 안 됩니다.

### UI downsampling 격리

Target face와 trajectory point 제한은 preview payload에만 적용합니다. Input
inspection의 통계와 worker Validation에는 항상 원본 객체를 사용해야 합니다.

### PASS/FAIL과 ERROR 분리

계산 가능한 위반은 결과 파일을 쓴 뒤 FAIL로 반환해야 합니다. 구조·파싱·좌표,
Target, numerical, output 오류만 예외와 코드 2~5를 사용합니다. 새로운 판정 항목을
추가할 때 CLI, 결과 JSON schema, CSV, 보고서, UI, Failure Reasons와 테스트를 함께
갱신합니다.

### 결정론

- 로봇과 pair는 고정 순서로 처리합니다.
- layer index는 정렬합니다.
- collision event는 시작 시간, 종류, pair 순으로 정렬합니다.
- 반복 실행 간 JSON/CSV의 field·row 순서를 유지합니다.
- 기하 fallback/downsampling은 같은 입력에 같은 선택을 해야 합니다.

### 비파괴 출력

기본 run은 항상 새 timestamp 폴더를 만들고 explicit non-empty output은 거부합니다.
테스트 cleanup에서도 저장소나 사용자 입력 폴더 전체를 대상으로 한 재귀 삭제를
사용하지 마십시오.

Worker가 강제 종료되면 `.waam_state/validation-status.json`만 있는 미완성 output 폴더가 남을
수 있습니다. 결과 선택 로직은 `summary.json` 또는 `error.json`이 있는 완료 디렉터리만
사용합니다. 미완성 폴더는 자동 삭제하지 않으며 사용자가 경로를 확인한 뒤 정리합니다.

## 코드 변경 점검표

- [ ] 공개 API·동작 변경에 맞게 `src/waam_validator/_version.py`의 애플리케이션 버전을 조정했다.
- [ ] `README.md`와 관련 `docs/` 문서를 갱신했다.
- [ ] synthetic unit test와 필요한 integration regression을 추가했다.
- [ ] PASS/FAIL, error code와 Failure Reasons 순서를 확인했다.
- [ ] UI preview가 대형 입력에서도 bounded payload를 유지한다.
- [ ] `pytest`, Ruff, strict mypy, `pip check`가 통과한다.
- [ ] 의존성 변경 시 `requirements.lock`을 갱신했다.

## 관련 문서

- [검증 방법과 판정 기준](validation-method.md)
- [Python API](python-api.md)
- [결과 및 산출물 참조](results-reference.md)
- [버전 및 호환성](versioning.md)
- [입력물 인터페이스](WAAM_Validator_입력물_인터페이스.md)

[루트 README로 돌아가기](../README.md)
