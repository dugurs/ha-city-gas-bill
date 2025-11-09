# custom_components/city_gas_bill/providers/daeryun_ens.py

"""
대륜이엔에스 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta # --- START: 수정된 코드 ---
import re
from typing import Final

from bs4 import BeautifulSoup

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    LOGGER, # 공용 로거 사용
)

class DaeryunENSProvider(GasProvider):
    """
    GasProvider를 상속받아 대륜이엔에스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_HEAT = "https://www.daeryunens.com/daeryunens/chargespaid/temperature.asp"
    URL_PRICE_INFO_PAGE = "https://www.daeryunens.com/daeryunens/bbs/bbs_list.asp?bbs_code=54"

    # 지원하는 지역 코드와 이름
    REGIONS: Final = {"seoul": "서울", "gyeonggi": "경기"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "daeryun_ens"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "대륜이엔에스"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """대륜이엔에스는 중앙난방을 지원하지 않습니다."""
        return False

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """주어진 기간의 평균열량을 조회하는 내부 헬퍼 함수입니다."""
        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        }
        try:
            async with self.websession.get(self.URL_HEAT, params=params) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            # XPath //*[@id="tempFrm"]/div/p[2]/span[2] 에 해당하는 CSS 선택자
            span_tag = soup.select_one("#tempFrm > div > p:nth-of-type(2) > span:nth-of-type(2)")
            if not span_tag:
                LOGGER.error("대륜이엔에스 평균열량 결과값이 포함된 span 태그를 찾지 못했습니다.")
                return None
            
            # "42.438&nbsp;MJN" 형태의 텍스트에서 숫자 부분만 추출
            text_content = span_tag.get_text(strip=True)
            match = re.search(r"([\d\.]+)", text_content)
            if match:
                return float(match.group(1))

            LOGGER.error("평균열량 텍스트('%s')에서 숫자 값을 추출하지 못했습니다.", text_content)
            return None

        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 대륜이엔에스 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """대륜이엔에스 웹사이트에서 전월 및 당월 평균열량 데이터를 가져옵니다."""
        today = date.today()
        # 대륜이엔에스는 당일 조회가 가능하므로, end_date를 그대로 사용합니다.
        first_day_curr_month = today.replace(day=1)
        
        # relativedelta 대신 timedelta를 사용하여 정확한 전월 말일을 계산합니다.
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }
        
        LOGGER.error("대륜이엔에스의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """대륜이엔에스는 자동 열량단가 조회를 지원하지 않습니다."""
        LOGGER.warning("대륜이엔에스는 자동 열량단가 조회를 지원하지 않습니다. ")
        LOGGER.warning("아래 링크에서 요금표 확인 후 '전월/당월 열량단가' 엔티티 값을 수동으로 입력해주세요")
        LOGGER.warning("%s",self.URL_PRICE_INFO_PAGE)
        return None

    async def scrape_base_fee(self) -> float | None:
        """대륜이엔에스의 기본요금은 1,250원으로 고정되어 있습니다."""
        return 1250.0

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """대륜이엔에스는 취사/난방 요금 구분이 없으므로 0을 반환합니다."""
        return 0.0