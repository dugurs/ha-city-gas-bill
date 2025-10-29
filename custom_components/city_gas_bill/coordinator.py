# custom_components/city_gas_bill/coordinator.py

"""DataUpdateCoordinator for the City Gas Bill integration."""
from __future__ import annotations
import async_timeout
import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER, CONF_PROVIDER
from .providers import AVAILABLE_PROVIDERS
from .providers.base import GasProvider

class CityGasDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching gas data from the selected provider."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.config_entry = entry
        self.websession = async_create_clientsession(hass, verify_ssl=False)

        # --- MODIFIED: Prioritize options over data ---
        # If the user has configured options, use them. Otherwise, fall back to the initial setup data.
        config = self.config_entry.options or self.config_entry.data
        provider_key = config[CONF_PROVIDER]
        # --- END MODIFICATION ---

        provider_class = AVAILABLE_PROVIDERS.get(provider_key)
        if not provider_class:
            raise ConfigEntryError(f"Provider '{provider_key}' not found.")
        self.provider: GasProvider = provider_class(self.websession)

        self.last_update_success_timestamp = None
        
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} ({self.provider.name})",
        )

    async def _async_update_data(self) -> dict:
        """Fetch data using the selected provider."""
        if self.provider.id == "manual":
            LOGGER.debug("Manual provider selected, skipping web scrape.")
            self.last_update_success_timestamp = dt_util.utcnow()
            return {}

        try:
            async with async_timeout.timeout(60):
                heat_data = await self.provider.scrape_heat_data()
                price_data = await self.provider.scrape_price_data()

                if not heat_data or not price_data:
                    failed_items = []
                    if not heat_data: failed_items.append("heat data")
                    if not price_data: failed_items.append("price data")
                    raise UpdateFailed(
                        f"Failed to scrape required item(s): {', '.join(failed_items)} "
                        f"from {self.provider.name}."
                    )

                self.last_update_success_timestamp = dt_util.utcnow()
                return {**heat_data, **price_data}

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with {self.provider.name}: {err}")
        except Exception as err:
            raise UpdateFailed(f"An unexpected error occurred for {self.provider.name}: {err}")