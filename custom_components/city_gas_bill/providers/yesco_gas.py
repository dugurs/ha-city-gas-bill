# custom_components/city_gas_bill/providers/yesco_gas.py

"""
예스코(Yesco) 도시가스 API 서버에서 데이터를 가져오는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
from typing import Final, Dict, Optional

import aiohttp
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
)

_LOGGER = logging.getLogger(__name__)

class YescoGasProvider(GasProvider):
    """
    GasProvider를 상속받아 예스코에 특화된 API 호출 로직을 구현한 클래스입니다.
    """
    API_URL = "https://www.lsyesco.com/Common/connApiServer.do"

    REGIONS: Final = {
        "1": "서울",
        "8": "경기",
    }
    
    def __init__(self, websession: aiohttp.ClientSession | None, region: str | None = None, usage_type: str | None = None):
        """
        공급사를 초기화하고, 선택된 지역 코드와 용도를 저장합니다.
        """
        super().__init__(websession, region=region, usage_type=usage_type)

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "yesco_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 기본 이름을 반환합니다."""
        return "예스코"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """예스코는 중앙난방 요금을 지원하지 않습니다."""
        return False

    async def _fetch_price_for_month(self, target_date: date) -> Optional[Dict[str, float]]:
        """
        특정 월의 '주택취사' 및 '주택난방' 열량단가를 조회하는 내부 헬퍼 함수입니다.
        """
        if not self.region:
            _LOGGER.error("예스코 공급사에 지역 코드가 설정되지 않았습니다. 열량단가를 조회할 수 없습니다.")
            return None
            
        payload = {"id": "E0006", "I_DATAB": target_date.strftime("%Y%m01")}
        
        try:
            async with self.websession.post(self.API_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("success"):
                    prices = {}
                    
                    for item in data["data"]["Tables"]["ITAB"]["tableMap"]:
                        if item.get("CITYCD") == self.region:
                            item_type = item.get("TYPENAME")
                            if item_type == "주택취사":
                                prices['cooking'] = float(item["AMOUNT_PERC"])
                            elif item_type == "주택난방":
                                prices['heating'] = float(item["AMOUNT_PERC"])
                    
                    if 'cooking' in prices and 'heating' in prices:
                        return prices
                    
                    _LOGGER.warning("%s 날짜의 주택취사/주택난방 단가 데이터를 모두 찾지 못했습니다. (지역코드: %s)", target_date, self.region)
                else:
                    _LOGGER.error("예스코 열량단가 API에서 오류 응답: %s", data.get("message"))
                
                return None
        except Exception as err:
            _LOGGER.error("%s 날짜의 예스코 열량단가 조회 중 오류 발생: %s", target_date, err)
            return None

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        특정 기간의 평균열량을 조회합니다.
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

        curr_prices = await self._fetch_price_for_month(first_day_curr_month)
        prev_prices = await self._fetch_price_for_month(first_day_prev_month)

        if curr_prices and prev_prices:
            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_prices['cooking'],
                DATA_CURR_MONTH_PRICE_HEATING: curr_prices['heating'],
                DATA_PREV_MONTH_PRICE_COOKING: prev_prices['cooking'],
                DATA_PREV_MONTH_PRICE_HEATING: prev_prices['heating'],
            }
        
        _LOGGER.error("예스코의 열량단가 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None
        
    async def scrape_base_fee(self) -> float | None:
        """예스코 API에서 현재 지역에 맞는 기본요금을 가져옵니다."""
        if not self.region:
            _LOGGER.error("예스코 공급사에 지역 코드가 설정되지 않아 기본요금을 조회할 수 없습니다.")
            return None

        today = date.today()
        payload = {"id": "E0006", "I_DATAB": today.strftime("%Y%m01")}

        try:
            async with self.websession.post(self.API_URL, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                if data.get("success"):
                    # API 응답의 모든 항목을 순회합니다.
                    for item in data["data"]["Tables"]["ITAB"]["tableMap"]:
                        # 'TYPENAME'이 '기본료'이고, 'CITYCD'가 현재 설정된 지역과 일치하는 항목을 찾습니다.
                        if item.get("TYPENAME") == "기본료" and item.get("CITYCD") == self.region:
                            return float(item["AMOUNT_PERC"])
                    
                    # 루프를 다 돌아도 일치하는 항목이 없는 경우
                    _LOGGER.error("예스코 API 응답에서 '%s' 지역의 기본료 항목을 찾지 못했습니다.", self.REGIONS.get(self.region, self.region))
                    return None
                else:
                    _LOGGER.error("예스코 기본요금 조회 API에서 오류 응답: %s", data.get("message"))
                    return None
        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.error("예스코 기본요금 데이터 파싱 중 오류 발생: %s", e)
            return None
        except Exception as err:
            _LOGGER.error("예스코 기본요금 조회 중 오류 발생: %s", err)
            return None