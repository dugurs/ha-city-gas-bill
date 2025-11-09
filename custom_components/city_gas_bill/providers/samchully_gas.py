# custom_components/city_gas_bill/providers/samchully_gas.py

"""
삼천리 도시가스 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
import re
from typing import Final, Any

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class SamchullyGasProvider(GasProvider):
    """
    GasProvider를 상속받아 삼천리 도시가스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_PRICE_PAGE = "https://www.samchully.co.kr/customer/gas/info/fee/system.do"
    URL_HEAT_API = "https://www.samchully.co.kr/customer/gas/info/fee/ajax/getUnitFee.do"

    # 지원하는 지역 코드와 이름
    REGIONS: Final = {"0001": "경기", "0002": "인천"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "samchully_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "삼천리 도시가스"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """삼천리는 중앙난방(공동주택) 요금을 지원합니다."""
        return True

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """주어진 기간의 평균열량을 API를 통해 조회하는 내부 헬퍼 함수입니다."""
        # API는 조회 종료일이 오늘이거나 미래인 경우 조회가 안되므로, 어제 날짜로 조정합니다.
        if end_date >= date.today():
            end_date = date.today() - timedelta(days=1)
        
        # 조정된 종료일이 시작일보다 빨라지는 경우(예: 매월 1일), 조회를 건너뜁니다.
        if end_date < start_date:
            LOGGER.debug("삼천리 평균열량 조회: 기간이 유효하지 않아 건너뜁니다 (%s ~ %s)", start_date, end_date)
            return None

        payload = {
            "findStartDate": start_date.strftime("%Y.%m.%d"),
            "findEndDate": end_date.strftime("%Y.%m.%d"),
        }
        try:
            async with self.websession.post(self.URL_HEAT_API, data=payload) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

                if data.get("result") == "SUCCESS" and "caloryFactor" in data:
                    # 응답값에 포함된 공백을 제거하고 float으로 변환합니다.
                    return float(data["caloryFactor"].strip())

                LOGGER.warning("삼천리 평균열량 API 응답에 유효한 데이터가 없습니다: %s", data)
                return None
        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 삼천리 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """삼천리 API에서 전월 및 당월의 평균열량 데이터를 가져옵니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        # 당월 데이터 조회가 실패하는 경우(예: 매월 1일), 전월 데이터로 임시 대체하여 안정성을 높입니다.
        if curr_heat is None and prev_heat is not None:
            LOGGER.debug("당월 평균열량 조회 실패, 전월 값(%s)으로 대체합니다.", prev_heat)
            curr_heat = prev_heat

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }

        LOGGER.error("삼천리의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def _fetch_prices_for_month(self, target_date: date) -> dict[str, float]:
        """특정 월의 열량단가를 스크래핑하는 내부 헬퍼 함수입니다. '변동없음'을 처리하며 항상 dict를 반환합니다."""
        params = {
            "region": self.region,
            "useTypeCod": "LRC1",
            "priceDate": target_date.strftime("%Y%m01")
        }
        prices = {} # 반환할 딕셔너리 초기화
        try:
            async with self.websession.get(self.URL_PRICE_PAGE, params=params) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")
            
            # 1. 취사 단가 추출
            cooking_price_td = soup.select_one("table.LRC1 td:nth-of-type(2)")
            if cooking_price_td:
                price_text = cooking_price_td.get_text(strip=True)
                if "변동없음" not in price_text:
                    prices['cooking'] = float(price_text)
                else:
                    LOGGER.debug("%s 취사단가 '변동없음' 확인. 값을 업데이트하지 않습니다.", target_date.strftime("%Y-%m"))
            
            # 2. 난방 단가 추출 (난방 타입에 따라 분기)
            heating_price_td = None
            if self.heating_type == "central_cogeneration":
                # 중앙난방 (열전용)
                heating_price_td = soup.select_one("table.LHOB tr:nth-of-type(3) td:nth-of-type(2)")
            elif self.heating_type == "central_chp":
                # 공동주택등열병합용
                heating_price_td = soup.select_one("table.LGA1 tr:nth-of-type(1) td:nth-of-type(3)")
            else:
                # 주택난방
                heating_price_td = soup.select_one("table.LRH1 td:nth-of-type(2)")

            if heating_price_td:
                price_text = heating_price_td.get_text(strip=True)
                if "변동없음" not in price_text:
                    prices['heating'] = float(price_text)
                else:
                    LOGGER.debug("%s 난방단가 '변동없음' 확인. 값을 업데이트하지 않습니다.", target_date.strftime("%Y-%m"))
            
        except Exception as err:
            LOGGER.error("%s의 삼천리 열량단가 스크래핑 중 오류: %s", target_date.strftime("%Y-%m"), err)
        
        return prices # 성공, 실패, 변동없음 모든 경우에 dict를 반환

    async def scrape_price_data(self) -> dict[str, float] | None:
        """전월 및 당월의 열량단가 데이터를 스크래핑합니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        first_day_prev_month = first_day_curr_month - relativedelta(months=1)

        curr_prices = await self._fetch_prices_for_month(first_day_curr_month)
        prev_prices = await self._fetch_prices_for_month(first_day_prev_month)

        result = {}
        if curr_prices:
            if 'cooking' in curr_prices: result[DATA_CURR_MONTH_PRICE_COOKING] = curr_prices['cooking']
            if 'heating' in curr_prices: result[DATA_CURR_MONTH_PRICE_HEATING] = curr_prices['heating']
        if prev_prices:
            if 'cooking' in prev_prices: result[DATA_PREV_MONTH_PRICE_COOKING] = prev_prices['cooking']
            if 'heating' in prev_prices: result[DATA_PREV_MONTH_PRICE_HEATING] = prev_prices['heating']
        
        # 최종 결과 딕셔너리가 비어있더라도 에러가 아니라 '변동없음' 상태이므로,
        # 그대로 반환하여 코디네이터가 기존 값을 덮어쓰지 않도록 합니다.
        if not result:
            LOGGER.info("삼천리 열량단가에 변동이 없어 업데이트할 데이터가 없습니다.")

        return result

    async def scrape_base_fee(self) -> float | None:
        """삼천리 웹사이트에서 현재 지역에 맞는 기본요금을 스크래핑합니다."""
        try:
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            region_name = self.REGIONS.get(self.region)
            if not region_name:
                LOGGER.error("알 수 없는 지역 코드(%s)입니다. 기본요금을 조회할 수 없습니다.", self.region)
                return None
                
            # '인천'은 '인천시'로, '경기'는 '경기도'로 검색 텍스트를 생성합니다.
            target_text = f"({region_name}시)" if region_name == "인천" else f"({region_name}도)"
            
            # 요금제 정보가 포함된 첫 번째 테이블 내의 모든 li 태그를 찾습니다.
            li_tags = soup.select("#gotoMainContents > table:nth-of-type(1) li")

            for li in li_tags:
                if target_text in li.get_text():
                    # 해당 지역 텍스트가 포함된 li 태그에서 숫자(요금)를 찾습니다.
                    match = re.search(r"([\d,]+)\s*원", li.get_text())
                    if match:
                        base_fee_str = match.group(1).replace(",", "")
                        return float(base_fee_str)
            
            LOGGER.error("기본요금 안내 문구에서 '%s' 지역의 요금 패턴을 찾지 못했습니다.", region_name)
            return None
        except Exception as err:
            LOGGER.error("삼천리 기본요금 스크래핑 중 오류 발생: %s", err)
            return None
    
    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        삼천리의 취사/난방 경계값을 반환합니다.
        이 값은 고지서 기준 고정값인 516 MJ 입니다.
        """
        return 516.0