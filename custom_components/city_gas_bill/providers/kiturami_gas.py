# custom_components/city_gas_bill/providers/kiturami_gas.py

"""
귀뚜라미에너지 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
import re
from typing import Final

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class KituramiGasProvider(GasProvider):
    """
    GasProvider를 상속받아 귀뚜라미에너지에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_PRICE_PAGE = "https://kituramienergy.co.kr/sub/cgas_guide/c_guid_02_02_01.asp"
    URL_HEAT_PAGE = "https://kituramienergy.co.kr/sub/cgas_guide/c_guid_02_02_02.asp"
    
    # 귀뚜라미에너지는 서울 지역만 서비스합니다.
    REGIONS: Final = {"seoul": "서울"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "kiturami_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "귀뚜라미에너지"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """귀뚜라미에너지는 중앙난방을 지원하지 않습니다."""
        return False

    def _get_month_part_no(self, target_date: date) -> int:
        """
        기준이 되는 '2025년 11월'과 대상 날짜의 월 차이를 계산하여
        요금표 div의 ID 번호(partXX)를 계산합니다.
        """
        # 기준점 설정 (요청 명세 기반)
        anchor_date = date(2025, 11, 1)
        anchor_no = 77
        
        # 대상 날짜를 해당 월의 1일로 맞춥니다.
        target_month_start = target_date.replace(day=1)
        
        # 두 날짜 사이의 월 차이를 계산합니다.
        # relativedelta는 두 날짜의 차이를 년, 월, 일 단위로 알려줍니다.
        diff = relativedelta(anchor_date, target_month_start)
        month_diff = diff.years * 12 + diff.months
        
        # 기준 번호에서 월 차이를 빼서 대상 월의 번호를 계산합니다.
        return anchor_no - month_diff

    async def scrape_price_data(self) -> dict[str, float] | None:
        """귀뚜라미에너지 웹사이트에서 전월 및 당월 열량단가를 스크래핑합니다."""
        try:
            # 요금표 페이지의 전체 HTML을 한 번만 가져옵니다.
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            today = date.today()
            
            # 당월과 전월의 part ID 번호를 계산합니다.
            curr_part_no = self._get_month_part_no(today)
            prev_part_no = self._get_month_part_no(today - relativedelta(months=1))
            
            # 당월 요금표 테이블을 찾습니다.
            curr_table = soup.select_one(f"#part{curr_part_no} table")
            if not curr_table:
                LOGGER.error("당월(part%s) 요금표 테이블을 찾지 못했습니다.", curr_part_no)
                return None
            
            # 전월 요금표 테이블을 찾습니다.
            prev_table = soup.select_one(f"#part{prev_part_no} table")
            if not prev_table:
                LOGGER.error("전월(part%s) 요금표 테이블을 찾지 못했습니다.", prev_part_no)
                return None

            # 각 테이블에서 단가 값을 추출합니다.
            # td[0]: 구분, td[1]: 전월단가, td[2]: 당월단가
            curr_price = float(curr_table.select_one("tbody tr:first-child td:nth-of-type(3)").get_text(strip=True))
            prev_price = float(prev_table.select_one("tbody tr:first-child td:nth-of-type(3)").get_text(strip=True))

            # 귀뚜라미는 취사/난방 단가가 동일합니다.
            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_price,
                DATA_CURR_MONTH_PRICE_HEATING: curr_price,
                DATA_PREV_MONTH_PRICE_COOKING: prev_price,
                DATA_PREV_MONTH_PRICE_HEATING: prev_price,
            }
        except (ValueError, TypeError, AttributeError) as e:
            LOGGER.error("귀뚜라미에너지 열량단가 파싱 중 오류 발생: %s", e)
            return None
        except Exception as err:
            LOGGER.error("귀뚜라미에너지 열량단가 스크래핑 중 오류 발생: %s", err)
            return None

    async def scrape_base_fee(self) -> float | None:
        """귀뚜라미에너지 웹사이트에서 기본요금을 스크래핑합니다."""
        try:
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            # 기본요금 안내 문구가 있는 p 태그를 찾습니다.
            p_tag = soup.select_one("div.contents_area > p.p_style")
            if not p_tag:
                LOGGER.error("기본요금 안내 문구가 포함된 p 태그를 찾지 못했습니다.")
                return None

            text_content = p_tag.get_text(strip=True)
            match = re.search(r"([\d,]+)\s*원", text_content)
            
            if match:
                base_fee_str = match.group(1).replace(",", "")
                return float(base_fee_str)

            LOGGER.error("기본요금 안내 문구에서 요금 숫자를 찾지 못했습니다.")
            return None
        except Exception as err:
            LOGGER.error("귀뚜라미에너지 기본요금 스크래핑 중 오류 발생: %s", err)
            return None


    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """주어진 기간의 평균열량을 조회하는 내부 헬퍼 함수입니다."""
        try:
            adjusted_end_date = end_date
            # 만약 조회 종료일이 오늘과 같다면, 어제 날짜로 조회합니다.
            # (당일 데이터는 집계되지 않는 경우가 많기 때문입니다.)
            if end_date == date.today():
                adjusted_end_date = end_date - timedelta(days=1)
            
            # 조정된 종료일이 시작일보다 빨라지는 경우(예: 매월 1일), 조회를 건너뜁니다.
            if adjusted_end_date < start_date:
                LOGGER.debug(
                    "조정된 평균열량 조회 종료일(%s)이 시작일(%s)보다 빨라 조회를 생략합니다.",
                    adjusted_end_date, start_date
                )
                return None

            payload = {
                "f_date": start_date.strftime("%Y-%m-%d"),
                "t_date": adjusted_end_date.strftime("%Y-%m-%d")
            }
            async with self.websession.post(self.URL_HEAT_PAGE, data=payload) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")
            
            heat_span = soup.select_one("div.contents_area > div.grey_box02.mb20 > span.blue")
            if not heat_span:
                LOGGER.error("평균열량 결과값이 포함된 span 태그를 찾지 못했습니다.")
                return None
            
            return float(heat_span.get_text(strip=True))
        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 귀뚜라미에너지 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """귀뚜라미에너지 웹사이트에서 전월 및 당월 평균열량 데이터를 가져옵니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        last_day_prev_month = first_day_curr_month - relativedelta(months=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }
        
        LOGGER.error("귀뚜라미에너지의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        귀뚜라미에너지의 취사/난방 경계값을 반환합니다.
        귀뚜라미에너지는 취사/난방 요금 구분이 없으므로 0을 반환합니다.
        """
        return 0.0