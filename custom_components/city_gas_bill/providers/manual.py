# custom_components/city_gas_bill/providers/manual.py

"""A non-scraping provider for manual data entry."""
from __future__ import annotations

from .base import GasProvider

class ManualProvider(GasProvider):
    """Provider for users who want to manage heat and price data manually."""

    @property
    def id(self) -> str:
        return "manual"

    @property
    def name(self) -> str:
        return "수동 입력 (직접 관리)"

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """Do not scrape, return None to keep existing values."""
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """Do not scrape, return None to keep existing values."""
        return None