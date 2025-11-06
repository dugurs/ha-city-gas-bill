# custom_components/city_gas_bill/providers/koone_gas.py

"""
코원에너지서비스(SK E&S) 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
from typing import Final, Any

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
)

_LOGGER = logging.getLogger(__name__)

class KooneGasProvider(GasProvider):
    """
    GasProvider를 상속받아 코원에너지서비스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_PRICE_PAGE = "https://www.skens.com/koone/rate/guide.do"  # 요금표 페이지
    URL_HEAT_API = "https://www.skens.com/koone/caloric/call_EBPP_044.do"  # 평균열량 API

    # 지원하는 지역 코드와 이름
    REGIONS: Final = {"274": "서울", "275": "경기"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다. (파일 이름과 동일)"""
        return "koone_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "코원에너지서비스 (SK E&S)"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """코원에너지서비스는 중앙난방 요금을 지원하지 않습니다."""
        return False

    async def _fetch_prices_from_html(self, html: str) -> dict[str, float] | None:
        """
        요금표 HTML에서 취사 및 난방 단가를 파싱하는 내부 헬퍼 함수입니다.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            # 요금표가 들어있는 테이블을 찾습니다.
            table = soup.select_one("#contents > div:nth-of-type(4) > table")
            if not table:
                _LOGGER.error("코원에너지서비스 요금표 테이블을 찾지 못했습니다.")
                return None

            rows = table.select("tbody tr")
            prices = {}

            # 테이블의 모든 행을 순회하며 필요한 데이터를 찾습니다.
            for row in rows:
                cells = row.find_all("td")
                if not cells or len(cells) < 3:
                    continue
                
                usage_name = cells[0].get_text(strip=True)
                # '주택용 취사' 또는 '주택용 난방' 행을 찾아 단가를 추출합니다.
                # [0]: 용도, [1]: 기본요금, [2]: 열량단가
                if usage_name == "주택용 취사":
                    prices['cooking'] = float(cells[2].get_text(strip=True))
                elif usage_name == "주택용 난방":
                    prices['heating'] = float(cells[2].get_text(strip=True))

            # 취사, 난방 요금을 모두 찾았는지 확인합니다.
            if 'cooking' in prices and 'heating' in prices:
                return prices
            
            _LOGGER.error("코원에너지서비스 요금표 HTML에서 취사/난방 단가를 모두 찾지 못했습니다.")
            return None
        except (ValueError, TypeError, IndexError) as e:
            _LOGGER.error("코원에너지서비스 요금표 파싱 중 오류 발생: %s", e)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        코원에너지서비스 웹사이트에서 전월 및 당월의 열량단가를 스크래핑합니다.
        """
        if not self.region:
            _LOGGER.error("코원에너지서비스 공급사에 지역 코드가 설정되지 않아 열량단가를 조회할 수 없습니다.")
            return None

        try:
            # 1. 먼저 요금 페이지에 접속하여 조회 가능한 월 목록(item-select)을 가져옵니다.
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            options = soup.select("select#item-select option")
            if not options:
                _LOGGER.error("요금 조회 월(item-select) 목록을 찾지 못했습니다.")
                return None

            # 2. 당월과 전월에 해당하는 `item-select` 코드를 찾습니다.
            today = date.today()
            curr_month_str = today.strftime("%Y-%m-01")
            prev_month_str = (today - relativedelta(months=1)).strftime("%Y-%m-01")
            
            curr_month_code = next((opt['value'] for opt in options if opt.text == curr_month_str), None)
            prev_month_code = next((opt['value'] for opt in options if opt.text == prev_month_str), None)

            if not curr_month_code or not prev_month_code:
                _LOGGER.error("당월(%s) 또는 전월(%s)의 요금 코드(item-select)를 찾지 못했습니다.", curr_month_str, prev_month_str)
                return None
            
            # 3. 찾은 코드를 사용하여 각 월의 요금 정보를 요청하고 파싱합니다.
            # 당월 요금 조회
            payload_curr = {"regionSeq": self.region, "seq": 0, "item-select": curr_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_curr) as response:
                response.raise_for_status()
                curr_prices = await self._fetch_prices_from_html(await response.text())

            # 전월 요금 조회
            payload_prev = {"regionSeq": self.region, "seq": 0, "item-select": prev_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_prev) as response:
                response.raise_for_status()
                prev_prices = await self._fetch_prices_from_html(await response.text())

            if not curr_prices or not prev_prices:
                return None

            # 4. 최종 데이터를 정해진 형식의 딕셔너리로 조합하여 반환합니다.
            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_prices['cooking'],
                DATA_CURR_MONTH_PRICE_HEATING: curr_prices['heating'],
                DATA_PREV_MONTH_PRICE_COOKING: prev_prices['cooking'],
                DATA_PREV_MONTH_PRICE_HEATING: prev_prices['heating'],
            }
        except Exception as err:
            _LOGGER.error("코원에너지서비스 열량단가 스크래핑 중 오류 발생: %s", err)
            return None

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        주어진 기간의 평균열량을 API를 통해 조회하는 내부 헬퍼 함수입니다.
        """
        payload = {
            "I_FDATE": start_date.strftime("%Y%m%d"),
            "I_TDATE": end_date.strftime("%Y%m%d"),
            "I_CALOR": "B000",
        }
        try:
            async with self.websession.post(self.URL_HEAT_API, data=payload) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

                if data and data.get("list"):
                    # API 응답에서 평균열량(E_CALOR) 값을 추출하여 float으로 변환
                    return float(data["list"][0]["E_CALOR"])

                _LOGGER.warning("코원에너지서비스 평균열량 API 응답에 'list' 데이터가 없습니다.")
                return None
        except Exception as err:
            _LOGGER.error("%s ~ %s 기간의 코원에너지서비스 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        코원에너지서비스 API에서 전월 및 당월의 평균열량 데이터를 가져옵니다.
        """
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        last_day_prev_month = first_day_curr_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        # 당월과 전월의 평균열량을 각각 조회합니다.
        curr_heat = await self._fetch_heat_for_period(first_day_curr_month, today)
        prev_heat = await self._fetch_heat_for_period(first_day_prev_month, last_day_prev_month)

        if curr_heat is not None and prev_heat is not None:
            return {
                DATA_CURR_MONTH_HEAT: curr_heat,
                DATA_PREV_MONTH_HEAT: prev_heat,
            }

        _LOGGER.error("코원에너지서비스의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None