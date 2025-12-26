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
CONF_PROVIDER_REGION: Final = "provider_region"  # 공급사 지역 선택을 위한 키
CONF_HEATING_TYPE: Final = "heating_type"    # 난방 타입 (주택난방, 중앙난방)
CONF_USAGE_TYPE: Final = "usage_type"      # 사용 용도 (취사전용, 난방전용, 혼합)
CONF_GAS_SENSOR: Final = "gas_sensor"      # 가스 계량기 센서 엔티티 ID
CONF_READING_DAY: Final = "reading_day"    # 월 정기 검침일
CONF_READING_TIME: Final = "reading_time"  # 일일 정기 검침시간 (HH:MM)
# --- 변경: CONF_BIMONTHLY_CYCLE -> CONF_READING_CYCLE ---
CONF_READING_CYCLE: Final = "bimonthly_cycle" # 정기 검침 주기 (매월/홀수월/짝수월) 설정 키입니다.
# --- 추가: 월패드 센서 사용 여부 (매월 1일 초기화 센서) ---
CONF_SENSOR_RESETS_MONTHLY: Final = "sensor_resets_monthly" 

# --- 기본값 ---

# '기본요금' Number 엔티티의 초기 기본값입니다.
DEFAULT_BASE_FEE: Final = 1250.0


# --- 데이터 코디네이터 키 ---

# 코디네이터가 웹사이트에서 가져온 데이터를 저장할 때 사용하는 딕셔너리 키입니다.
DATA_PREV_MONTH_HEAT: Final = "prev_month_heat"    # 전월 평균열량
DATA_CURR_MONTH_HEAT: Final = "curr_month_heat"    # 당월 평균열량
DATA_PREV_MONTH_PRICE_COOKING: Final = "prev_month_price_cooking"   # 전월 열량단가 (취사)
DATA_PREV_MONTH_PRICE_HEATING: Final = "prev_month_price_heating"   # 전월 열량단가 (난방)
DATA_CURR_MONTH_PRICE_COOKING: Final = "curr_month_price_cooking"   # 당월 열량단가 (취사)
DATA_CURR_MONTH_PRICE_HEATING: Final = "curr_month_price_heating"   # 당월 열량단가 (난방)


# --- 센서 속성(Attribute) 키 ---

# 센서의 추가 정보(Attributes)에 표시될 내용의 키입니다.
ATTR_START_DATE: Final = "start_date"
ATTR_END_DATE: Final = "end_date"
ATTR_DAYS_TOTAL: Final = "days_total"
ATTR_DAYS_PREV_MONTH: Final = "days_prev_month"
ATTR_DAYS_CURR_MONTH: Final = "days_curr_month"

# 상세 계산 정보 키
ATTR_BASE_FEE: Final = "base_fee"
ATTR_CORRECTION_FACTOR: Final = "correction_factor"
ATTR_MONTHLY_GAS_USAGE: Final = "monthly_gas_usage"
ATTR_CORRECTED_MONTHLY_USAGE: Final = "corrected_monthly_usage"
ATTR_PREV_MONTH_CALCULATED_FEE: Final = "prev_month_calculated_fee"
ATTR_CURR_MONTH_CALCULATED_FEE: Final = "curr_month_calculated_fee"
ATTR_PREV_MONTH_REDUCTION_APPLIED: Final = "prev_month_reduction_applied"
ATTR_CURR_MONTH_REDUCTION_APPLIED: Final = "curr_month_reduction_applied"
ATTR_COOKING_HEATING_BOUNDARY: Final = "cooking_heating_boundary" # 취사/난방 경계
ATTR_PREV_MONTH_COOKING_FEE: Final = "prev_month_cooking_fee" # 전월 취사용 요금
ATTR_PREV_MONTH_HEATING_FEE: Final = "prev_month_heating_fee" # 전월 난방용 요금
ATTR_CURR_MONTH_COOKING_FEE: Final = "curr_month_cooking_fee" # 당월 취사용 요금
ATTR_CURR_MONTH_HEATING_FEE: Final = "curr_month_heating_fee" # 당월 난방용 요금

# 정기(격월 등) 센서용 키
ATTR_PREVIOUS_MONTH: Final = "previous_month"
ATTR_CURRENT_MONTH: Final = "current_month"
ATTR_PREVIOUS_MONTH_ACTUAL: Final = "previous_month_actual"
ATTR_CURRENT_MONTH_ESTIMATED: Final = "current_month_estimated"
ATTR_USAGE_PREVIOUS_MONTH: Final = "usage_previous_month"
ATTR_USAGE_CURRENT_MONTH: Final = "usage_current_month"


# --- 이벤트 이름 ---

# 매월 검침일에 '총 사용요금' 센서의 값을 '전월 총 사용요금'으로 이전하기 위해
# 사용하는 내부 이벤트의 이름입니다.
EVENT_BILL_RESET: Final = f"{DOMAIN}_bill_reset"