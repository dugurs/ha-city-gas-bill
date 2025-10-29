# custom_components/city_gas_bill/number.py

"""Number platform for City Gas Bill configuration entities."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import DOMAIN, DEFAULT_BASE_FEE, CONF_GAS_SENSOR, LOGGER
from .providers import AVAILABLE_PROVIDERS
from .const import CONF_PROVIDER

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform."""
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )
    
    async_add_entities([
        BaseFeeNumber(entry, device_info),
        MonthlyStartReadingNumber(hass, entry, device_info),
        PrevMonthHeatNumber(entry, device_info),
        CurrMonthHeatNumber(entry, device_info),
        PrevMonthPriceNumber(entry, device_info),
        CurrMonthPriceNumber(entry, device_info),
        CorrectionFactorNumber(entry, device_info),
    ])

class RestorableNumberEntity(NumberEntity, RestoreEntity):
    """Base class for restorable number entities."""
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo, default_value: float) -> None:
        """Initialize the number entity."""
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = default_value

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                LOGGER.warning("Could not parse restored state for %s", self.entity_id)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self.async_write_ha_state()

class CorrectionFactorNumber(RestorableNumberEntity):
    """Representation of the temperature/pressure correction factor."""
    _attr_translation_key = "correction_factor"
    _attr_icon = "mdi:gauge"
    _attr_native_unit_of_measurement = None
    _attr_native_min_value = 0.8; _attr_native_max_value = 1.2; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=1.0)

class PrevMonthHeatNumber(RestorableNumberEntity):
    _attr_translation_key = "prev_month_heat"
    _attr_icon = "mdi:fire-alert"
    _attr_native_unit_of_measurement = "MJ/Nm³"
    _attr_native_min_value = 30.0; _attr_native_max_value = 50.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=43.0)

class CurrMonthHeatNumber(RestorableNumberEntity):
    _attr_translation_key = "curr_month_heat"
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "MJ/Nm³"
    _attr_native_min_value = 30.0; _attr_native_max_value = 50.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=43.0)

class PrevMonthPriceNumber(RestorableNumberEntity):
    _attr_translation_key = "prev_month_price"
    _attr_icon = "mdi:cash-minus"
    _attr_native_unit_of_measurement = "KRW/MJ"
    _attr_native_min_value = 0.0; _attr_native_max_value = 100.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        # --- MODIFIED ---
        super().__init__(entry, device_info, default_value=22.3)

class CurrMonthPriceNumber(RestorableNumberEntity):
    _attr_translation_key = "curr_month_price"
    _attr_icon = "mdi:cash"
    _attr_native_unit_of_measurement = "KRW/MJ"
    _attr_native_min_value = 0.0; _attr_native_max_value = 100.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        # --- MODIFIED ---
        super().__init__(entry, device_info, default_value=22.3)

class BaseFeeNumber(RestorableNumberEntity):
    _attr_translation_key = "base_fee"
    _attr_icon = "mdi:cash"
    _attr_native_unit_of_measurement = "KRW"
    _attr_native_min_value = 0; _attr_native_max_value = 10000; _attr_native_step = 1.0
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=DEFAULT_BASE_FEE)

class MonthlyStartReadingNumber(RestorableNumberEntity):
    _attr_translation_key = "monthly_start_reading"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "m³"
    _attr_native_min_value = 0; _attr_native_max_value = 999999; _attr_native_step = 0.01
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        self.hass = hass
        self._entry = entry
        super().__init__(entry, device_info, default_value=0.0)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.native_value > 0: return

        gas_sensor_id = self._entry.data[CONF_GAS_SENSOR]
        gas_state: State | None = self.hass.states.get(gas_sensor_id)
        if gas_state and gas_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                initial_value = float(gas_state.state)
                self._attr_native_value = initial_value
                self.async_write_ha_state()
                LOGGER.info("Set initial start reading from '%s' to %s", gas_sensor_id, initial_value)
            except (ValueError, TypeError):
                LOGGER.warning("Could not parse state of '%s'. Start reading remains 0.", gas_sensor_id)