# custom_components/city_gas_bill/providers/gyeonggi_gas.py

"""
경기 지역 도시가스(코원에너지서비스) 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
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

class GyeonggiGasProvider(GasProvider):
    """
    경기 지역(코원에너지서비스)의 DWR 호출을 통해 데이터를 가져오는 클래스입니다.
    incheon_gas.py와 거의 동일하며 지역 코드만 다릅니다.
    """
    
    URL_PRICE = "https://icgas.co.kr:8443/recruit/dwr/exec/ICGAS.getChargecost.dwr"
    URL_HEAT = "https://icgas.co.kr:8443/recruit/dwr/exec/PAY.getSimplePayCalListData.dwr"

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "gyeonggi_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "인천도시가스 (경기,코원)"

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        특정 기간 동안의 평균열량을 조회합니다. (incheon_gas.py와 동일)
        """
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

                s0_match = re.search(r'var s0="(.+?)";', response_text, re.DOTALL)
                if not s0_match:
                    _LOGGER.warning("DWR 응답에서 s0 변수(열량 데이터)를 찾지 못했습니다.")
                    return None
                
                html_content = s0_match.group(1)
                heat_match = re.search(r'(\d+\.\d+)\s*MJ/Nm', html_content)

                if heat_match:
                    return float(heat_match.group(1))
                
                _LOGGER.warning("DWR 응답 HTML에서 열량 값을 찾지 못했습니다.")
                return None
        except Exception as err:
            _LOGGER.error("%s부터 %s까지의 열량 데이터 조회 중 오류 발생: %s", start_date, end_date, err)
            return None

    async def _fetch_price_for_date(self, target_date: date) -> float | None:
        """
        특정 날짜의 열량단가를 조회합니다.
        """
        session_id = f"{random.randint(1000, 9999)}_{int(time.time() * 1000)}"
        
        payload = {
            "callCount": "1",
            "c0-scriptName": "ICGAS",
            "c0-methodName": "getChargecost",
            "c0-id": session_id,
            # --- 유일한 차이점: 경기 지역 코드는 '2' ---
            "c0-param0": "string:2",
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
                    return float(match.group(1))
                _LOGGER.warning("%s 날짜의 단가 데이터(s6)를 DWR 응답에서 찾지 못했습니다.", target_date)
                return None
        except Exception as err:
            _LOGGER.error("%s 날짜의 단가 조회 중 오류 발생: %s", target_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """전월 및 당월의 평균열량 데이터를 스크래핑합니다. (incheon_gas.py와 동일)"""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        
        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }
        _LOGGER.error("경기 도시가스의 열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """전월 및 당월의 열량단가 데이터를 스크래핑합니다. (incheon_gas.py와 동일)"""
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
        _LOGGER.error("경기 도시가스의 단가 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None