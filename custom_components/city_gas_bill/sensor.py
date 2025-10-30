# custom_components/city_gas_bill/sensor.py

"""
City Gas Bill 통합구성요소의 센서(Sensor) 플랫폼 파일입니다.
실제 가스 요금 계산 로직과 다양한 정보(사용량, 예상요금 등)를 제공하는 센서들을 정의합니다.
"""
from __future__ import annotations
from datetime import date, timedelta, datetime
import calendar

from dateutil.relativedelta import relativedelta

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback, Event
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN, LOGGER, CONF_GAS_SENSOR, CONF_READING_DAY, ATTR_START_DATE, 
    ATTR_END_DATE, ATTR_DAYS_TOTAL, ATTR_DAYS_PREV_MONTH, ATTR_DAYS_CURR_MONTH,
    EVENT_BILL_RESET, CONF_PROVIDER
)
from .coordinator import CityGasDataUpdateCoordinator
from .providers import AVAILABLE_PROVIDERS

def _get_last_reading_date(today: date, reading_day: int) -> date:
    """
    오늘 날짜와 설정된 검침일을 기준으로 '지난번 검침일'을 계산합니다.
    검침일이 '말일(0)'인 경우 매월 마지막 날을 기준으로 계산합니다.
    """
    if reading_day == 0:
        day = calendar.monthrange(today.year, today.month)[1]
        # 오늘이 말일이면 오늘이 검침일
        if today.day == day: return today
        # 아니면 지난달 말일이 지난번 검침일
        last_month = today - relativedelta(months=1)
        return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
    
    # 오늘 날짜가 검침일보다 같거나 크면, 이번 달의 검침일이 지난번 검침일
    if today.day >= reading_day: return today.replace(day=reading_day)
    # 오늘 날짜가 검침일보다 작으면, 지난달의 검침일이 지난번 검침일
    return (today - relativedelta(months=1)).replace(day=reading_day)

def _get_next_reading_date(start_date: date, reading_day: int) -> date:
    """
    검침 시작일을 기준으로 '다음번 검침일'을 계산합니다.
    """
    next_month = start_date + relativedelta(months=1)
    if reading_day == 0:
        return next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1])
    return next_month.replace(day=reading_day)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Sensor 플랫폼을 설정합니다.
    필요한 센서 엔티티들을 생성하고 등록합니다.
    """
    coordinator: CityGasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )

    # 계산에 필요한 Number 엔티티들의 ID를 미리 가져옵니다.
    ent_reg = er.async_get(hass)
    num_ids = {
        "start_reading": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_monthly_start_reading"),
        "base_fee": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_base_fee"),
        "prev_heat": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_heat"),
        "curr_heat": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_heat"),
        "prev_price": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_price"),
        "curr_price": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_price"),
        "correction_factor": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_correction_factor"),
    }
    
    # 예상 사용량 센서의 ID는 예상 요금 센서에서 참조하기 위해 미리 정의합니다.
    usage_sensor_id = f"{entry.entry_id}_estimated_monthly_usage"

    sensors = [
        MonthlyGasUsageSensor(hass, entry, device_info, num_ids.get("start_reading")),
        TotalBillSensor(hass, entry, device_info, num_ids),
        EstimatedUsageSensor(hass, entry, device_info, num_ids.get("start_reading")),
        EstimatedBillSensor(hass, entry, device_info, num_ids, usage_sensor_id),
        PreviousMonthBillSensor(hass, entry, device_info),
        LastScrapTimeSensor(coordinator, device_info),
    ]
    async_add_entities(sensors, True)

# --- 각 센서 클래스 정의 ---

class MonthlyGasUsageSensor(SensorEntity):
    """이번 달 누적 가스 사용량을 보여주는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "monthly_gas_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, start_reading_entity_id: str | None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._start_reading_id = start_reading_entity_id
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0.0
        
    async def async_added_to_hass(self) -> None:
        """센서가 추가되면 관련 엔티티들의 상태 변화를 추적합니다."""
        await super().async_added_to_hass()
        if not self._start_reading_id: return
        # 실제 가스 센서나 시작 검침값 엔티티가 변경되면 이 센서도 업데이트합니다.
        self.async_on_remove(async_track_state_change_event(self.hass, [self._gas_sensor_id, self._start_reading_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
        
    @callback
    def _handle_state_change(self, event) -> None:
        """상태 변화 이벤트 핸들러"""
        self.async_schedule_update_ha_state(True)
        
    async def async_update(self) -> None:
        """현재 가스 사용량을 계산하여 업데이트합니다."""
        if not self._start_reading_id: self._attr_native_value = None; return
        current_reading_state = self.hass.states.get(self._gas_sensor_id)
        start_reading_state = self.hass.states.get(self._start_reading_id)
        
        # 필요한 엔티티들의 상태가 유효하지 않으면 값을 표시하지 않습니다.
        if (not current_reading_state or current_reading_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or 
            not start_reading_state or start_reading_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
            self._attr_native_value = None
            return
            
        try:
            current_reading = float(current_reading_state.state)
            start_reading = float(start_reading_state.state)
            # 사용량 = 현재값 - 시작값
            usage = current_reading - start_reading
            # 사용량이 음수가 되면 0으로 표시합니다.
            self._attr_native_value = round(usage, 2) if usage >= 0 else 0
        except (ValueError, TypeError):
            self._attr_native_value = None

class TotalBillSensor(SensorEntity):
    """현재까지의 총 가스 요금을 계산하여 보여주는 핵심 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY # 통화 기호(₩) 표시를 위해 설정
    _attr_state_class = SensorStateClass.TOTAL
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, number_entity_ids: dict) -> None:
        self.hass = hass
        self._entry = entry
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._number_ids = number_entity_ids
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._last_reset_day: date | None = None # 중복 리셋 방지를 위한 마지막 리셋 날짜 저장
        self._attr_extra_state_attributes = {}
        self._attr_native_value = 0
        
    async def async_added_to_hass(self) -> None:
        """요금 계산에 관련된 모든 엔티티를 추적합니다."""
        await super().async_added_to_hass()
        entities_to_track = [self._gas_sensor_id] + [eid for eid in self._number_ids.values() if eid is not None]
        if not all(self._number_ids.values()): return
        self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
        
    @callback
    def _handle_state_change(self, event) -> None:
        self.async_schedule_update_ha_state(True)
        
    async def async_update(self) -> None:
        """요금을 계산하는 메인 함수를 호출합니다."""
        await self._calculate_bill()
        
    async def _check_and_reset_on_reading_day(self) -> None:
        """오늘이 검침일인지 확인하고, 맞다면 요금을 리셋하는 로직입니다."""
        start_reading_id = self._number_ids.get("start_reading")
        if not start_reading_id: return
        
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        
        # 설정된 검침일과 오늘 날짜가 일치하는지 확인합니다.
        is_reading_day = (
            (reading_day_config == 0 and today.day == calendar.monthrange(today.year, today.month)[1]) or 
            (reading_day_config != 0 and today.day == reading_day_config)
        )
        
        # 오늘이 검침일이고, 아직 리셋하지 않았다면 리셋 절차를 진행합니다.
        if is_reading_day and self._last_reset_day != today:
            LOGGER.info("검침일이 되어 요금 리셋을 진행합니다.")
            # 현재 요금 정보를 이벤트로 전송하여 '전월 요금 센서'가 저장하도록 합니다.
            self.hass.bus.async_fire(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", {
                "state": self.native_value,
                "attributes": self.extra_state_attributes,
            })
            
            current_reading_state = self.hass.states.get(self._gas_sensor_id)
            if current_reading_state and current_reading_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    # --- FIX: 리셋 시 소수점 버림 적용 ---
                    # 현재 가스 계량기 값을 읽어와 정수로 변환(소수점 버림) 후 새로운 시작값으로 설정합니다.
                    new_start_value = int(float(current_reading_state.state))
                    await self.hass.services.async_call(
                        "number", "set_value", 
                        {"entity_id": start_reading_id, "value": float(new_start_value)}, 
                        blocking=True
                    )
                    self._last_reset_day = today # 오늘 리셋했음을 기록
                    LOGGER.info("새로운 월 검침 시작값을 %s로 설정했습니다.", new_start_value)
                except (ValueError, TypeError):
                    LOGGER.error("가스 센서 값을 읽을 수 없어 시작값 리셋에 실패했습니다.")

    async def _calculate_bill(self) -> None:
        """실제 가스 요금을 계산하는 핵심 로직입니다."""
        # 먼저 오늘이 리셋 날짜인지 확인합니다.
        await self._check_and_reset_on_reading_day()
        
        if not all(self._number_ids.values()): self._attr_native_value = None; return
        
        try:
            # 계산에 필요한 모든 값을 엔티티에서 가져옵니다.
            current_reading = float(self.hass.states.get(self._gas_sensor_id).state)
            start_reading = float(self.hass.states.get(self._number_ids["start_reading"]).state)
            base_fee = float(self.hass.states.get(self._number_ids["base_fee"]).state)
            prev_heat = float(self.hass.states.get(self._number_ids["prev_heat"]).state)
            curr_heat = float(self.hass.states.get(self._number_ids["curr_heat"]).state)
            prev_price = float(self.hass.states.get(self._number_ids["prev_price"]).state)
            curr_price = float(self.hass.states.get(self._number_ids["curr_price"]).state)
            correction_factor = float(self.hass.states.get(self._number_ids["correction_factor"]).state)
        except (ValueError, TypeError, KeyError, AttributeError):
            # 하나라도 값을 가져오지 못하면 계산을 중단합니다.
            self._attr_native_value = None
            return
        
        # 1. 계량기 사용량 계산
        monthly_usage = current_reading - start_reading
        if monthly_usage < 0: monthly_usage = 0
        
        # 2. 온압보정계수를 적용한 '보정 사용량' 계산
        corrected_monthly_usage = monthly_usage * correction_factor

        # 3. 사용 기간 및 일할 계산을 위한 일수 산정
        today = date.today()
        start_of_period = _get_last_reading_date(today, self._config[CONF_READING_DAY])
        
        prev_month_days, curr_month_days = 0, 0
        
        # 오늘이 검침 시작일과 같거나 이후인 경우에만 기간을 계산합니다.
        if today >= start_of_period:
            first_day_of_curr_month = today.replace(day=1)

            # 검침 시작일이 이번 달 1일보다 이전이면, 지난달에 포함된 기간이 있음
            if start_of_period < first_day_of_curr_month:
                last_day_of_prev_month = first_day_of_curr_month - timedelta(days=1)
                # 지난달 일수 = (지난달 말일 - 검침 시작일) + 1일
                prev_month_days = (last_day_of_prev_month - start_of_period).days + 1
            
            # 이번 달 일수 = (오늘 - 이번 달 시작일(또는 검침 시작일)) + 1일
            curr_month_start = max(start_of_period, first_day_of_curr_month)
            curr_month_days = (today - curr_month_start).days + 1

        # 총 사용일수 합계
        total_days_for_ratio = prev_month_days + curr_month_days

        # 아직 사용 기간이 하루도 안 지났으면 기본요금(부가세 포함)만 표시
        if total_days_for_ratio <= 0:
            self._attr_native_value = round(base_fee * 1.1)
            self._attr_extra_state_attributes = {ATTR_START_DATE: start_of_period.isoformat(), ATTR_END_DATE: today.isoformat(), ATTR_DAYS_TOTAL: 0}
            return

        # 4. 사용량을 기간 비율에 따라 '전월분'과 '당월분'으로 배분 (일할 계산)
        prev_month_usage = corrected_monthly_usage * (prev_month_days / total_days_for_ratio)
        curr_month_usage = corrected_monthly_usage * (curr_month_days / total_days_for_ratio)
        
        # 5. 각 월별 단가와 열량을 적용하여 요금 계산
        prev_month_fee = prev_month_usage * prev_heat * prev_price
        curr_month_fee = curr_month_usage * curr_heat * curr_price
        
        # 6. 최종 요금 합산 (기본요금 + 사용요금) 및 부가세(10%) 적용
        total_fee = (base_fee + prev_month_fee + curr_month_fee) * 1.1
        
        self._attr_native_value = round(total_fee) # 최종 요금은 반올림하여 정수로 표시
        
        # 디버깅 및 정보 제공을 위한 추가 속성 저장
        self._attr_extra_state_attributes = {
            ATTR_START_DATE: start_of_period.isoformat(),
            ATTR_END_DATE: today.isoformat(),
            ATTR_DAYS_TOTAL: total_days_for_ratio,
            ATTR_DAYS_PREV_MONTH: prev_month_days,
            ATTR_DAYS_CURR_MONTH: curr_month_days,
            "base_fee": base_fee,
            "monthly_gas_usage": round(monthly_usage, 2),
            "correction_factor": correction_factor,
            "corrected_monthly_usage": round(corrected_monthly_usage, 2),
            "prev_month_calculated_fee": round(prev_month_fee),
            "curr_month_calculated_fee": round(curr_month_fee)
        }

class EstimatedUsageSensor(SensorEntity):
    """현재 사용 추세를 기반으로 이번 달 총 예상 사용량을 계산하는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "estimated_monthly_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, start_reading_entity_id: str | None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._start_reading_id = start_reading_entity_id
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0.0
        
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._start_reading_id: return
        self.async_on_remove(async_track_state_change_event(self.hass, [self._gas_sensor_id, self._start_reading_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
        
    @callback
    def _handle_state_change(self, event) -> None:
        self.async_schedule_update_ha_state(True)
        
    async def async_update(self) -> None:
        """예상 사용량을 계산하여 업데이트합니다."""
        if not self._start_reading_id: self._attr_native_value = None; return
        try:
            current_reading = float(self.hass.states.get(self._gas_sensor_id).state)
            start_reading = float(self.hass.states.get(self._start_reading_id).state)
            current_usage = current_reading - start_reading
            if current_usage < 0: current_usage = 0
        except (ValueError, TypeError, AttributeError):
            self._attr_native_value = None; return
            
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        start_of_period = _get_last_reading_date(today, reading_day_config)
        next_reading_day = _get_next_reading_date(start_of_period, reading_day_config)
        
        # 현재까지 경과한 일수
        days_passed = (today - start_of_period).days
        # 이번 달 전체 일수
        total_days_in_period = (next_reading_day - start_of_period).days
        
        # 경과 일수가 없거나 전체 일수가 이상하면 현재 사용량을 그대로 표시
        if days_passed <= 0 or total_days_in_period <= 0:
            self._attr_native_value = round(current_usage, 2)
            return
            
        # 일평균 사용량 = 현재 사용량 / 경과 일수
        daily_avg_usage = current_usage / days_passed
        # 예상 총 사용량 = 일평균 사용량 * 전체 일수
        estimated_usage = daily_avg_usage * total_days_in_period
        self._attr_native_value = round(estimated_usage, 2)

class EstimatedBillSensor(SensorEntity):
    """예상 사용량을 바탕으로 이번 달 총 예상 요금을 계산하는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "estimated_total_bill"
    _attr_native_unit_of_measurement = "KRW"
    # --- FIX: 통화 단위 표시 ---
    # SensorDeviceClass.MONETARY를 사용하여 UI에서 금액 앞에 '₩' 기호가 붙도록 합니다.
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-clock"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, number_entity_ids: dict, estimated_usage_unique_id: str | None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._number_ids = number_entity_ids
        self._estimated_usage_unique_id = estimated_usage_unique_id
        self._estimated_usage_id: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0
        
    async def async_added_to_hass(self) -> None:
        """예상 사용량 센서와 설정값 엔티티들을 추적합니다."""
        await super().async_added_to_hass()
        ent_reg = er.async_get(self.hass)
        # 예상 사용량 센서의 실제 entity_id를 찾습니다.
        self._estimated_usage_id = ent_reg.async_get_entity_id("sensor", DOMAIN, self._estimated_usage_unique_id)
        
        entities_to_track = [self._estimated_usage_id] + [eid for eid in self._number_ids.values() if eid is not None]
        if not all(self._number_ids.values()) or not self._estimated_usage_id: return
        self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
        
    @callback
    def _handle_state_change(self, event) -> None:
        self.async_schedule_update_ha_state(True)
        
    async def async_update(self) -> None:
        """예상 요금을 계산하여 업데이트합니다."""
        if not all(self._number_ids.values()) or not self._estimated_usage_id: self._attr_native_value = None; return
        try:
            # 예상 사용량 센서에서 예상 총 사용량을 가져옵니다.
            estimated_usage = float(self.hass.states.get(self._estimated_usage_id).state)
            # 나머지 요금 계산에 필요한 값들을 가져옵니다.
            base_fee = float(self.hass.states.get(self._number_ids["base_fee"]).state)
            prev_heat = float(self.hass.states.get(self._number_ids["prev_heat"]).state)
            curr_heat = float(self.hass.states.get(self._number_ids["curr_heat"]).state)
            prev_price = float(self.hass.states.get(self._number_ids["prev_price"]).state)
            curr_price = float(self.hass.states.get(self._number_ids["curr_price"]).state)
            correction_factor = float(self.hass.states.get(self._number_ids["correction_factor"]).state)
        except (ValueError, TypeError, KeyError, AttributeError):
            self._attr_native_value = None; return

        # 예상 사용량에도 온압보정계수를 적용합니다.
        corrected_estimated_usage = estimated_usage * correction_factor

        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        start_of_period = _get_last_reading_date(today, reading_day_config)
        end_of_period = _get_next_reading_date(start_of_period, reading_day_config)
        
        # 이번 달 전체 청구 기간 일수
        total_days = (end_of_period - start_of_period).days
        if total_days <= 0: 
            self._attr_native_value = round(base_fee * 1.1)
            return

        prev_month_days, curr_month_days = 0, 0
        
        # 청구 기간이 두 달에 걸쳐 있는지 확인합니다.
        if start_of_period.month != end_of_period.month:
            # 시작 월의 마지막 날짜를 구합니다.
            last_day_of_start_month = (start_of_period.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            # 이전 달에 속하는 일수
            prev_month_days = (last_day_of_start_month - start_of_period).days + 1
            # 현재 달에 속하는 일수 = 전체 일수 - 이전 달 일수
            curr_month_days = total_days - prev_month_days
        else: 
            # 청구 기간이 한 달 내에 모두 포함되면 (예: 1일~말일)
            prev_month_days = total_days
            curr_month_days = 0
        
        # 예상 사용량을 기간 비율대로 배분합니다.
        prev_month_usage = corrected_estimated_usage * (prev_month_days / total_days) if total_days > 0 else 0
        curr_month_usage = corrected_estimated_usage * (curr_month_days / total_days) if total_days > 0 else 0
        
        # 각 월별 예상 요금 계산
        prev_month_fee = prev_month_usage * prev_heat * prev_price
        curr_month_fee = curr_month_usage * curr_heat * curr_price
        
        # 최종 예상 요금 합산 (부가세 포함)
        total_fee = (base_fee + prev_month_fee + curr_month_fee) * 1.1
        self._attr_native_value = round(total_fee)

class PreviousMonthBillSensor(SensorEntity, RestoreEntity):
    """지난달 확정 요금을 저장하고 보여주는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "previous_month_total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-refund"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        
    async def async_added_to_hass(self) -> None:
        """HA 재시작 시 지난달 요금 정보를 복원하고, 리셋 이벤트를 구독합니다."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
                self._attr_extra_state_attributes = last_state.attributes
            except (ValueError, TypeError):
                self._attr_native_value = None
        # TotalBillSensor가 보내는 리셋 이벤트를 기다립니다.
        self.async_on_remove(self.hass.bus.async_listen(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", self._handle_bill_reset_event))
        
    @callback
    def _handle_bill_reset_event(self, event: Event) -> None:
        """리셋 이벤트가 발생하면 전달받은 요금 정보를 저장합니다."""
        LOGGER.debug("지난달 요금 센서가 리셋 이벤트를 수신했습니다: %s", event.data)
        self._attr_native_value = event.data.get("state")
        self._attr_extra_state_attributes = event.data.get("attributes", {})
        self.async_write_ha_state()

class LastScrapTimeSensor(CoordinatorEntity[CityGasDataUpdateCoordinator], SensorEntity):
    """마지막으로 데이터를 성공적으로 가져온 시간을 보여주는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "last_update_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:cloud-check-variant"
    
    def __init__(self, coordinator: CityGasDataUpdateCoordinator, device_info: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.translation_key}"
        
    @property
    def native_value(self) -> datetime | None:
        """코디네이터에 저장된 마지막 성공 시간을 반환합니다."""
        if self.coordinator.last_update_success:
            return self.coordinator.last_update_success_timestamp
        return None