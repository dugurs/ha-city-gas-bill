# custom_components/city_gas_bill/providers/chungbuk_gas.py

"""
참빛충북도시가스 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date
import re
from typing import Final

from bs4 import BeautifulSoup, Tag
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class ChungbukGasProvider(GasProvider):
    """
    GasProvider를 상속받아 참빛충북도시가스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    URL_PRICE_PAGE = "https://www.ccbgas.co.kr/charge/charge01.do"
    REGIONS: Final = {"chungbuk": "충북"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "chungbuk_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "참빛충북도시가스"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """참빛충북도시가스는 중앙난방을 지원합니다."""
        return True

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """참빛충북도시가스는 자동 평균열량 조회를 지원하지 않습니다."""
        LOGGER.warning(
            "참빛충북도시가스는 자동 평균열량 조회를 지원하지 않습니다. "
            "고지서를 참고하여 '전월/당월 평균열량' 엔티티 값을 수동으로 입력해주세요."
        )
        return None

    async def _fetch_prices_for_month(self, target_date: date) -> dict[str, float] | None:
        """특정 월의 열량단가를 스크래핑하는 내부 헬퍼 함수입니다."""
        params = {"ym": target_date.strftime("%Y%m")}
        try:
            async with self.websession.get(self.URL_PRICE_PAGE, params=params) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            # 페이지 내 모든 테이블을 찾은 후, 내용("취사용")을 기반으로 정확한 요금표 테이블을 식별합니다.
            target_table = None
            for table in soup.find_all("table"):
                if table.find("td", string=re.compile(r"\s*취사용\s*")):
                    target_table = table
                    break
            
            if not target_table:
                LOGGER.error("%s의 열량단가 테이블을 찾지 못했습니다.", target_date.strftime("%Y-%m"))
                return None
            
            prices = {}

            # "취사용" 텍스트를 포함하는 td를 기준으로 행을 찾습니다.
            cooking_label_cell = target_table.find("td", string=re.compile(r"\s*취사용\s*"))
            if not cooking_label_cell:
                # 위에서 테이블을 찾았으므로 이 에러는 발생하지 않아야 함
                LOGGER.error("요금표에서 '취사용' 셀을 찾지 못했습니다.")
                return None

            cooking_row = cooking_label_cell.find_parent("tr")
            if not isinstance(cooking_row, Tag):
                LOGGER.error("'취사용' 셀의 부모 행을 찾지 못했습니다.")
                return None

            # 취사용 단가: "취사용" 행의 세 번째 td
            cooking_price_cells = cooking_row.find_all("td")
            if len(cooking_price_cells) > 2:
                prices['cooking'] = float(cooking_price_cells[2].get_text(strip=True))
            else:
                LOGGER.error("취사용 단가 셀을 찾지 못했습니다.")
                return None

            # 난방용 행: "취사용" 행의 다음 행
            heating_row = cooking_row.find_next_sibling("tr")
            if not isinstance(heating_row, Tag):
                LOGGER.error("난방용 요금 행을 찾지 못했습니다.")
                return None
            
            # 중앙난방용 행: 난방용 행의 다음 행
            central_heating_row = heating_row.find_next_sibling("tr")
            if not isinstance(central_heating_row, Tag):
                LOGGER.error("중앙난방용 요금 행을 찾지 못했습니다.")
                return None

            # 사용량 타입에 따라 난방/중앙난방 단가 추출
            if self.usage_type == 'central':
                # 중앙난방: 중앙난방용 행의 마지막 td
                heating_price_cell = central_heating_row.find_all("td")[-1]
            else:
                # 주택난방: 난방용 행의 마지막 td
                heating_price_cell = heating_row.find_all("td")[-1]

            if heating_price_cell:
                prices['heating'] = float(heating_price_cell.get_text(strip=True))
            else:
                LOGGER.error("난방/중앙난방 단가 셀을 찾지 못했습니다.")
                return None

            return prices

        except Exception as err:
            LOGGER.error("%s의 참빛충북도시가스 열량단가 스크래핑 중 오류: %s", target_date.strftime("%Y-%m"), err)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """전월 및 당월의 열량단가 데이터를 스크래핑합니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        first_day_prev_month = first_day_curr_month - relativedelta(months=1)

        curr_prices = await self._fetch_prices_for_month(first_day_curr_month)
        prev_prices = await self._fetch_prices_for_month(first_day_prev_month)

        if curr_prices and prev_prices:
            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_prices['cooking'],
                DATA_CURR_MONTH_PRICE_HEATING: curr_prices['heating'],
                DATA_PREV_MONTH_PRICE_COOKING: prev_prices['cooking'],
                DATA_PREV_MONTH_PRICE_HEATING: prev_prices['heating'],
            }
        
        LOGGER.error("참빛충북도시가스의 열량단가 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_base_fee(self) -> float | None:
        """참빛충북도시가스 웹사이트에서 기본요금을 스크래핑합니다."""
        try:
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")
            
            # 특정 클래스에 의존하지 않고, 페이지 내 모든 li 태그를 검색하는 방식으로 복원합니다.
            li_tags = soup.find_all("li")
            for li in li_tags:
                text = li.get_text()
                if "기본요금" in text and "취사용" in text:
                    match = re.search(r"\((\s*[\d,]+)\s*원/월\)", text)
                    if match:
                        fee_str = match.group(1).replace(",", "").strip()
                        return float(fee_str)

            LOGGER.error("기본요금 안내 문구에서 요금 패턴을 찾지 못했습니다.")
            return None
        except Exception as err:
            LOGGER.error("참빛충북도시가스 기본요금 스크래핑 중 오류 발생: %s", err)
            return None

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """참빛충북도시가스는 취사/난방 요금 구분이 없으므로 0을 반환합니다."""
        return 0.0