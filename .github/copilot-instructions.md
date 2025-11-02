## 목표
이 문서는 AI 코딩 에이전트(예: Copilot, 자동화된 PR 작성자)가 이 리포지토리에서 빠르게 생산적일 수 있도록
프로젝트 구조, 핵심 아키텍처, 개발 패턴, 통합 지점 및 예제를 압축해 제공합니다.

## 한 문장 요약
`custom_components/city_gas_bill` 안의 Home Assistant 커스텀 통합입니다. 주요 흐름은: Provider(스크래퍼 또는 수동) → Coordinator(데이터 수집) → Billing 계산기 → Sensor/Number/Button 엔티티.

## 핵심 파일 및 역할(바로 참조할 파일 경로)
- `custom_components/city_gas_bill/manifest.json`  — 통합 메타(의존 패키지: `aiohttp`, `beautifulsoup4`, `python-dateutil`).
- `custom_components/city_gas_bill/providers/__init__.py` — `AVAILABLE_PROVIDERS`를 동적으로 발견/등록합니다. (파일명 == provider id)
- `custom_components/city_gas_bill/providers/base.py` — `GasProvider` 추상 인터페이스: 반드시 `id`, `name`, `scrape_heat_data`, `scrape_price_data`를 구현해야 합니다.
- `custom_components/city_gas_bill/coordinator.py` — `CityGasDataUpdateCoordinator`: provider로부터 `scrape_*` 데이터를 가져와 한 딕셔너리로 합쳐서 센서가 사용합니다. `manual` provider는 스크래핑을 건너뜁니다.
- `custom_components/city_gas_bill/billing.py` — `GasBillCalculator`: 전월/당월 분할, 격월 집계, 최종 요금 계산 로직이 중앙에 모여 있습니다.
- `custom_components/city_gas_bill/sensor.py` — 센서 엔티티 구현. `number` 엔티티 ID(예: `{entry_id}_prev_month_heat`)와의 강한 결합 패턴이 있으니 참고.
- `custom_components/city_gas_bill/config_flow.py` — UI 기반 설정 흐름. `AVAILABLE_PROVIDERS`로 프로바이더 드롭다운을 구성합니다.
- `custom_components/city_gas_bill/services.yaml` — 서비스 정의: `city_gas_bill.update_data`.

## 아키텍처 & 데이터 흐름 (짧게)
1. 설정에서 선택한 provider id(예: `seoul_gas`)가 `AVAILABLE_PROVIDERS`에서 조회됩니다.
2. `CityGasDataUpdateCoordinator`는 provider 인스턴스(`GasProvider`)에 `websession`을 주입하고 주기(또는 수동 서비스 호출)에 따라 `scrape_heat_data()`와 `scrape_price_data()`를 호출합니다.
3. 성공적으로 수집된 데이터는 coordinator의 `data`로 병합되어 `sensor` 플랫폼이 사용합니다.
4. 소비자: `sensor.TotalBillSensor` 등은 `GasBillCalculator`를 사용해 보정계수/일할 계산/세금(10%)까지 적용한 최종 요금을 계산합니다.

## 프로젝트-특화 규칙 / 중요한 구현 디테일
- Provider 파일명(예: `seoul_gas.py`)은 provider의 ID로 사용됩니다. `providers/__init__.py`는 디렉토리 내 `*.py`를 동적으로 import 하여 `AVAILABLE_PROVIDERS`를 빌드합니다.
- `GasProvider`는 네 가지 멤버를 반드시 구현합니다: `id`, `name`, `scrape_heat_data()`, `scrape_price_data()`.
- `coordinator.py`는 `manual` provider를 특별 처리: 스크래핑을 하지 않고 빈 dict 또는 None을 반환하여 사용자가 `number` 엔티티에 수동값을 유지하도록 합니다.
- 센서-숫자(entities) 매핑: `sensor.py`에서 `number` 엔티티 id들을 `ent_reg.async_get_entity_id('number', DOMAIN, f"{entry.entry_id}_prev_month_heat")` 형태로 조회합니다. 새 필드를 추가할 때는 이 패턴을 유지하세요.
- 검침 리셋 로직: `sensor.TotalBillSensor._check_and_reset_on_reading_day()`가 `reading_day`와 `reading_time`을 동시에 만족할 때 전월 요금 이관과 `number` 엔티티(`monthly_start_reading`) 재설정을 수행합니다.
- 단위/타입: 가스 사용량은 m³, 열량은 MJ/Nm³, 단가는 KRW/MJ, 최종 요금은 KRW(정수)입니다.

## 예제: 새로운 공급사 추가(구현 템플릿)
1. `custom_components/city_gas_bill/providers/new_provider.py` 생성
2. `from .base import GasProvider` 상속
3. 구현해야 할 것:
   - `@property def id(self) -> str: return 'new_provider'` (파일명과 일치)
   - `@property def name(self) -> str: return 'New Gas Co.'`
   - `async def scrape_heat_data(self) -> dict | None:` → `{ 'prev_month_heat': float, 'curr_month_heat': float }` 또는 `None`
   - `async def scrape_price_data(self) -> dict | None:` → `{ 'prev_month_price': float, 'curr_month_price': float }` 또는 `None`

## 개발자 워크플로(간단한 안내)
- 의존성: `manifest.json`의 `requirements`를 참고하세요 (`aiohttp`, `beautifulsoup4`, `python-dateutil`). 개발 환경에서 설치하려면 가상환경을 만들고 pip로 설치하세요.
  PowerShell 예시:
  ```powershell
  python -m venv .venv; .\.venv\Scripts\Activate.ps1
  pip install aiohttp beautifulsoup4 python-dateutil
  ```
- Home Assistant에서 로컬 테스트: `custom_components/city_gas_bill` 폴더를 HA `config/custom_components/`에 복사한 뒤 HA 재시작(개별적 명령은 환경마다 다름).
- 디버깅: 로그는 `const.LOGGER`를 사용합니다. HA의 `logger` 설정에서 `custom_components.city_gas_bill`을 `debug`로 설정하면 상세 로그를 확인할 수 있습니다.

## 주의점 / 금지된 가정
- 외부 네트워크 호출은 provider 구현에 의존합니다. 스크래핑 로직은 타깃 웹사이트의 변경에 취약하므로 에러 처리를 꼼꼼히 유지하세요.
- `providers/__init__.py`가 모듈을 동적으로 로드하므로, 새 파일의 문법 오류는 통합 로드 실패로 이어집니다.
- provider의 `scrape_*`가 `None`을 반환하면 coordinator는 업데이트 실패로 처리하지 않고(특히 `manual`) 기존 `number` 엔티티를 덮어쓰지 않습니다.

## 빠른 참고(중요 경로 요약)
- Provider 구현: `custom_components/city_gas_bill/providers/*.py`
- Coordinator: `custom_components/city_gas_bill/coordinator.py`
- 계산기: `custom_components/city_gas_bill/billing.py`
- 주요 엔티티/플랫폼: `custom_components/city_gas_bill/sensor.py`, `number.py`, `button.py`
- 설정 흐름: `custom_components/city_gas_bill/config_flow.py`

피드백 요청: 이 파일에서 더 상세히 문서화했으면 하는 부분(예: 로컬 디버깅 단계, 테스트 스크립트, CI 규칙)이 있으면 알려주세요.
