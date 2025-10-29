# custom_components/city_gas_bill/providers/base.py

"""Base class for all gas providers."""
from __future__ import annotations
from abc import ABC, abstractmethod
import aiohttp

class GasProvider(ABC):
    """Abstract base class for all regional gas providers."""

    def __init__(self, websession: aiohttp.ClientSession | None):
        """Initialize the gas provider."""
        self.websession = websession

    @property
    @abstractmethod
    def id(self) -> str:
        """Return the unique ID of the provider (should match the file name)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the user-friendly name of the provider."""

    @abstractmethod
    async def scrape_heat_data(self) -> dict[str, float] | None:
        """Scrape average heat values for the current and previous months."""

    @abstractmethod
    async def scrape_price_data(self) -> dict[str, float] | None:
        """Scrape unit price values."""