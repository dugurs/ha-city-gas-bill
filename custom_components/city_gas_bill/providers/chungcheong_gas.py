# custom_components/city_gas_bill/providers/chungcheong_gas.py

"""
충청에너지서비스(SK E&S) 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Final, Any

from bs4 import BeautifulSoup, Tag
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class ChungcheongGasProvider(GasProvider):
    """
    GasProvider를 상속받아 충청에너지서비스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_PRICE_PAGE = "https://www.skens.com/cheongju/rate/guide.do"  # 요금표 페이지
    URL_HEAT_API = "https://www.skens.com/cheongju/caloric/call_EBPP_044.do"  # 평균열량 API

    # 지원하는 지역 코드와 이름
    REGIONS: Final = {"279": "충청"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다. (파일 이름과 동일)"""
        return "chungcheong_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "충청에너지서비스 (SK E&S)"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """충청에너지서비스는 중앙난방 요금을 지원합니다."""
        return True

    async def _fetch_prices_from_html(self, html: str, heating_label: str) -> dict[str, float] | None:
        """
        요금표 HTML에서 취사 및 난방 단가를 파싱하는 내부 헬퍼 함수입니다.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            table = soup.select_one("#contents > div:nth-of-type(4) > table > tbody")
            if not table:
                LOGGER.error("충청에너지서비스 요금표 테이블(tbody)을 찾지 못했습니다.")
                return None

            prices = {}
            
            # 1. 취사 단가 직접 찾기
            cooking_label_cell = table.find("td", string="취사전용")
            if cooking_label_cell and isinstance(cooking_label_cell.parent, Tag):
                cooking_row_cells = cooking_label_cell.parent.find_all("td")
                if len(cooking_row_cells) >= 3:
                    prices['cooking'] = float(cooking_row_cells[2].get_text(strip=True))

            # 2. 난방 단가 직접 찾기 (개별난방 또는 중앙난방)
            heating_label_cell = table.find("td", string=heating_label)
            if heating_label_cell and isinstance(heating_label_cell.parent, Tag):
                heating_row_cells = heating_label_cell.parent.find_all("td")
                if len(heating_row_cells) >= 3:
                    prices['heating'] = float(heating_row_cells[2].get_text(strip=True))

            # 두 단가를 모두 찾았는지 최종 확인
            if 'cooking' in prices and 'heating' in prices:
                return prices
            
            LOGGER.error("충청에너지서비스 요금표 HTML에서 취사/난방 단가를 모두 찾지 못했습니다. (찾는 이름: %s)", heating_label)
            return None
            
        except (ValueError, TypeError, AttributeError) as e:
            LOGGER.error("충청에너지서비스 요금표 파싱 중 오류 발생: %s", e)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        충청에너지서비스 웹사이트에서 전월 및 당월의 열량단가를 스크래핑합니다.
        """
        if not self.region:
            LOGGER.error("충청에너지서비스 공급사에 지역 코드가 설정되지 않아 열량단가를 조회할 수 없습니다.")
            return None
        
        # --- START: 변경된 부분 ---
        # 주택난방(residential)의 경우 '개별난방' 텍스트를 찾도록 수정
        heating_label = "중앙난방" if self.heating_type in ["central_cogeneration", "central_chp"] else "개별난방"
        # --- END: 변경된 부분 ---

        try:
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            options = soup.select("select#item-select option")
            if not options:
                LOGGER.error("요금 조회 월(item-select) 목록을 찾지 못했습니다.")
                return None

            today = date.today()
            curr_month_str = today.strftime("%Y-%m-01")
            prev_month_str = (today - relativedelta(months=1)).strftime("%Y-%m-01")
            
            curr_month_code = next((opt['value'] for opt in options if opt.text == curr_month_str), None)
            prev_month_code = next((opt['value'] for opt in options if opt.text == prev_month_str), None)

            if not curr_month_code or not prev_month_code:
                LOGGER.error("당월(%s) 또는 전월(%s)의 요금 코드(item-select)를 찾지 못했습니다.", curr_month_str, prev_month_str)
                return None
            
            payload_curr = {"regionSeq": self.region, "seq": 0, "item-select": curr_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_curr) as response:
                response.raise_for_status()
                curr_prices = await self._fetch_prices_from_html(await response.text(), heating_label)

            payload_prev = {"regionSeq": self.region, "seq": 0, "item-select": prev_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_prev) as response:
                response.raise_for_status()
                prev_prices = await self._fetch_prices_from_html(await response.text(), heating_label)

            if not curr_prices or not prev_prices:
                return None

            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_prices['cooking'],
                DATA_CURR_MONTH_PRICE_HEATING: curr_prices['heating'],
                DATA_PREV_MONTH_PRICE_COOKING: prev_prices['cooking'],
                DATA_PREV_MONTH_PRICE_HEATING: prev_prices['heating'],
            }
        except Exception as err:
            LOGGER.error("충청에너지서비스 열량단가 스크래핑 중 오류 발생: %s", err)
            return None

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        주어진 기간의 평균열량을 API를 통해 조회하는 내부 헬퍼 함수입니다.
        """
        payload = {
            "I_FDATE": start_date.strftime("%Y%m%d"),
            "I_TDATE": end_date.strftime("%Y%m%d"),
            "I_CALOR": "D000",
        }
        try:
            async with self.websession.post(self.URL_HEAT_API, data=payload) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

                if data and data.get("list"):
                    return float(data["list"][0]["E_CALOR"])

                LOGGER.warning("충청에너지서비스 평균열량 API 응답에 'list' 데이터가 없습니다.")
                return None
        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 충청에너지서비스 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        충청에너지서비스 API에서 전월 및 당월의 평균열량 데이터를 가져옵니다.
        """
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

        LOGGER.error("충청에너지서비스의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    # 기본요금 조회 로직
    async def scrape_base_fee(self) -> float | None:
        """
        충청에너지서비스 웹사이트에서 현재 적용되는 기본요금을 스크래핑합니다.
        요금표 테이블에서 첫 번째 행의 기본요금을 기준으로 합니다.
        """
        try:
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            # 요금표 테이블의 첫 번째 행, 두 번째 열(td)을 선택합니다.
            base_fee_cell = soup.select_one("#contents > div:nth-of-type(4) > table > tbody > tr:first-child > td:nth-of-type(2)")
            
            if not base_fee_cell:
                LOGGER.error("충청에너지서비스 기본요금 테이블 셀을 찾지 못했습니다.")
                return None

            # 텍스트에서 콤마(,)를 제거하고 float으로 변환하여 반환합니다.
            base_fee_str = base_fee_cell.get_text(strip=True).replace(",", "")
            return float(base_fee_str)

        except (ValueError, TypeError) as e:
            LOGGER.error("충청에너지서비스 기본요금 파싱 중 값 변환 오류 발생: %s", e)
            return None
        except Exception as err:
            LOGGER.error("충청에너지서비스 기본요금 스크래핑 중 오류 발생: %s", err)
            return None

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        충청에너지서비스는 취사/난방 경계값이 없으므로 0을 반환합니다.
        """
        return 0.0