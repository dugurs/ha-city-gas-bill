# custom_components/city_gas_bill/const.py

"""
City Gas Bill 통합구성요소에서 공통적으로 사용되는 상수들을 정의하는 파일입니다.
"""
from logging import getLogger
from typing import Final

# --- 기본 상수 ---

# 이 통합구성요소의 고유한 도메인 이름입니다.
# HA 내부적으로 이 이름을 사용하여 모든 것을 식별합니다 (예: city_gas_bill.update_data 서비스).
DOMAIN: Final = "city_gas_bill"

# 로그 메시지를 기록할 때 사용할 로거(Logger) 객체입니다.
# __package__는 현재 패키지 이름(city_gas_bill)을 의미합니다.
LOGGER = getLogger(__package__)


# --- 플랫폼 정의 ---

# 이 통합구성요소가 사용하는 Home Assistant 플랫폼의 종류를 정의합니다.
SENSOR: Final = "sensor"    # 센서 (예: 총 사용요금)
NUMBER: Final = "number"    # 숫자 입력 (예: 기본요금)
BUTTON: Final = "button"    # 버튼 (예: 데이터 갱신)

# 위 플랫폼들을 리스트로 묶어서 관리합니다.
PLATFORMS: Final = [SENSOR, NUMBER, BUTTON]


# --- 설정 및 옵션 키 ---

# 사용자가 config flow (UI 설정 화면)에서 입력하는 값들의 내부적인 키 이름입니다.
CONF_PROVIDER: Final = "provider"          # 도시가스 공급사
CONF_GAS_SENSOR: Final = "gas_sensor"      # 가스 계량기 센서 엔티티 ID
CONF_READING_DAY: Final = "reading_day"    # 월 정기 검침일
CONF_READING_TIME: Final = "reading_time"  # 일일 정기 검침시간 (HH:MM)
CONF_BIMONTHLY_CYCLE: Final = "bimonthly_cycle" # 격월 요금 기능을 위한 '검침 주기' 설정 키입니다.

# --- 기본값 ---

# '기본요금' Number 엔티티의 초기 기본값입니다.
DEFAULT_BASE_FEE: Final = 1250.0


# --- 데이터 코디네이터 키 ---

# 코디네이터가 웹사이트에서 가져온 데이터를 저장할 때 사용하는 딕셔너리 키입니다.
DATA_PREV_MONTH_HEAT: Final = "prev_month_heat"    # 전월 평균열량
DATA_CURR_MONTH_HEAT: Final = "curr_month_heat"    # 당월 평균열량
DATA_PREV_MONTH_PRICE: Final = "prev_month_price"   # 전월 열량단가
DATA_CURR_MONTH_PRICE: Final = "curr_month_price"   # 당월 열량단가


# --- 센서 속성(Attribute) 키 ---

# '총 사용요금' 센서의 추가 정보(Attributes)에 표시될 내용의 키입니다.
ATTR_START_DATE: Final = "start_date"          # 이번 달 청구 시작일
ATTR_END_DATE: Final = "end_date"            # 현재 날짜 (계산 기준일)
ATTR_DAYS_TOTAL: Final = "total_days"          # 총 사용일수
ATTR_DAYS_PREV_MONTH: Final = "prev_month_days"  # 총 사용일수 중 전월에 해당하는 일수
ATTR_DAYS_CURR_MONTH: Final = "curr_month_days"  # 총 사용일수 중 당월에 해당하는 일수
ATTR_MONTHLY_GAS_USAGE: Final = "monthly_gas_usage" # 격월 센서가 '전월 총 사용요금'의 속성에서 전월 사용량 값을 가져올 때 사용하는 키

# --- 이벤트 이름 ---

# 매월 검침일에 '총 사용요금' 센서의 값을 '전월 총 사용요금'으로 이전하기 위해
# 사용하는 내부 이벤트의 이름입니다.
EVENT_BILL_RESET: Final = f"{DOMAIN}_bill_reset"