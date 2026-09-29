# 버전 및 호환성

## 현재 버전

현재 WAAM Validator 애플리케이션 버전은 **1.0.1**입니다. 버전의 단일 원본은
[`src/waam_validator/_version.py`](../src/waam_validator/_version.py)이며 다음 위치가
이 값을 공유합니다.

- Python package metadata
- `waam_validator.__version__`
- 로컬 UI 상단
- `summary.json`과 `error.json`의 `validator_version`
- `validation_report.md`와 `run.log`

`pyproject.toml`은 이 파일을 동적으로 읽으므로 두 파일에 같은 버전을 중복해서
적지 않습니다.

## 세 종류의 버전 개념

| 구분 | 현재 값 | 역할 |
| --- | --- | --- |
| WAAM Validator 애플리케이션 | `1.0.0` | 설치된 코드와 검증 알고리즘 릴리스 식별 |
| `config.yaml` | 버전 없음 | 현재 애플리케이션의 엄격한 Config 모델로 직접 검증 |
| 결과 JSON schema | `4.0` | XY Reach 의미와 명시적 XY metric 필드를 포함한 JSON 형식 식별 |

Config에는 `schema_version`을 작성하지 않습니다. 필수 필드 누락과 알 수 없는 필드는
오류이며, Config 항목의 정확한 목록은 [Config 참조](config-reference.md)를 기준으로
합니다. 결과의 `schema_version`은 Config 버전이 아니라 결과를 읽는 프로그램을 위한
형식 버전입니다.

결과 schema `1.1`, `2.0`, `3.0`과 구형 `check_arm_crossing`, `reach_radius_mm` 또는
`output` 블록이 있는 Config는 자동 변환하지 않습니다. 현재 UI와 주문 생성 worker는 schema `4.0` 결과만
지원합니다. 기존 입력은 현재 Config 참조에 맞춘 뒤 다시 Validation해야 합니다.

## 버전 변경 기준

- 기존 입력·공개 API·결과 해석과 호환되지 않는 변경: 애플리케이션 major 변경
- 기존 사용법을 유지하는 기능 추가: 애플리케이션 minor 변경
- 호환되는 버그 수정이 별도 릴리스 식별을 필요로 하는 경우: patch 번호 추가 가능
- 결과 JSON 필드의 제거·의미 변경: 애플리케이션 버전과 별도로 결과 schema 변경
- Config 필드 변경: Config 참조, 공개 예제, 로컬 regression 입력과 입력물 인터페이스를 함께 변경

## 릴리스 점검

1. `_version.py` 한 곳의 버전을 변경합니다.
2. README, 변경된 세부 문서와 예제 Config를 갱신합니다.
3. 전체 pytest, Ruff, strict mypy와 `pip check`를 실행합니다.
4. editable 설치 후 package metadata와 runtime 버전이 같은지 확인합니다.
5. 공개 sample job과 별도 로컬 regression 입력으로 UI 입력 확인·Validation·결과 전환을 smoke test합니다.

```powershell
python -m pip install -e . --no-deps
python -c "import importlib.metadata as m, waam_validator; print(m.version('waam-validator'), waam_validator.__version__)"
```

[루트 README로 돌아가기](../README.md)
