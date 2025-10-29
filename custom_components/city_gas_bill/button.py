# custom_components/city_gas_bill/button.py

"""Button platform for the City Gas Bill integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER
from .providers import AVAILABLE_PROVIDERS
from .const import CONF_PROVIDER

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )

    async_add_entities([UpdateDataButton(hass, entry, device_info)])


class UpdateDataButton(ButtonEntity):
    """A button to manually trigger a data sync from the provider."""

    _attr_has_entity_name = True
    _attr_translation_key = "update_data"
    _attr_icon = "mdi:cloud-refresh"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the update button."""
        self.hass = hass
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Update data button pressed. Calling update_data service.")
        await self.hass.services.async_call(
            DOMAIN,
            "update_data",
            {},
            blocking=False,
        )