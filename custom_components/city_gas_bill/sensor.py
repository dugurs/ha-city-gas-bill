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
    EVENT_BILL_RESET, CONF_PROVIDER, ATTR_MONTHLY_GAS_USAGE, CONF_BIMONTHLY_CYCLE
)
from .coordinator import CityGasDataUpdateCoordinator
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
        "prev_price": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_prev_month_price"),
        "curr_price": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_curr_month_price"),
        "correction_factor": ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_correction_factor"),
    }
    
    # 의존성 주입을 위한 각 센서의 고유 ID 정의
    usage_sensor_uid = f"{entry.entry_id}_monthly_gas_usage"
    bill_sensor_uid = f"{entry.entry_id}_total_bill"
    prev_bill_sensor_uid = f"{entry.entry_id}_previous_month_total_bill"
    estimated_usage_sensor_uid = f"{entry.entry_id}_estimated_monthly_usage"
    estimated_bill_sensor_uid = f"{entry.entry_id}_estimated_total_bill"
    bimonthly_bill_sensor_uid = f"{entry.entry_id}_bimonthly_bill"

    sensors = [
        MonthlyGasUsageSensor(hass, entry, device_info, num_ids.get("start_reading")),
        TotalBillSensor(hass, entry, device_info, num_ids),
        EstimatedUsageSensor(hass, entry, device_info, num_ids.get("start_reading")),
        EstimatedBillSensor(hass, entry, device_info, num_ids, estimated_usage_sensor_uid),
        PreviousMonthBillSensor(hass, entry, device_info),
        LastScrapTimeSensor(coordinator, device_info),
    ]
    
    if config.get(CONF_BIMONTHLY_CYCLE, "disabled") != "disabled":
        bimonthly_sensors = [
            BimonthlyUsageSensor(hass, entry, device_info, usage_sensor_uid, prev_bill_sensor_uid),
            BimonthlyBillSensor(hass, entry, device_info, bill_sensor_uid, prev_bill_sensor_uid),
            PreviousBimonthlyBillSensor(hass, entry, device_info, bimonthly_bill_sensor_uid),
            EstimatedBimonthlyUsageSensor(hass, entry, device_info, estimated_usage_sensor_uid, prev_bill_sensor_uid),
            EstimatedBimonthlyBillSensor(hass, entry, device_info, estimated_bill_sensor_uid, prev_bill_sensor_uid)
        ]
        sensors.extend(bimonthly_sensors)
        
    async_add_entities(sensors, True)

# --- 기본 월별 센서 클래스들 ---

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
        await super().async_added_to_hass()
        if not self._start_reading_id: return
        self.async_on_remove(async_track_state_change_event(self.hass, [self._gas_sensor_id, self._start_reading_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._start_reading_id: self._attr_native_value = None; return
        current_reading_state = self.hass.states.get(self._gas_sensor_id)
        start_reading_state = self.hass.states.get(self._start_reading_id)
        if (not current_reading_state or current_reading_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or not start_reading_state or start_reading_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)): self._attr_native_value = None; return
        try:
            current_reading = float(current_reading_state.state)
            start_reading = float(start_reading_state.state)
            usage = current_reading - start_reading
            self._attr_native_value = round(usage, 2) if usage >= 0 else 0
        except (ValueError, TypeError): self._attr_native_value = None

class TotalBillSensor(SensorEntity):
    """현재까지의 총 가스 요금을 계산하여 보여주는 핵심 센서입니다."""
    _attr_has_entity_name = True
    _attr_translation_key = "total_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, number_entity_ids: dict) -> None:
        self.hass = hass
        self._entry = entry
        self._config = entry.options or entry.data
        self._gas_sensor_id = self._config[CONF_GAS_SENSOR]
        self._number_ids = number_entity_ids
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._last_reset_day: date | None = None
        self._attr_extra_state_attributes = {}
        self._attr_native_value = 0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        entities_to_track = [self._gas_sensor_id] + [eid for eid in self._number_ids.values() if eid is not None]
        if not all(self._number_ids.values()): return
        self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None: await self._calculate_bill()
    async def _check_and_reset_on_reading_day(self) -> None:
        start_reading_id = self._number_ids.get("start_reading")
        if not start_reading_id: return
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        is_reading_day = ((reading_day_config == 0 and today.day == calendar.monthrange(today.year, today.month)[1]) or (reading_day_config != 0 and today.day == reading_day_config))
        if is_reading_day and self._last_reset_day != today:
            LOGGER.info("검침일이 되어 요금 리셋을 진행합니다.")
            self.hass.bus.async_fire(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", {"state": self.native_value, "attributes": self.extra_state_attributes,})
            current_reading_state = self.hass.states.get(self._gas_sensor_id)
            if current_reading_state and current_reading_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    new_start_value = int(float(current_reading_state.state))
                    await self.hass.services.async_call("number", "set_value", {"entity_id": start_reading_id, "value": float(new_start_value)}, blocking=True)
                    self._last_reset_day = today
                    LOGGER.info("새로운 월 검침 시작값을 %s로 설정했습니다.", new_start_value)
                except (ValueError, TypeError): LOGGER.error("가스 센서 값을 읽을 수 없어 시작값 리셋에 실패했습니다.")
    async def _calculate_bill(self) -> None:
        await self._check_and_reset_on_reading_day()
        if not all(self._number_ids.values()): self._attr_native_value = None; return
        try:
            current_reading = float(self.hass.states.get(self._gas_sensor_id).state)
            start_reading = float(self.hass.states.get(self._number_ids["start_reading"]).state)
            base_fee = float(self.hass.states.get(self._number_ids["base_fee"]).state)
            prev_heat = float(self.hass.states.get(self._number_ids["prev_heat"]).state)
            curr_heat = float(self.hass.states.get(self._number_ids["curr_heat"]).state)
            prev_price = float(self.hass.states.get(self._number_ids["prev_price"]).state)
            curr_price = float(self.hass.states.get(self._number_ids["curr_price"]).state)
            correction_factor = float(self.hass.states.get(self._number_ids["correction_factor"]).state)
        except (ValueError, TypeError, KeyError, AttributeError): self._attr_native_value = None; return
        
        monthly_usage = current_reading - start_reading
        if monthly_usage < 0: monthly_usage = 0
        
        corrected_monthly_usage = monthly_usage * correction_factor
        today = date.today()
        start_of_period = _get_last_reading_date(today, self._config[CONF_READING_DAY])
        
        prev_month_days, curr_month_days = 0, 0
        if today >= start_of_period:
            first_day_of_curr_month = today.replace(day=1)
            if start_of_period < first_day_of_curr_month:
                last_day_of_prev_month = first_day_of_curr_month - timedelta(days=1)
                prev_month_days = (last_day_of_prev_month - start_of_period).days + 1
            curr_month_start = max(start_of_period, first_day_of_curr_month)
            curr_month_days = (today - curr_month_start).days + 1

        total_days_for_ratio = prev_month_days + curr_month_days

        if total_days_for_ratio <= 0:
            self._attr_native_value = round(base_fee * 1.1)
            self._attr_extra_state_attributes = {ATTR_START_DATE: start_of_period.isoformat(), ATTR_END_DATE: today.isoformat(), ATTR_DAYS_TOTAL: 0}
            return

        prev_month_usage = corrected_monthly_usage * (prev_month_days / total_days_for_ratio)
        curr_month_usage = corrected_monthly_usage * (curr_month_days / total_days_for_ratio)
        
        prev_month_fee = prev_month_usage * prev_heat * prev_price
        curr_month_fee = curr_month_usage * curr_heat * curr_price
        total_fee = (base_fee + prev_month_fee + curr_month_fee) * 1.1
        self._attr_native_value = round(total_fee)
        self._attr_extra_state_attributes = {
            ATTR_START_DATE: start_of_period.isoformat(),
            ATTR_END_DATE: today.isoformat(),
            ATTR_DAYS_TOTAL: total_days_for_ratio,
            ATTR_DAYS_PREV_MONTH: prev_month_days,
            ATTR_DAYS_CURR_MONTH: curr_month_days,
            "base_fee": base_fee,
            ATTR_MONTHLY_GAS_USAGE: round(monthly_usage, 2),
            "correction_factor": correction_factor,
            "corrected_monthly_usage": round(corrected_monthly_usage, 2),
            "prev_month_calculated_fee": round(prev_month_fee),
            "curr_month_calculated_fee": round(curr_month_fee)
        }

class EstimatedUsageSensor(SensorEntity):
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
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._start_reading_id: self._attr_native_value = None; return
        try:
            current_reading = float(self.hass.states.get(self._gas_sensor_id).state)
            start_reading = float(self.hass.states.get(self._start_reading_id).state)
            current_usage = current_reading - start_reading
            if current_usage < 0: current_usage = 0
        except (ValueError, TypeError, AttributeError): self._attr_native_value = None; return
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
        self._estimated_usage_id: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = 0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        ent_reg = er.async_get(self.hass)
        self._estimated_usage_id = ent_reg.async_get_entity_id("sensor", DOMAIN, self._estimated_usage_unique_id)
        entities_to_track = [self._estimated_usage_id] + [eid for eid in self._number_ids.values() if eid is not None]
        if not all(self._number_ids.values()) or not self._estimated_usage_id: return
        self.async_on_remove(async_track_state_change_event(self.hass, entities_to_track, self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not all(self._number_ids.values()) or not self._estimated_usage_id: self._attr_native_value = None; return
        try:
            estimated_usage = float(self.hass.states.get(self._estimated_usage_id).state)
            base_fee = float(self.hass.states.get(self._number_ids["base_fee"]).state)
            prev_heat = float(self.hass.states.get(self._number_ids["prev_heat"]).state)
            curr_heat = float(self.hass.states.get(self._number_ids["curr_heat"]).state)
            prev_price = float(self.hass.states.get(self._number_ids["prev_price"]).state)
            curr_price = float(self.hass.states.get(self._number_ids["curr_price"]).state)
            correction_factor = float(self.hass.states.get(self._number_ids["correction_factor"]).state)
        except (ValueError, TypeError, KeyError, AttributeError): self._attr_native_value = None; return

        corrected_estimated_usage = estimated_usage * correction_factor
        today = date.today()
        reading_day_config = self._config[CONF_READING_DAY]
        start_of_period = _get_last_reading_date(today, reading_day_config)
        end_of_period = _get_next_reading_date(start_of_period, reading_day_config)
        
        total_days = (end_of_period - start_of_period).days
        if total_days <= 0: 
            self._attr_native_value = round(base_fee * 1.1)
            return

        prev_month_days, curr_month_days = 0, 0
        if start_of_period.month != end_of_period.month:
            last_day_of_start_month = (start_of_period.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            prev_month_days = (last_day_of_start_month - start_of_period).days + 1
            curr_month_days = total_days - prev_month_days
        else: 
            prev_month_days = total_days
            curr_month_days = 0
        
        prev_month_usage = corrected_estimated_usage * (prev_month_days / total_days) if total_days > 0 else 0
        curr_month_usage = corrected_estimated_usage * (curr_month_days / total_days) if total_days > 0 else 0
        prev_month_fee = prev_month_usage * prev_heat * prev_price
        curr_month_fee = curr_month_usage * curr_heat * curr_price
        total_fee = (base_fee + prev_month_fee + curr_month_fee) * 1.1
        self._attr_native_value = round(total_fee)

class PreviousMonthBillSensor(SensorEntity, RestoreEntity):
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

# --- 격월 주기 센서 클래스들 ---

class BimonthlyUsageSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bimonthly_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:counter"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, usage_sensor_unique_id: str, prev_bill_sensor_unique_id: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._usage_sensor_unique_id = usage_sensor_unique_id
        self._prev_bill_sensor_unique_id = prev_bill_sensor_unique_id
        self._usage_sensor_id: str | None = None
        self._prev_bill_sensor_id: str | None = None
        self._attr_native_value = 0.0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._usage_sensor_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._usage_sensor_unique_id)
        self._prev_bill_sensor_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_bill_sensor_unique_id)
        if self._usage_sensor_id and self._prev_bill_sensor_id:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._usage_sensor_id, self._prev_bill_sensor_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._usage_sensor_id or not self._prev_bill_sensor_id: self._attr_native_value = None; return
        current_usage_state = self.hass.states.get(self._usage_sensor_id)
        prev_bill_state = self.hass.states.get(self._prev_bill_sensor_id)
        try:
            current_usage = float(current_usage_state.state) if current_usage_state and current_usage_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0.0
            prev_usage = 0.0
            if prev_bill_state and prev_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                prev_usage = float(prev_bill_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
            bimonthly_cycle = self._config.get(CONF_BIMONTHLY_CYCLE)
            today = date.today()
            is_odd_month = today.month % 2 == 1
            is_even_month = not is_odd_month
            if (bimonthly_cycle == "odd" and is_odd_month) or (bimonthly_cycle == "even" and is_even_month):
                self._attr_native_value = round(prev_usage + current_usage, 2)
            else:
                self._attr_native_value = round(current_usage, 2)
        except (ValueError, TypeError): self._attr_native_value = None

class BimonthlyBillSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bimonthly_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-multiple"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, bill_sensor_unique_id: str, prev_bill_sensor_unique_id: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._bill_sensor_unique_id = bill_sensor_unique_id
        self._prev_bill_sensor_unique_id = prev_bill_sensor_unique_id
        self._bill_sensor_id: str | None = None
        self._prev_bill_sensor_id: str | None = None
        self._attr_native_value = 0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._bill_sensor_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._bill_sensor_unique_id)
        self._prev_bill_sensor_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_bill_sensor_unique_id)
        if self._bill_sensor_id and self._prev_bill_sensor_id:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._bill_sensor_id, self._prev_bill_sensor_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._bill_sensor_id or not self._prev_bill_sensor_id: self._attr_native_value = None; return
        current_bill_state = self.hass.states.get(self._bill_sensor_id)
        prev_bill_state = self.hass.states.get(self._prev_bill_sensor_id)
        try:
            current_bill = float(current_bill_state.state) if current_bill_state and current_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            prev_bill = float(prev_bill_state.state) if prev_bill_state and prev_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            bimonthly_cycle = self._config.get(CONF_BIMONTHLY_CYCLE)
            today = date.today()
            is_odd_month = today.month % 2 == 1
            is_even_month = not is_odd_month
            if (bimonthly_cycle == "odd" and is_odd_month) or (bimonthly_cycle == "even" and is_even_month):
                self._attr_native_value = round(prev_bill + current_bill)
            else:
                self._attr_native_value = round(current_bill)
        except (ValueError, TypeError): self._attr_native_value = None

class PreviousBimonthlyBillSensor(SensorEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bimonthly_previous_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-sync"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, bimonthly_bill_unique_id: str) -> None:
        self.hass = hass
        self._entry = entry
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._bimonthly_bill_unique_id = bimonthly_bill_unique_id
        self._bimonthly_bill_id: str | None = None
        self._attr_native_value = None
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try: self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError): self._attr_native_value = None
        self._bimonthly_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._bimonthly_bill_unique_id)
        self.async_on_remove(self.hass.bus.async_listen(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", self._handle_bill_reset_event))
    @callback
    def _handle_bill_reset_event(self, event: Event) -> None:
        if not self._bimonthly_bill_id: return
        bimonthly_cycle = self._config.get(CONF_BIMONTHLY_CYCLE)
        yesterday = date.today() - timedelta(days=1)
        prev_month = yesterday.month
        is_prev_month_odd = prev_month % 2 == 1
        is_prev_month_even = not is_prev_month_odd
        if (bimonthly_cycle == "odd" and is_prev_month_odd) or (bimonthly_cycle == "even" and is_prev_month_even):
            bimonthly_bill_state = self.hass.states.get(self._bimonthly_bill_id)
            if bimonthly_bill_state and bimonthly_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    self._attr_native_value = round(float(bimonthly_bill_state.state))
                    self.async_write_ha_state()
                    LOGGER.debug("직전 격월 총 사용요금을 %s 로 업데이트했습니다.", self._attr_native_value)
                except (ValueError, TypeError): LOGGER.warning("'격월 총 사용요금' 센서의 값을 읽을 수 없어 업데이트에 실패했습니다.")

class EstimatedBimonthlyUsageSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bimonthly_estimated_usage"
    _attr_native_unit_of_measurement = "m³"
    _attr_device_class = SensorDeviceClass.GAS
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:chart-box-outline"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, est_usage_unique_id: str, prev_bill_unique_id: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._est_usage_unique_id = est_usage_unique_id
        self._prev_bill_unique_id = prev_bill_unique_id
        self._est_usage_id: str | None = None
        self._prev_bill_id: str | None = None
        self._attr_native_value = 0.0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._est_usage_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._est_usage_unique_id)
        self._prev_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_bill_unique_id)
        if self._est_usage_id and self._prev_bill_id:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._est_usage_id, self._prev_bill_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._est_usage_id or not self._prev_bill_id: self._attr_native_value = None; return
        est_usage_state = self.hass.states.get(self._est_usage_id)
        prev_bill_state = self.hass.states.get(self._prev_bill_id)
        try:
            current_estimated_usage = float(est_usage_state.state) if est_usage_state and est_usage_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0.0
            prev_actual_usage = 0.0
            if prev_bill_state and prev_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                prev_actual_usage = float(prev_bill_state.attributes.get(ATTR_MONTHLY_GAS_USAGE, 0.0))
            bimonthly_cycle = self._config.get(CONF_BIMONTHLY_CYCLE)
            today = date.today()
            is_odd_month = today.month % 2 == 1
            is_even_month = not is_odd_month
            if (bimonthly_cycle == "odd" and is_odd_month) or (bimonthly_cycle == "even" and is_even_month):
                self._attr_native_value = round(prev_actual_usage + current_estimated_usage, 2)
            else:
                self._attr_native_value = round(current_estimated_usage, 2)
        except (ValueError, TypeError): self._attr_native_value = None

class EstimatedBimonthlyBillSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "bimonthly_estimated_bill"
    _attr_native_unit_of_measurement = "KRW"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-clock"
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo, est_bill_unique_id: str, prev_bill_unique_id: str) -> None:
        self.hass = hass
        self._config = entry.options or entry.data
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._ent_reg = er.async_get(hass)
        self._est_bill_unique_id = est_bill_unique_id
        self._prev_bill_unique_id = prev_bill_unique_id
        self._est_bill_id: str | None = None
        self._prev_bill_id: str | None = None
        self._attr_native_value = 0
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._est_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._est_bill_unique_id)
        self._prev_bill_id = self._ent_reg.async_get_entity_id("sensor", DOMAIN, self._prev_bill_unique_id)
        if self._est_bill_id and self._prev_bill_id:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._est_bill_id, self._prev_bill_id], self._handle_state_change))
        self.async_schedule_update_ha_state(force_refresh=True)
    @callback
    def _handle_state_change(self, event) -> None: self.async_schedule_update_ha_state(True)
    async def async_update(self) -> None:
        if not self._est_bill_id or not self._prev_bill_id: self._attr_native_value = None; return
        est_bill_state = self.hass.states.get(self._est_bill_id)
        prev_bill_state = self.hass.states.get(self._prev_bill_id)
        try:
            current_estimated_bill = float(est_bill_state.state) if est_bill_state and est_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            prev_actual_bill = float(prev_bill_state.state) if prev_bill_state and prev_bill_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) else 0
            bimonthly_cycle = self._config.get(CONF_BIMONTHLY_CYCLE)
            today = date.today()
            is_odd_month = today.month % 2 == 1
            is_even_month = not is_odd_month
            if (bimonthly_cycle == "odd" and is_odd_month) or (bimonthly_cycle == "even" and is_even_month):
                self._attr_native_value = round(prev_actual_bill + current_estimated_bill)
            else:
                self._attr_native_value = round(current_estimated_bill)
        except (ValueError, TypeError): self._attr_native_value = None