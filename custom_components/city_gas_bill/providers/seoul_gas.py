# custom_components/city_gas_bill/providers/seoul_gas.py

"""Provider implementation for Seoul Gas."""
from __future__ import annotations
from datetime import date, timedelta
import re
import logging

from bs4 import BeautifulSoup

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE,
)

_LOGGER = logging.getLogger(__name__)

class SeoulGasProvider(GasProvider):
    """Provider for scraping data from Seoul Gas."""
    URL_HEAT = "https://www.seoulgas.co.kr/front/payment/selectHeat.do"
    URL_PRICE = "https://www.seoulgas.co.kr/front/payment/gasPayTable.do"

    @property
    def id(self) -> str:
        return "seoul_gas"

    @property
    def name(self) -> str:
        return "서울도시가스"

    def _parse_heat_from_html(self, html_content: str, month_label: str) -> str | None:
        soup = BeautifulSoup(html_content, "html.parser")
        content_div = soup.select_one("#content")
        if not content_div:
            _LOGGER.error("Could not find the main content div for %s.", month_label)
            return None
        for p_tag in content_div.find_all("p"):
            if "평균 열량" in p_tag.get_text():
                match = re.search(r"(\d+\.\d+)", p_tag.get_text())
                if match:
                    return match.group(1)
        _LOGGER.error("Could not parse the heat data for %s.", month_label)
        return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        try:
            params_curr = {"startDate": first_day_curr_month.strftime("%Y.%m.%d"), "endDate": today.strftime("%Y.%m.%d")}
            async with self.websession.post(self.URL_HEAT, data=params_curr) as response:
                response.raise_for_status()
                curr_heat_str = self._parse_heat_from_html(await response.text(), "current month")

            params_prev = {"startDate": first_day_prev_month.strftime("%Y.%m.%d"), "endDate": last_day_prev_month.strftime("%Y.%m.%d")}
            async with self.websession.post(self.URL_HEAT, data=params_prev) as response:
                response.raise_for_status()
                prev_heat_str = self._parse_heat_from_html(await response.text(), "previous month")

            if not curr_heat_str or not prev_heat_str: return None
            return {
                DATA_CURR_MONTH_HEAT: float(curr_heat_str),
                DATA_PREV_MONTH_HEAT: float(prev_heat_str)
            }
        except Exception as err:
            _LOGGER.error("Error scraping heat data for Seoul Gas: %s", err)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        try:
            async with self.websession.get(self.URL_PRICE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")
                table = soup.select_one(".tblgas > table")
                if not table: return None
                for th in table.find_all("th"):
                    if "취사" in th.get_text():
                        tds = th.find_next_siblings("td")
                        if len(tds) >= 2:
                            return {
                                DATA_PREV_MONTH_PRICE: float(tds[0].get_text(strip=True)),
                                DATA_CURR_MONTH_PRICE: float(tds[1].get_text(strip=True))
                            }
                return None
        except Exception as err:
            _LOGGER.error("Error scraping price data for Seoul Gas: %s", err)
            return None