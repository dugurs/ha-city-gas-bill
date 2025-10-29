# custom_components/city_gas_bill/sensor.py

"""Sensor platform for the City Gas Bill integration."""
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
    """Calculate the last reading date based on today and the configured reading day."""
    if reading_day == 0:
        day = calendar.monthrange(today.year, today.month)[1]
        if today.day == day: return today
        last_month = today - relativedelta(months=1)
        return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
    if today.day >= reading_day: return today.replace(day=reading_day)
    return (today - relativedelta(months=1)).replace(day=reading_day)

def _get_next_reading_date(start_date: date, reading_day: int) -> date:
    """Calculate the next reading date from the start of the billing period."""
    next_month = start_date + relativedelta(months=1)
    if reading_day == 0:
        return next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1])
    return next_month.replace(day=reading_day)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    coordinator: CityGasDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name

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

class MonthlyGasUsageSensor(SensorEntity):
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
            LOGGER.info("Reading day detected. Firing reset event and updating start value.")
            self.hass.bus.async_fire(f"{EVENT_BILL_RESET}_{self._entry.entry_id}", {"state": self.native_value, "attributes": self.extra_state_attributes,})
            current_reading_state = self.hass.states.get(self._gas_sensor_id)
            if current_reading_state and current_reading_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    new_start_value = float(current_reading_state.state)
                    await self.hass.services.async_call("number", "set_value", {"entity_id": start_reading_id, "value": new_start_value}, blocking=True)
                    self._last_reset_day = today
                except (ValueError, TypeError): LOGGER.error("Failed to set new start value due to invalid gas sensor state.")
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
        end_of_period = today
        total_days = (end_of_period - start_of_period).days
        if total_days <= 0:
            self._attr_native_value = round(base_fee * 1.1)
            self._attr_extra_state_attributes = {ATTR_START_DATE: start_of_period.isoformat(), ATTR_END_DATE: today.isoformat(), ATTR_DAYS_TOTAL: 0}
            return

        prev_month_days, curr_month_days = 0, 0
        first_day_of_curr_month = today.replace(day=1)
        if start_of_period < first_day_of_curr_month:
            last_day_of_prev_month = first_day_of_curr_month - timedelta(days=1)
            prev_month_end = min(end_of_period, last_day_of_prev_month)
            prev_month_days = (prev_month_end - start_of_period).days + 1
        if end_of_period >= first_day_of_curr_month:
            curr_month_start = max(start_of_period, first_day_of_curr_month)
            curr_month_days = (end_of_period - curr_month_start).days + 1

        prev_month_usage = corrected_monthly_usage * (prev_month_days / total_days) if total_days > 0 else 0
        curr_month_usage = corrected_monthly_usage * (curr_month_days / total_days) if total_days > 0 else 0
        prev_month_fee = prev_month_usage * prev_heat * prev_price
        curr_month_fee = curr_month_usage * curr_heat * curr_price
        total_fee = (base_fee + prev_month_fee + curr_month_fee) * 1.1
        self._attr_native_value = round(total_fee)
        self._attr_extra_state_attributes = {
            ATTR_START_DATE: start_of_period.isoformat(),
            ATTR_END_DATE: end_of_period.isoformat(),
            ATTR_DAYS_TOTAL: total_days,
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
    _attr_state_class = SensorStateClass.MEASUREMENT
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
        if total_days <= 0: self._attr_native_value = round(base_fee * 1.1); return
        
        prev_month_days, curr_month_days = 0, 0
        
        if start_of_period.month != end_of_period.month:
            # This logic finds the last day of the month in which the period starts
            last_day_of_start_month = (start_of_period.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            prev_month_days = (last_day_of_start_month - start_of_period).days + 1
            curr_month_days = (end_of_period - last_day_of_start_month).days -1
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