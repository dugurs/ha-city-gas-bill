# custom_components/city_gas_bill/providers/yesco_gas.py

"""
예스코(Yesco) 도시가스 API 서버에서 데이터를 가져오는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
from typing import Final # Final 임포트

import aiohttp
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE,
)

_LOGGER = logging.getLogger(__name__)

class YescoGasProvider(GasProvider):
    """
    GasProvider를 상속받아 예스코에 특화된 API 호출 로직을 구현한 클래스입니다.
    """
    API_URL = "https://www.lsyesco.com/Common/connApiServer.do"

    # [추가] 이 공급사가 지원하는 지역 목록을 정의합니다.
    # config_flow.py에서 이 정보를 사용하여 동적으로 UI 옵션을 생성합니다.
    # key: API 호출에 사용할 지역 코드, value: UI에 표시될 이름
    REGIONS: Final = {
        "1": "서울",
        "8": "경기",
    }
    
    # __init__ 메소드에서 지역(region) 코드를 받도록 수정합니다.
    def __init__(self, websession: aiohttp.ClientSession | None, region: str | None = None):
        """
        공급사를 초기화하고, 선택된 지역 코드를 저장합니다.
        """
        super().__init__(websession, region=region)

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "yesco_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 기본 이름을 반환합니다."""
        return "예스코"

    async def _fetch_price_for_month(self, target_date: date) -> float | None:
        """
        특정 월의 '주택취사' 열량단가를 조회하는 내부 헬퍼 함수입니다.
        """
        # [수정] 지역 코드가 설정되지 않았으면 오류를 로깅하고 중단합니다.
        if not self.region:
            _LOGGER.error("예스코 공급사에 지역 코드가 설정되지 않았습니다. 열량단가를 조회할 수 없습니다.")
            return None
            
        payload = {"id": "E0006", "I_DATAB": target_date.strftime("%Y%m01")}
        
        try:
            async with self.websession.post(self.API_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("success"):
                    for item in data["data"]["Tables"]["ITAB"]["tableMap"]:
                        # self.region을 사용하여 올바른 지역의 단가를 찾습니다.
                        if item.get("TYPENAME") == "주택취사" and item.get("CITYCD") == self.region:
                            _LOGGER.debug("예스코 %s 지역(%s)의 주택취사 단가 %s를 찾았습니다.", 
                                          self.REGIONS.get(self.region, "알수없음"), self.region, item["AMOUNT_PERC"])
                            return float(item["AMOUNT_PERC"])
                    _LOGGER.warning("%s 날짜의 주택취사 단가 데이터를 찾지 못했습니다. (지역코드: %s)", target_date, self.region)
                else:
                    _LOGGER.error("예스코 열량단가 API에서 오류 응답: %s", data.get("message"))
                
                return None
        except Exception as err:
            _LOGGER.error("%s 날짜의 예스코 열량단가 조회 중 오류 발생: %s", target_date, err)
            return None

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        특정 기간의 평균열량을 조회합니다. (열량은 지역과 무관하므로 수정 없음)
        """
        payload = {
            "id": "E0005",
            "F_CALDT": start_date.strftime("%Y%m%d"),
            "T_CALDT": end_date.strftime("%Y%m%d")
        }

        try:
            async with self.websession.post(self.API_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("success") and data["data"]["Parameters"].get("O_RTNCD") == "00":
                    return float(data["data"]["Parameters"]["O_CALORIEAV"])
                else:
                    _LOGGER.error("예스코 평균열량 API에서 오류 응답: %s", data.get("message"))
                    return None
        except Exception as err:
            _LOGGER.error("%s ~ %s 기간의 예스코 평균열량 조회 중 오류 발생: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """전월 및 당월 평균열량 데이터를 가져옵니다."""
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
        
        _LOGGER.error("예스코의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """전월 및 당월 열량단가 데이터를 가져옵니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        first_day_prev_month = first_day_curr_month - relativedelta(months=1)

        curr_month_price = await self._fetch_price_for_month(first_day_curr_month)
        prev_month_price = await self._fetch_price_for_month(first_day_prev_month)

        if curr_month_price is not None and prev_month_price is not None:
            return {
                DATA_CURR_MONTH_PRICE: curr_month_price,
                DATA_PREV_MONTH_PRICE: prev_month_price,
            }
        
        _LOGGER.error("예스코의 열량단가 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None