# custom_components/city_gas_bill/providers/incheon_gas.py

"""Provider implementation for Incheon City Gas."""
from __future__ import annotations
from datetime import date, timedelta
import time
import random
import re
import logging

from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE,
)

_LOGGER = logging.getLogger(__name__)

class IncheonGasProvider(GasProvider):
    """Provider for scraping data from Incheon City Gas."""
    
    URL_PRICE = "https://icgas.co.kr:8443/recruit/dwr/exec/ICGAS.getChargecost.dwr"
    # --- NEW: 열량 조회 URL 추가 ---
    URL_HEAT = "https://icgas.co.kr:8443/recruit/dwr/exec/PAY.getSimplePayCalListData.dwr"

    @property
    def id(self) -> str:
        return "incheon_gas"

    @property
    def name(self) -> str:
        return "인천도시가스 (인천,코원)"

    # --- NEW: 열량 조회를 위한 별도 함수 ---
    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """Fetch the average heat for a specific date range."""
        session_id = f"{random.randint(1000, 9999)}_{int(time.time() * 1000)}"
        
        payload = {
            "callCount": "1",
            "c0-scriptName": "PAY",
            "c0-methodName": "getSimplePayCalListData",
            "c0-id": session_id,
            "c0-param0": f"string:{start_date.strftime('%Y%m%d')}",
            "c0-param1": f"string:{end_date.strftime('%Y%m%d')}",
            "xml": "true",
        }

        try:
            async with self.websession.post(self.URL_HEAT, data=payload) as response:
                response.raise_for_status()
                response_text = await response.text()

                # 응답에서 s0 변수의 HTML 내용을 먼저 추출합니다.
                # re.DOTALL은 줄바꿈 문자를 포함하여 매칭하기 위함입니다.
                s0_match = re.search(r'var s0="(.+?)";', response_text, re.DOTALL)
                if not s0_match:
                    _LOGGER.warning("Could not find s0 variable in heat DWR response.")
                    return None
                
                html_content = s0_match.group(1)
                
                # HTML 내용에서 열량 값을 추출합니다. (예: 42.507 MJ/Nm³)
                heat_match = re.search(r'(\d+\.\d+)\s*MJ/Nm', html_content)
                if heat_match:
                    heat_str = heat_match.group(1)
                    _LOGGER.debug("Found heat value for %s-%s: %s", start_date, end_date, heat_str)
                    return float(heat_str)
                
                _LOGGER.warning("Could not find heat value in DWR HTML response.")
                return None
        except Exception as err:
            _LOGGER.error("Error fetching heat for %s-%s: %s", start_date, end_date, err)
            return None

    async def _fetch_price_for_date(self, target_date: date) -> float | None:
        """Fetch the unit price for a specific date using DWR call."""
        session_id = f"{random.randint(1000, 9999)}_{int(time.time() * 1000)}"
        
        payload = {
            "callCount": "1",
            "c0-scriptName": "ICGAS",
            "c0-methodName": "getChargecost",
            "c0-id": session_id,
            "c0-param0": "string:1",
            "c0-param1": "string:주택취사",
            "c0-param2": f"string:{target_date.strftime('%Y-%m-%d')}",
            "c0-param3": "string:주택취사",
            "xml": "true",
        }

        try:
            async with self.websession.post(self.URL_PRICE, data=payload) as response:
                response.raise_for_status()
                response_text = await response.text()

                match = re.search(r'var s6="(\d+\.\d+)"', response_text)
                if match:
                    price_str = match.group(1)
                    _LOGGER.debug("Found price for %s: %s", target_date, price_str)
                    return float(price_str)
                
                _LOGGER.warning("Could not find price (s6) in DWR response for %s", target_date)
                return None
        except Exception as err:
            _LOGGER.error("Error fetching price for %s: %s", target_date, err)
            return None

    # --- MODIFIED: 열량 스크래핑 로직 구현 ---
    async def scrape_heat_data(self) -> dict[str, float] | None:
        """Scrape average heat for the current and previous months."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        
        # 각 기간에 맞는 평균열량을 조회합니다.
        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }
        
        _LOGGER.error("Failed to fetch one or both month's heat values for Incheon Gas.")
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """Scrape unit price for the current and previous months."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        first_day_prev_month = first_day_curr_month - relativedelta(months=1)

        curr_month_price = await self._fetch_price_for_date(first_day_curr_month)
        prev_month_price = await self._fetch_price_for_date(first_day_prev_month)

        if curr_month_price is not None and prev_month_price is not None:
            return {
                DATA_CURR_MONTH_PRICE: curr_month_price,
                DATA_PREV_MONTH_PRICE: prev_month_price,
            }
        
        _LOGGER.error("Failed to fetch one or both month's prices for Incheon Gas.")
        return None