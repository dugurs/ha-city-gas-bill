# custom_components/city_gas_bill/__init__.py

"""The City Gas Bill integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_time_change, async_call_later
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN, 
    PLATFORMS, 
    LOGGER,
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE
)
from .coordinator import CityGasDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up City Gas Bill from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = CityGasDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    async def _weekly_update(now):
        """Callback to trigger a weekly coordinator refresh on Mondays."""
        if now.weekday() == 0:
            LOGGER.info("Scheduled update: It's Monday, triggering data refresh.")
            await coordinator.async_request_refresh()
        else:
            LOGGER.debug("Scheduled update: Skipping, it's not Monday.")

    update_listener = async_track_time_change(hass, _weekly_update, hour=1, minute=0, second=0)

    @callback
    def update_number_entities():
        """Update number entities with the latest data from the coordinator."""
        LOGGER.debug("Coordinator has new data. Updating number entities.")
        ent_reg = er.async_get(hass)
        
        key_to_unique_id_map = {
            DATA_PREV_MONTH_HEAT: f"{entry.entry_id}_prev_month_heat",
            DATA_CURR_MONTH_HEAT: f"{entry.entry_id}_curr_month_heat",
            DATA_PREV_MONTH_PRICE: f"{entry.entry_id}_prev_month_price",
            DATA_CURR_MONTH_PRICE: f"{entry.entry_id}_curr_month_price",
        }

        for data_key, unique_id in key_to_unique_id_map.items():
            entity_id = ent_reg.async_get_entity_id("number", DOMAIN, unique_id)
            new_value = coordinator.data.get(data_key)

            if entity_id and new_value is not None:
                LOGGER.debug("Updating %s with new value: %s", entity_id, new_value)
                hass.async_create_task(
                    hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": entity_id, "value": new_value},
                        blocking=False,
                    )
                )

    coordinator_listener_remover = coordinator.async_add_listener(update_number_entities)

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "update_listener": update_listener,
        "coordinator_listener_remover": coordinator_listener_remover,
    }

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    if not entry.data.get("_initial_reload_done"):
        LOGGER.info("First time setup. Scheduling reload in 5s to ensure entities are ready.")
        async def _reload_integration(now):
            await hass.services.async_call(
                "homeassistant", "reload_config_entry",
                {"entry_id": entry.entry_id}, blocking=False
            )
        async_call_later(hass, 5, _reload_integration)
        new_data = {**entry.data, "_initial_reload_done": True}
        hass.config_entries.async_update_entry(entry, data=new_data)

    async def handle_update_service(call: ServiceCall) -> None:
        """Handle the service call to update gas data."""
        LOGGER.info("Manual update triggered by service call.")
        for entry_id_key, data in hass.data[DOMAIN].items():
            if "coordinator" in data:
                await data["coordinator"].async_request_refresh()
                
    hass.services.async_register(DOMAIN, "update_data", handle_update_service)
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "update_data"))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        data["update_listener"]()
        data["coordinator_listener_remover"]()
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)