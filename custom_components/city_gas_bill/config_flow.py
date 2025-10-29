# custom_components/city_gas_bill/config_flow.py

"""Config flow for the City Gas Bill integration."""
from __future__ import annotations
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from .const import DOMAIN, CONF_PROVIDER, CONF_GAS_SENSOR, CONF_READING_DAY
from .providers import AVAILABLE_PROVIDERS

def _get_data_schema(current_config: dict | None = None) -> vol.Schema:
    """Return the data schema for user input."""
    if current_config is None:
        current_config = {}

    provider_options: list[SelectOptionDict] = sorted(
        [
            SelectOptionDict(value=provider_id, label=provider(None).name)
            for provider_id, provider in AVAILABLE_PROVIDERS.items()
        ],
        key=lambda item: item["label"],
    )

    return vol.Schema({
        vol.Required(
            CONF_PROVIDER,
            default=current_config.get(CONF_PROVIDER),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=provider_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_GAS_SENSOR,
            default=current_config.get(CONF_GAS_SENSOR),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="gas"),
        ),
        vol.Required(
            CONF_READING_DAY,
            default=current_config.get(CONF_READING_DAY, 26),
        ): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=28, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Coerce(int)
        ),
    })

class CityGasBillConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for City Gas Bill."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CityGasBillOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="City Gas", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_get_data_schema())

class CityGasBillOptionsFlowHandler(OptionsFlow):
    """Handle an options flow for City Gas Bill."""

    # --- MODIFIED: Reverted to the original working method. ---
    # This will work without crashing, although it may still produce a
    # deprecation warning in the logs. This is acceptable for now.
    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_config = self.config_entry.options or self.config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=_get_data_schema(current_config),
        )