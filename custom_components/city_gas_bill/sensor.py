# custom_components/city_gas_bill/sensor.py

"""
City Gas Bill 통합구성요소의 센서(Sensor) 플랫폼 파일입니다.
실제 가스 요금 계산 로직과 다양한 정보(사용량, 예상요금 등)를 제공하는 센서들을 정의합니다.
"""
from __future__ import annotations
from datetime import date, timedelta, datetime
import calendar
from typing import NamedTuple

from dateutil.relativedelta import relativedelta

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback, Event
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN, LOGGER, CONF_GAS_SENSOR, CONF_READING_DAY, CONF_READING_TIME,
    EVENT_BILL_RESET, CONF_PROVIDER, CONF_READING_CYCLE, CONF_USAGE_TYPE,
    CONF_SENSOR_RESETS_MONTHLY, # 추가된 옵션 키
    ATTR_START_DATE, ATTR_END_DATE, ATTR_DAYS_TOTAL, ATTR_DAYS_PREV_MONTH,
    ATTR_DAYS_CURR_MONTH, ATTR_BASE_FEE, ATTR_CORRECTION_FACTOR,
    ATTR_MONTHLY_GAS_USAGE, ATTR_CORRECTED_MONTHLY_USAGE,
    ATTR_PREV_MONTH_CALCULATED_FEE, ATTR_CURR_MONTH_CALCULATED_FEE,
    ATTR_PREV_MONTH_REDUCTION_APPLIED, ATTR_CURR_MONTH_REDUCTION_APPLIED,
    ATTR_PREVIOUS_MONTH, ATTR_CURRENT_MONTH, ATTR_PREVIOUS_MONTH_ACTUAL,
    ATTR_CURRENT_MONTH_ESTIMATED, ATTR_USAGE_PREVIOUS_MONTH, ATTR_USAGE_CURRENT_MONTH,
    ATTR_COOKING_HEATING_BOUNDARY, ATTR_PREV_MONTH_COOKING_FEE, ATTR_PREV_MONTH_HEATING_FEE,
    ATTR_CURR_MONTH_COOKING_FEE, ATTR_CURR_MONTH_HEATING_FEE
)
from .coordinator import CityGasDataUpdateCoordinator
from .billing import GasBillCalculator
from .providers import AVAILABLE_PROVIDERS

def _get_last_reading_date(today: date, reading_day: int) -> date:
    """오늘 날짜와 설정된 검침일을 기준으로 '지난번 검침일'을 계산합니다."""
    if reading_day == 0:
        day = calendar.monthrange(today.year, today.month)[1]
        if today.day == day: return today
        last_month = today - relativedelta(months=1)
        return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
    
    if today.day >= reading_day: return today.replace(day=reading_day)
    return (today - relativedelta(months=1)).replace(day=reading_day)

def _get_next_reading_date(start_date: date, reading_day: int) -> date:
    """검침 시작일을 기준으로 '다음번 검침일'을 계산합니다."""
    next_month = start_date + relativedelta(months=1)
    if reading_day == 0:
        return next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1])
    return next_month.replace(day=reading_day)

# --- START: 재사용을 위한 헬퍼 함수 및 데이터 클래스 ---

class BillConfigInputs(NamedTuple):
    """요금 계산에 필요한 설정 값들을 담는 데이터 클래스입니다."""
    base_fee: float
    prev_heat: float
    curr_heat: float
    prev_price_cooking: float
    prev_price_heating: float
    curr_price_cooking: float
    curr_price_heating: float
    correction_factor: float
    winter_reduction_fee: float
    non_winter_reduction_fee: float
    cooking_heating_boundary: float

def _get_state_as_float(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """엔티티 ID로 상태를 가져와 float으로 변환하는 공용 헬퍼 함수."""
    if not entity_id:
        return None
    state_obj = hass.states.get(entity_id)
    if state_obj and state_obj.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        try:
            return float(state_obj.state)
        except (ValueError, TypeError):
            return None
    return None

def _get_bill_config_inputs(hass: HomeAssistant, number_ids: dict) -> BillConfigInputs | None:
    """
    요금 계산에 필요한 모든 Number 엔티티의 상태를 안전하게 가져와 데이터 클래스에 담아 반환합니다.
    """
    keys = [
        "base_fee", "prev_heat", "curr_heat", "prev_price_cooking", "prev_price_heating",
        "curr_price_cooking", "curr_price_heating", "correction_factor", 
        "winter_reduction_fee", "non_winter_reduction_fee", "cooking_heating_boundary"
    ]
    
    values = [_get_state_as_float(hass, number_ids.get(key)) for key in keys]
    
    if any(v is None for v in values):
        LOGGER.debug("요금 설정 값 중 일부가 준비되지 않았습니다.")
        return None
        
    return BillConfigInputs(*values)

# --- END: 재사용을 위한 헬퍼 함수 및 데이터 클래스 ---

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Sensor 플랫폼을 설정하고 모든 센서 엔티티를 생성합니다."""
    coordinator: CityGasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    config = entry.options or entry.data
    provider_name = AVAILABLE_PROVIDERS[config[CONF_PROVIDER]](None).name

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )

    ent_reg = er.async_get(hass)
    num_ids = {
        "start_reading": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_monthly_start_reading"),
        "base_fee": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_base_fee"),
        "prev_heat": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_heat"),
        "curr_heat": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_heat"),
        "prev_price_cooking": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_price_cooking"),
        "prev_price_heating": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_price_heating"),
        "curr_price_cooking": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_price_cooking"),
        "curr_price_heating": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_price_heating"),
        "correction_factor": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_correction_factor"),
        "winter_reduction_fee": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_winter_reduction_fee"),
        "non_winter_reduction_fee": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_non_winter_reduction_fee"),
        "cooking_heating_boundary": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_cooking_heating_boundary"),
    }
    
    usage_sensor_uid = f"{entry.entry_id}_monthly_gas_usage"
    bill_sensor_uid = f"{entry.entry_id}_total_bill"
    prev_bill_sensor_uid = f"{entry.entry_id}_previous_month_total_bill"
    pre_prev_bill_sensor_uid = f"{entry.entry_id}_pre_previous_month_total_bill"
    
    estimated_usage_sensor_uid = f"{entry.entry_id}_estimated_monthly_usage"
    estimated_bill_sensor_uid = f"{entry.entry_id}_estimated_total_bill"
    periodic_bill_sensor_uid = f"{entry.entry_id}_periodic_bill"

    # --- 추가: 월패드 누적 변환 센서 (설정된 경우) ---
    virtual_sensor = None
    if config.get(CONF_SENSOR_RESETS_MONTHLY):
        # 가상의 누적 센서를 생성하고 목록에 추가합니다.
        virtual_sensor = WallpadCumulativeSensor(hass, entry, device_info)
    
    # 기본 센서 목록
    sensors = [
        # virtual_sensor가 존재하면 그것을 넘겨줍니다.
        MonthlyGasUsageSensor(hass, entry, device_info, num_ids.get("start_reading"), virtual_sensor),
        TotalBillSensor(hass, entry, device_info, num_ids, virtual_sensor),
        EstimatedUsageSensor(hass, entry, device_info, num_ids.get("start_reading"), virtual_sensor),
        EstimatedBillSensor(hass, entry, device_info, num_ids, estimated_usage_sensor_uid),
        PreviousMonthBillSensor(hass, entry, device_info),
        PrePreviousMonthBillSensor(hass, entry, device_info, prev_bill_sensor_uid),
        LastScrapTimeSensor(coordinator, device_info),
    ]
    
    if virtual_sensor:
        sensors.append(virtual_sensor)
    
    # 정기(격월/3개월) 센서 추가
    reading_cycle = config.get(CONF_READING_CYCLE, "disabled")
    if reading_cycle != "disabled":
        periodic_sensors = [
            PeriodicUsageSensor(hass, entry, device_info, usage_sensor_uid, prev_bill_sensor_uid, pre_prev_bill_sensor_uid),
            PeriodicBillSensor(hass, entry, device_info, bill_sensor_uid, prev_bill_sensor_uid, pre_prev_bill_sensor_uid),
            PreviousPeriodicBillSensor(hass, entry, device_info, periodic_bill_sensor_uid),
            EstimatedPeriodicUsageSensor(hass, entry, device_info, estimated_usage_sensor_uid, prev_bill_sensor_uid, pre_prev_bill_sensor_uid),
            EstimatedPeriodicBillSensor(hass, entry, device_info, estimated_bill_sensor_uid, prev_bill_sensor_uid, pre_prev_bill_sensor_uid)
        ]
        sensors.extend(periodic_sensors)
        
    async_add_entities(sensors, True)
    

# --- 새로운 센서 클래스: 월패드 누적 변환 센서 ---
class WallpadCumulativeSensor(SensorEntity, RestoreEntity):
    """
    매월 1일 0으로 초기화되는 월패드 센서를 계속 증가하는 누적 값으로 변환하는 가상 센서입니다.
    """
    _attr_has_entity_name = True
    _attr_translation_key = "virtual_cumulative_gas" # 번역키 필요 (ko.json 추가 권장)
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._raw_sensor_id = self._config[CONF_GAS_SENSOR]
        self._attr_unique_id = f"{entry.entry_id}_virtual_cumulative_gas"
        self._attr_device_info = device_info
        
        self._attr_native_value = 0.0
        self._offset = 0.0 # 누적 보정값
        self._last_raw_value = 0.0 # 직전 센서값
        
        # 이 센서의 업데이트를 구독할 외부 콜백 목록
        self._listeners = []

    def async_add_listener(self, callback_func):
        """외부 센서(TotalBillSensor 등)가 이 센서의 업데이트를 구독할 수 있게 합니다."""
        self._listeners.append(callback_func)

    def _notify_listeners(self):
        """구독자들에게 업데이트를 알립니다."""
        for callback_func in self._listeners:
            if callable(callback_func):
                # 안전하게 실행하기 위해 Task로 예약
                self.hass.async_create_task(callback_func())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        
        # 1. 상태 복원
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
                # 속성에서 offset, last_raw_value 복원
                self._offset = last_state.attributes.get("accumulated_offset", 0.0)
                self._last_raw_value = last_state.attributes.get("last_raw_value", 0.0)
                LOGGER.debug("가상 누적 센서 복원됨: 값=%s, 오프셋=%s, 직전값=%s", 
                             self._attr_native_value, self._offset, self._last_raw_value)
            except (ValueError, TypeError):
                LOGGER.warning("가상 누적 센서의 이전 상태를 복원할 수 없습니다.")

        # 2. 원본 센서 추적
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._raw_sensor_id], self._handle_raw_sensor_change)
        )
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_raw_sensor_change(self, event: Event) -> None:
        """원본 센서 값이 변경되면 누적값을 계산합니다."""
        new_state = event.data.get("new_state")
        if not new_state or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            new_raw_value = float(new_state.state)
        except (ValueError, TypeError):
            return

        # 리셋 감지 로직: 값이 줄어들었으면 리셋으로 간주
        # (작은 노이즈나 오차 방지를 위해 -0.1 이하로 줄어든 경우만 체크할 수도 있지만, 
        #  월패드는 보통 0으로 확실히 떨어지므로 단순 비교도 괜찮습니다.)
        if new_raw_value < self._last_raw_value:
            LOGGER.info("월패드 센서 리셋 감지: %s -> %s. 오프셋을 증가시킵니다.", self._last_raw_value, new_raw_value)
            # 리셋 직전의 값만큼 오프셋에 더해줍니다.
            # 예: 100 -> 0 이 되면, 오프셋에 100을 더함.
            # 그러면 현재 누적값 = 0 + 100 = 100 (유지됨)
            self._offset += self._last_raw_value
        
        # 새로운 누적값 계산
        self._attr_native_value = new_raw_value + self._offset
        self._last_raw_value = new_raw_value
        
        # 상태 속성 업데이트 (복원용)
        self._attr_extra_state_attributes = {
            "accumulated_offset": self._offset,
            "last_raw_value": self._last_raw_value
        }
        
        self.async_write_ha_state()
        self._notify_listeners() # 구독자들에게 알림

# --- 기본 월별 센서 클래스들 ---

class MonthlyGasUsageSensor(SensorEntity):
    """이번 달 누적 가스 사용량을 보여주는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "monthly_gas_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, start_reading_entity_id: str | None, virtual_sensor: WallpadCumulativeSensor | None = None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._start_reading_id = start_reading_entity_id
        self._virtual_sensor = virtual_sensor # 가상 센서 인스턴스
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._start_reading_id: return
        
        if self._virtual_sensor:
            # 가상 센서 모드: 가상 센서의 콜백에 등록
            self._virtual_sensor.async_add_listener(self.async_update_ha_state)
            # 시작 지침 변경(사용자 수동 수정 등)도 감지해야 함
            self.async_on_remove(async_track_state_change_event(self.hass, [self._start_reading_id], self._handle_state_change))
        else:
            # 일반 모드: 원본 센서와 시작 지침 변경 감지
            self.async_on_remove(async_track_state_change_event(self.hass, [self._gas_sensor_id, self._start_reading_id], self._handle_state_change))
            
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._start_reading_id: self._attr_native_value = None; return
        
        # 현재 지침 가져오기 (가상 센서 우선)
        if self._virtual_sensor:
            current_reading = self._virtual_sensor.native_value
        else:
            current_reading = _get_state_as_float(self.hass, self._gas_sensor_id)
            
        start_reading = _get_state_as_float(self.hass, self._start_reading_id)

        if current_reading is None or start_reading is None:
            self._attr_native_value = None
            return

        usage = current_reading - start_reading
        self._attr_native_value = round(usage, 2) if usage >= 0 else 0

class TotalBillSensor(SensorEntity):
    """현재까지의 총 가스 요금을 계산하여 보여주는 핵심 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, number_entity_ids: dict, virtual_sensor: WallpadCumulativeSensor | None = None) -> None:
        self.hass = hass
        self._entry = entry
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._number_ids = number_entity_ids
        self._virtual_sensor = virtual_sensor # 가상 센서
        self._usage_type = self._config.get(CONF_USAGE_TYPE, "combined")
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._last_reset_day: date | None = None
        self._attr_extra_state_attributes = {}
        self._attr_native_value = 0
        
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        
        # 추적할 엔티티 목록 (Number 설정값들)
        entities_to_track = [eid for eid in self._number_ids.values() if eid is not None]
        
        if self._virtual_sensor:
            # 가상 센서 모드: 가상 센서 콜백 등록 + 설정값 변경 감지
            self._virtual_sensor.async_add_listener(self.async_update_ha_state)
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        else:
            # 일반 모드: 원본 센서 + 설정값 변경 감지
            entities_to_track.append(self._gas_sensor_id)
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        
        # 시간 기반 리셋 트리거
        reading_time_str = self._config.get(CONF_READING_TIME, "00:00")
        try:
            target_time = datetime.strptime(reading_time_str, "%H:%M").time()
        except Exception:
            target_time = datetime.strptime("00:00", "%H:%M").time()
            
        self.async_on_remove(
            async_track_time_change(
                self.hass,
                self._handle_scheduled_reset,
                hour=target_time.hour,
                minute=target_time.minute,
                second=0
            )
        )
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    
    @callback
    def _handle_scheduled_reset(self, now: datetime) -> None:
        LOGGER.debug("예약된 검침 시간(%s)이 되어 리셋 로직을 확인합니다.", now)
        self.hass.async_create_task(self._check_and_reset_on_reading_day())

    async def async_update(self) -> None: await self._calculate_bill()

    def _get_current_reading(self) -> float | None:
        """현재 지침을 가져오는 내부 헬퍼 (가상/실제 분기 처리)"""
        if self._virtual_sensor:
            return self._virtual_sensor.native_value
        return _get_state_as_float(self.hass, self._gas_sensor_id)

    async def _check_and_reset_on_reading_day(self) -> None:
        start_reading_id = self._number_ids.get("start_reading")
        if not start_reading_id: return
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        
        reading_time_str = self._config.get(CONF_READING_TIME, "00:00")
        try:
            target_time = datetime.strptime(reading_time_str, "%H:%M").time()
        except Exception:
            target_time = datetime.strptime("00:00", "%H:%M").time()
            
        now_time = datetime.now().time()
        is_reading_time = (now_time.hour == target_time.hour and now_time.minute == target_time.minute)
        is_reading_day = ((reading_day_config == 0 and today.day == calendar.monthrange(today.year, today.month)[1]) or (reading_day_config != 0 and today.day == reading_day_config))
        
        if is_reading_day and is_reading_time and self._last_reset_day != today:
            LOGGER.info("검침일이 되어 요금 리셋을 진행합니다.")
            
            event_state = self.native_value
            event_attrs = self.extra_state_attributes

            config_inputs = _get_bill_config_inputs(self.hass, self._number_ids)
            current_reading = self._get_current_reading() # 수정됨
            start_reading = _get_state_as_float(self.hass, self._number_ids.get("start_reading"))

            if config_inputs and current_reading is not None and start_reading is not None:
                monthly_usage_raw = current_reading - start_reading
                if monthly_usage_raw < 0: monthly_usage_raw = 0
                monthly_usage_int = int(monthly_usage_raw)
                corrected_usage_int = monthly_usage_int * config_inputs.correction_factor
                calculator = GasBillCalculator(reading_day_config)
                total_fee_int, attrs_int = calculator.compute_total_bill_from_usage(
                    corrected_usage=corrected_usage_int,
                    base_fee=config_inputs.base_fee,
                    prev_heat=config_inputs.prev_heat,
                    curr_heat=config_inputs.curr_heat,
                    prev_price_cooking=config_inputs.prev_price_cooking,
                    prev_price_heating=config_inputs.prev_price_heating,
                    curr_price_cooking=config_inputs.curr_price_cooking,
                    curr_price_heating=config_inputs.curr_price_heating,
                    cooking_heating_boundary=config_inputs.cooking_heating_boundary,
                    winter_reduction_fee=config_inputs.winter_reduction_fee,
                    non_winter_reduction_fee=config_inputs.non_winter_reduction_fee,
                    today=today,
                    usage_type=self._usage_type,
                )
                event_state = total_fee_int
                event_attrs = {
                    ATTR_START_DATE: attrs_int.get("start_date"),
                    ATTR_END_DATE: attrs_int.get("end_date"),
                    ATTR_DAYS_TOTAL: attrs_int.get("days_total"),
                    ATTR_DAYS_PREV_MONTH: attrs_int.get("days_prev_month", 0),
                    ATTR_DAYS_CURR_MONTH: attrs_int.get("days_curr_month", 0),
                    ATTR_BASE_FEE: config_inputs.base_fee,
                    ATTR_MONTHLY_GAS_USAGE: monthly_usage_int,
                    ATTR_CORRECTION_FACTOR: config_inputs.correction_factor,
                    ATTR_CORRECTED_MONTHLY_USAGE: round(corrected_usage_int, 2),
                    ATTR_PREV_MONTH_CALCULATED_FEE: attrs_int.get("prev_month_calculated_fee"),
                    ATTR_CURR_MONTH_CALCULATED_FEE: attrs_int.get("curr_month_calculated_fee"),
                    ATTR_PREV_MONTH_REDUCTION_APPLIED: attrs_int.get("prev_month_reduction_applied"),
                    ATTR_CURR_MONTH_REDUCTION_APPLIED: attrs_int.get("curr_month_reduction_applied"),
                    ATTR_COOKING_HEATING_BOUNDARY: attrs_int.get("cooking_heating_boundary"),
                    ATTR_PREV_MONTH_COOKING_FEE: attrs_int.get("prev_month_cooking_fee"),
                    ATTR_PREV_MONTH_HEATING_FEE: attrs_int.get("prev_month_heating_fee"),
                    ATTR_CURR_MONTH_COOKING_FEE: attrs_int.get("curr_month_cooking_fee"),
                    ATTR_CURR_MONTH_HEATING_FEE: attrs_int.get("curr_month_heating_fee"),
                }
            
            self.hass.bus.async_fire(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", {"state": event_state, "attributes": event_attrs,})
            
            if current_reading is not None and start_reading is not None:
                monthly_usage_raw = current_reading - start_reading
                if monthly_usage_raw < 0: monthly_usage_raw = 0
                monthly_usage_int = int(monthly_usage_raw)

                new_start_value = start_reading + monthly_usage_int
                await self.hass.services.async_call("number", "set_value", {"entity_id": start_reading_id, "value": float(new_start_value)}, blocking=True)
                self._last_reset_day = today
                LOGGER.info("새로운 월 검침 시작값을 %s로 설정했습니다.", new_start_value)

    async def _calculate_bill(self) -> None:
        await self._check_and_reset_on_reading_day()

        config_inputs = _get_bill_config_inputs(self.hass, self._number_ids)
        current_reading = self._get_current_reading() # 수정됨
        start_reading = _get_state_as_float(self.hass, self._number_ids.get("start_reading"))

        if config_inputs is None or current_reading is None or start_reading is None:
            self._attr_native_value = None
            return
        
        monthly_usage = current_reading - start_reading
        if monthly_usage < 0: monthly_usage = 0
        corrected_monthly_usage = monthly_usage * config_inputs.correction_factor
        today = date.today()
        calculator = GasBillCalculator(self._config[CONF_READING_DAY])
        total_fee, attrs = calculator.compute_total_bill_from_usage(
            corrected_usage=corrected_monthly_usage,
            base_fee=config_inputs.base_fee,
            prev_heat=config_inputs.prev_heat,
            curr_heat=config_inputs.curr_heat,
            prev_price_cooking=config_inputs.prev_price_cooking,
            prev_price_heating=config_inputs.prev_price_heating,
            curr_price_cooking=config_inputs.curr_price_cooking,
            curr_price_heating=config_inputs.curr_price_heating,
            cooking_heating_boundary=config_inputs.cooking_heating_boundary,
            winter_reduction_fee=config_inputs.winter_reduction_fee,
            non_winter_reduction_fee=config_inputs.non_winter_reduction_fee,
            today=today,
            usage_type=self._usage_type,
        )
        self._attr_native_value = total_fee
        self._attr_extra_state_attributes = {
            ATTR_START_DATE: attrs.get("start_date"),
            ATTR_END_DATE: attrs.get("end_date"),
            ATTR_DAYS_TOTAL: attrs.get("days_total"),
            ATTR_DAYS_PREV_MONTH: attrs.get("days_prev_month", 0),
            ATTR_DAYS_CURR_MONTH: attrs.get("days_curr_month", 0),
            ATTR_BASE_FEE: config_inputs.base_fee,
            ATTR_MONTHLY_GAS_USAGE: int(monthly_usage),
            ATTR_CORRECTION_FACTOR: config_inputs.correction_factor,
            ATTR_CORRECTED_MONTHLY_USAGE: round(corrected_monthly_usage, 2),
            ATTR_PREV_MONTH_CALCULATED_FEE: attrs.get("prev_month_calculated_fee"),
            ATTR_CURR_MONTH_CALCULATED_FEE: attrs.get("curr_month_calculated_fee"),
            ATTR_PREV_MONTH_REDUCTION_APPLIED: attrs.get("prev_month_reduction_applied"),
            ATTR_CURR_MONTH_REDUCTION_APPLIED: attrs.get("curr_month_reduction_applied"),
            ATTR_COOKING_HEATING_BOUNDARY: attrs.get("cooking_heating_boundary"),
            ATTR_PREV_MONTH_COOKING_FEE: attrs.get("prev_month_cooking_fee"),
            ATTR_PREV_MONTH_HEATING_FEE: attrs.get("prev_month_heating_fee"),
            ATTR_CURR_MONTH_COOKING_FEE: attrs.get("curr_month_cooking_fee"),
            ATTR_CURR_MONTH_HEATING_FEE: attrs.get("curr_month_heating_fee"),
        }

class EstimatedUsageSensor(SensorEntity):
    """현재 누적 사용량 추세를 바탕으로 검침 주기 종료 시점의 월 예상 사용량을 계산합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "estimated_monthly_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, start_reading_entity_id: str | None, virtual_sensor: WallpadCumulativeSensor | None = None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._start_reading_id = start_reading_entity_id
        self._virtual_sensor = virtual_sensor
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._start_reading_id: return
        
        if self._virtual_sensor:
            self._virtual_sensor.async_add_listener(self.async_update_ha_state)
            self.async_on_remove(async_track_state_change_event(self.hass, [self._start_reading_id], self._handle_state_change))
        else:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._gas_sensor_id, self._start_reading_id], self._handle_state_change))
            
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._start_reading_id: self._attr_native_value = None; return
        
        if self._virtual_sensor:
            current_reading = self._virtual_sensor.native_value
        else:
            current_reading = _get_state_as_float(self.hass, self._gas_sensor_id)
            
        start_reading = _get_state_as_float(self.hass, self._start_reading_id)

        if current_reading is None or start_reading is None:
            self._attr_native_value = None
            return

        current_usage = current_reading - start_reading
        if current_usage < 0: current_usage = 0
        
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        start_of_period = _get_last_reading_date(today, reading_day_config)
        next_reading_day = _get_next_reading_date(start_of_period, reading_day_config)
        days_passed = (today - start_of_period).days
        if days_passed <= 0: self._attr_native_value = round(current_usage, 2); return
        total_days_in_period = (next_reading_day - start_of_period).days
        if total_days_in_period <= 0: self._attr_native_value = round(current_usage, 2); return
        daily_avg_usage = current_usage / days_passed
        estimated_usage = daily_avg_usage * total_days_in_period
        self._attr_native_value = round(estimated_usage, 2)

class EstimatedBillSensor(SensorEntity):
    """예상 사용량과 요율(열량·단가, 기본요금, 보정계수)을 이용해 월 예상 요금을 계산합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "estimated_total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-clock"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, number_entity_ids: dict, estimated_usage_unique_id: str | None) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._number_ids = number_entity_ids
        self._estimated_usage_unique_id = estimated_usage_unique_id
        self._usage_type = self._config.get(CONF_USAGE_TYPE, "combined")
        self._estimated_usage_id: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {}
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        ent_reg = er.async_get(self.hass)
        self._estimated_usage_id = ent_reg.async_get_entity_id("sensor", DOMAIN, self._estimated_usage_unique_id)
        entities_to_track = [self._estimated_usage_id] + [eid for eid in self._number_ids.values() if eid is not None]
        if not self._estimated_usage_id: return
        self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        
        config_inputs = _get_bill_config_inputs(self.hass, self._number_ids)
        estimated_usage = _get_state_as_float(self.hass, self._estimated_usage_id)

        if config_inputs is None or estimated_usage is None:
            self._attr_native_value = None
            return
            
        corrected_estimated_usage = estimated_usage * config_inputs.correction_factor
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        
        start_of_period = _get_last_reading_date(today, reading_day_config)
        next_reading_day = _get_next_reading_date(start_of_period, reading_day_config)

        calculator = GasBillCalculator(reading_day_config)
        
        calculation_end_date = next_reading_day - timedelta(days=1)
        
        total_fee, attrs = calculator.compute_total_bill_from_usage(
            corrected_usage=corrected_estimated_usage,
            base_fee=config_inputs.base_fee,
            prev_heat=config_inputs.prev_heat,
            curr_heat=config_inputs.curr_heat,
            prev_price_cooking=config_inputs.prev_price_cooking,
            prev_price_heating=config_inputs.prev_price_heating,
            curr_price_cooking=config_inputs.curr_price_cooking,
            curr_price_heating=config_inputs.curr_price_heating,
            cooking_heating_boundary=config_inputs.cooking_heating_boundary,
            winter_reduction_fee=config_inputs.winter_reduction_fee,
            non_winter_reduction_fee=config_inputs.non_winter_reduction_fee,
            today=calculation_end_date,
            usage_type=self._usage_type,
        )
        self._attr_native_value = total_fee

        self._attr_extra_state_attributes = {
            ATTR_START_DATE: start_of_period.isoformat(),
            ATTR_END_DATE: calculation_end_date.isoformat(),
            ATTR_DAYS_TOTAL: attrs.get("days_total"),
            ATTR_DAYS_PREV_MONTH: attrs.get("days_prev_month", 0),
            ATTR_DAYS_CURR_MONTH: attrs.get("days_curr_month", 0),
            ATTR_BASE_FEE: config_inputs.base_fee,
            ATTR_MONTHLY_GAS_USAGE: round(estimated_usage, 2),
            ATTR_CORRECTION_FACTOR: config_inputs.correction_factor,
            ATTR_CORRECTED_MONTHLY_USAGE: round(corrected_estimated_usage, 2),
            ATTR_PREV_MONTH_CALCULATED_FEE: attrs.get("prev_month_calculated_fee"),
            ATTR_CURR_MONTH_CALCULATED_FEE: attrs.get("curr_month_calculated_fee"),
            ATTR_PREV_MONTH_REDUCTION_APPLIED: attrs.get("prev_month_reduction_applied"),
            ATTR_CURR_MONTH_REDUCTION_APPLIED: attrs.get("curr_month_reduction_applied"),
            ATTR_COOKING_HEATING_BOUNDARY: attrs.get("cooking_heating_boundary"),
            ATTR_PREV_MONTH_COOKING_FEE: attrs.get("prev_month_cooking_fee"),
            ATTR_PREV_MONTH_HEATING_FEE: attrs.get("prev_month_heating_fee"),
            ATTR_CURR_MONTH_COOKING_FEE: attrs.get("curr_month_cooking_fee"),
            ATTR_CURR_MONTH_HEATING_FEE: attrs.get("curr_month_heating_fee"),
        }

class PreviousMonthBillSensor(SensorEntity, RestoreEntity):
    """검침일 리셋 직전에 발행된 이벤트로 전월 총요금과 속성을 저장/복원하는 센서입니다."""
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
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
                self._attr_extra_state_attributes = last_state.attributes
            except (ValueError, TypeError):
                self._attr_native_value = None
        self.async_on_remove(self.hass.bus.async_listen(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", self._handle_bill_reset_event))
    @callback
    def _handle_bill_reset_event(self, event: Event) -> None:
        LOGGER.debug("PreviousMonthBillSensor received reset event with data: %s", event.data)
        self._attr_native_value = event.data.get("state")
        self._attr_extra_state_attributes = event.data.get("attributes", {})
        self.async_write_ha_state()

class LastScrapTimeSensor(CoordinatorEntity[CityGasDataUpdateCoordinator], SensorEntity):
    """공급사 데이터 스크래핑의 마지막 성공 시각을 노출합니다."""
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
        if self.coordinator.last_update_success:
            return self.coordinator.last_update_success_timestamp
        return None

# --- 추가: 전전월 요금 센서 클래스 ---
class PrePreviousMonthBillSensor(SensorEntity, RestoreEntity):
    """
    '전월 요금 센서'의 상태 변화를 감지하여, 
    전월 요금이 갱신되기 직전의 값(즉, 2달 전 요금)을 저장하는 센서입니다.
    3개월 검침 주기일 때만 사용됩니다.
    """
    _attr_has_entity_name = True
    _attr_translation_key = "pre_previous_month_total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-refund"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, prev_bill_sensor_unique_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._prev_bill_sensor_unique_id = prev_bill_sensor_unique_id
        self._attr_native_value = 0.0
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # 이전 상태 복원
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
                self._attr_extra_state_attributes = last_state.attributes
            except (ValueError, TypeError):
                pass
        
        # '전월 요금 센서'의 Entity ID 찾기
        ent_reg = er.async_get(self.hass)
        prev_bill_entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_bill_sensor_unique_id)
        
        if prev_bill_entity_id:
            # 전월 요금 센서가 변경될 때 호출될 리스너 등록
            self.async_on_remove(
                async_track_state_change_event(self.hass, [prev_bill_entity_id], self._handle_prev_bill_change)
            )

    @callback
    def _handle_prev_bill_change(self, event: Event) -> None:
        """
        전월 요금 센서의 값이 변경되면(새로운 달로 넘어가면),
        변경 전의 '옛날 값(old_state)'을 가져와서 '전전월 요금'으로 저장합니다.
        """
        old_state = event.data.get("old_state")
        if old_state and old_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(old_state.state)
                self._attr_extra_state_attributes = old_state.attributes
                self.async_write_ha_state()
                LOGGER.debug("전월 요금 변경 감지: 전전월 요금을 %s 로 업데이트했습니다.", self._attr_native_value)
            except (ValueError, TypeError):
                LOGGER.warning("전월 요금 센서의 이전 값을 숫자로 변환할 수 없습니다.")

# --- 정기(격월/3개월) 주기 센서 클래스들 ---

class PeriodicUsageSensor(SensorEntity):
    """정기 청구 사이클에 따라 사용량을 합산하여 제공합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "periodic_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, usage_uid: str, prev_uid: str, pre_prev_uid: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._usage_uid = usage_uid
        self._prev_uid = prev_uid
        self._pre_prev_uid = pre_prev_uid # 전전월 센서 UID 추가
        self._usage_id: str | None = None
        self._prev_id: str | None = None
        self._pre_prev_id: str | None = None
        self._attr_native_value = 0.0
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._usage_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._usage_uid)
        self._prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_uid)
        self._pre_prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._pre_prev_uid)
        
        entities_to_track = [eid for eid in [self._usage_id, self._prev_id, self._pre_prev_id] if eid]
        if entities_to_track:
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._usage_id or not self._prev_id: self._attr_native_value = None; return
        
        current_state = self.hass.states.get(self._usage_id)
        prev_state = self.hass.states.get(self._prev_id)
        pre_prev_state = self.hass.states.get(self._pre_prev_id) if self._pre_prev_id else None
        
        try:
            current_val = float(current_state.state) if current_state and current_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0.0
            
            # 사용량은 TotalBillSensor와 달리 센서의 attributes에서 가져와야 할 수도 있습니다.
            # 여기서는 편의상 전월 요금 센서(PreviousMonthBillSensor)의 속성인 ATTR_MONTHLY_GAS_USAGE를 사용한다고 가정합니다.
            prev_val = 0.0
            if prev_state and prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                prev_val = float(prev_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
            
            pre_prev_val = 0.0
            if pre_prev_state and pre_prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                pre_prev_val = float(pre_prev_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
            
            reading_cycle = self._config.get(CONF_READING_CYCLE)
            today = date.today()
            
            # 합산 로직 호출 (전전월 값 포함)
            agg = GasBillCalculator.aggregate_periodic(current_val, prev_val, today, reading_cycle, pre_prev_val)
            self._attr_native_value = round(agg, 2)
            
            # 속성 업데이트 (디버깅용)
            if GasBillCalculator.is_billing_month(today, reading_cycle):
                self._attr_extra_state_attributes = {
                    "current": current_val,
                    "previous": prev_val,
                    "pre_previous": pre_prev_val if reading_cycle.startswith("quarterly") else None
                }
            else:
                self._attr_extra_state_attributes = {}

        except (ValueError, TypeError): self._attr_native_value = None

class PeriodicBillSensor(SensorEntity):
    """정기 청구 사이클에 따라 요금을 합산하여 제공합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "periodic_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, bill_uid: str, prev_uid: str, pre_prev_uid: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._bill_uid = bill_uid
        self._prev_uid = prev_uid
        self._pre_prev_uid = pre_prev_uid
        self._bill_id: str | None = None
        self._prev_id: str | None = None
        self._pre_prev_id: str | None = None
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._bill_uid)
        self._prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_uid)
        self._pre_prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._pre_prev_uid)
        
        entities_to_track = [eid for eid in [self._bill_id, self._prev_id, self._pre_prev_id] if eid]
        if entities_to_track:
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._bill_id or not self._prev_id: self._attr_native_value = None; return
        
        curr_state = self.hass.states.get(self._bill_id)
        prev_state = self.hass.states.get(self._prev_id)
        pre_prev_state = self.hass.states.get(self._pre_prev_id) if self._pre_prev_id else None
        
        try:
            curr_val = float(curr_state.state) if curr_state and curr_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            prev_val = float(prev_state.state) if prev_state and prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            pre_prev_val = float(pre_prev_state.state) if pre_prev_state and pre_prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            
            reading_cycle = self._config.get(CONF_READING_CYCLE)
            today = date.today()

            agg = GasBillCalculator.aggregate_periodic(curr_val, prev_val, today, reading_cycle, pre_prev_val)
            self._attr_native_value = round(agg)
            
            if GasBillCalculator.is_billing_month(today, reading_cycle):
                self._attr_extra_state_attributes = {
                    "current": curr_val,
                    "previous": prev_val,
                    "pre_previous": pre_prev_val if reading_cycle.startswith("quarterly") else None
                }
            else:
                self._attr_extra_state_attributes = {}

        except (ValueError, TypeError): self._attr_native_value = None

class PreviousPeriodicBillSensor(SensorEntity, RestoreEntity):
    """직전 정기 청구월의 총요금을 저장/복원하는 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "periodic_previous_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-sync"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, periodic_bill_unique_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._periodic_bill_unique_id = periodic_bill_unique_id
        self._periodic_bill_id: str | None = None
        self._attr_native_value = None
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try: self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError): self._attr_native_value = None
        self._periodic_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._periodic_bill_unique_id)
        self.async_on_remove(self.hass.bus.async_listen(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", self._handle_bill_reset_event))
    @callback
    def _handle_bill_reset_event(self, event: Event) -> None:
        if not self._periodic_bill_id: return
        reading_cycle = self._config.get(CONF_READING_CYCLE)
        yesterday = date.today() - timedelta(days=1)
        if GasBillCalculator.is_billing_month(yesterday, reading_cycle):
            periodic_bill_state = self.hass.states.get(self._periodic_bill_id)
            if periodic_bill_state and periodic_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._attr_native_value = round(float(periodic_bill_state.state))
                    self.async_write_ha_state()
                    LOGGER.debug("직전 정기 총 사용요금을 %s 로 업데이트했습니다.", self._attr_native_value)
                except (ValueError, TypeError): LOGGER.warning("'정기 총 사용요금' 센서의 값을 읽을 수 없어 업데이트에 실패했습니다.")


class EstimatedPeriodicUsageSensor(SensorEntity):
    """월 예상 사용량을 기준으로 정기(격월/3개월) 예상 사용량을 계산합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "periodic_estimated_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:chart-box-outline"
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, est_usage_uid: str, prev_uid: str, pre_prev_uid: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._est_usage_uid = est_usage_uid
        self._prev_uid = prev_uid
        self._pre_prev_uid = pre_prev_uid
        self._est_usage_id: str | None = None
        self._prev_id: str | None = None
        self._pre_prev_id: str | None = None
        self._attr_native_value = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._est_usage_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._est_usage_uid)
        self._prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_uid)
        self._pre_prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._pre_prev_uid)
        
        entities_to_track = [eid for eid in [self._est_usage_id, self._prev_id, self._pre_prev_id] if eid]
        if entities_to_track:
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._est_usage_id or not self._prev_id: self._attr_native_value = None; return
        
        est_state = self.hass.states.get(self._est_usage_id)
        prev_state = self.hass.states.get(self._prev_id)
        pre_prev_state = self.hass.states.get(self._pre_prev_id) if self._pre_prev_id else None
        
        try:
            curr_est = float(est_state.state) if est_state and est_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0.0
            
            prev_val = 0.0
            if prev_state and prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                prev_val = float(prev_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
            
            pre_prev_val = 0.0
            if pre_prev_state and pre_prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                pre_prev_val = float(pre_prev_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
                
            reading_cycle = self._config.get(CONF_READING_CYCLE)
            today = date.today()
            agg = GasBillCalculator.aggregate_periodic(curr_est, prev_val, today, reading_cycle, pre_prev_val)
            self._attr_native_value = round(agg, 2)
        except (ValueError, TypeError): self._attr_native_value = None

class EstimatedPeriodicBillSensor(SensorEntity):
    """월 예상 요금을 기준으로 정기(격월/3개월) 예상 요금을 계산합니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "periodic_estimated_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, est_bill_uid: str, prev_uid: str, pre_prev_uid: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._est_bill_uid = est_bill_uid
        self._prev_uid = prev_uid
        self._pre_prev_uid = pre_prev_uid
        self._est_bill_id: str | None = None
        self._prev_id: str | None = None
        self._pre_prev_id: str | None = None
        self._attr_native_value = 0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._est_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._est_bill_uid)
        self._prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_uid)
        self._pre_prev_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._pre_prev_uid)
        
        entities_to_track = [eid for eid in [self._est_bill_id, self._prev_id, self._pre_prev_id] if eid]
        if entities_to_track:
            self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        if not self._est_bill_id or not self._prev_id: self._attr_native_value = None; return
        
        est_state = self.hass.states.get(self._est_bill_id)
        prev_state = self.hass.states.get(self._prev_id)
        pre_prev_state = self.hass.states.get(self._pre_prev_id) if self._pre_prev_id else None
        
        try:
            curr_est = float(est_state.state) if est_state and est_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            prev_val = float(prev_state.state) if prev_state and prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            pre_prev_val = float(pre_prev_state.state) if pre_prev_state and pre_prev_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            
            reading_cycle = self._config.get(CONF_READING_CYCLE)
            today = date.today()

            agg = GasBillCalculator.aggregate_periodic(curr_est, prev_val, today, reading_cycle, pre_prev_val)
            self._attr_native_value = round(agg)
        except (ValueError, TypeError): self._attr_native_value = None