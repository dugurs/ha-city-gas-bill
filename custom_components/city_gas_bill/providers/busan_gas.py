# custom_components/city_gas_bill/providers/busan_gas.py

"""
부산도시가스(SK E&S) 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import logging
from typing import Final, Any
import re # 정규식 모듈 임포트

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class BusanGasProvider(GasProvider):
    """
    GasProvider를 상속받아 부산도시가스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터 스크래핑을 위한 URL
    URL_PRICE_PAGE = "https://www.skens.com/busan/rate/guide.do"  # 요금표 페이지
    URL_HEAT_API = "https://www.skens.com/busan/caloric/call_EBPP_044.do"  # 평균열량 API

    # 지원하는 지역 코드와 이름
    REGIONS: Final = {"276": "부산"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다. (파일 이름과 동일)"""
        return "busan_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "부산도시가스 (SK E&S)"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """부산도시가스는 중앙난방 요금을 지원합니다."""
        return True

    async def _fetch_prices_from_html(self, html: str, heating_label: str) -> dict[str, float] | None:
        """
        요금표 HTML에서 취사 및 난방 단가를 파싱하는 내부 헬퍼 함수입니다.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            # 요금표가 들어있는 테이블을 찾습니다.
            table = soup.select_one("#contents > div:nth-of-type(4) > table")
            if not table:
                LOGGER.error("부산도시가스 요금표 테이블을 찾지 못했습니다.")
                return None

            rows = table.select("tbody tr")
            prices = {}

            # 테이블의 모든 행을 순회하며 필요한 데이터를 찾습니다.
            for row in rows:
                cells = row.find_all("td")
                # 부산도시가스는 [용도, 단가] 2개의 열만 필요합니다.
                if not cells or len(cells) < 2:
                    continue
                
                usage_name = cells[0].get_text(strip=True)
                
                # '취사전용' 행을 찾아 취사 단가를 추출합니다.
                if usage_name == "취사전용":
                    prices['cooking'] = float(cells[1].get_text(strip=True))
                # 사용자가 선택한 용도(주택난방/중앙난방)에 맞는 행을 찾아 난방 단가를 추출합니다.
                elif usage_name == heating_label:
                    prices['heating'] = float(cells[1].get_text(strip=True))

            # 취사, 난방 요금을 모두 찾았는지 확인합니다.
            if 'cooking' in prices and 'heating' in prices:
                return prices
            
            LOGGER.error("부산도시가스 요금표 HTML에서 취사/난방 단가(%s)를 모두 찾지 못했습니다.", heating_label)
            return None
        except (ValueError, TypeError, IndexError) as e:
            LOGGER.error("부산도시가스 요금표 파싱 중 오류 발생: %s", e)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        부산도시가스 웹사이트에서 전월 및 당월의 열량단가를 스크래핑합니다.
        """
        if not self.region:
            LOGGER.error("부산도시가스 공급사에 지역 코드가 설정되지 않아 열량단가를 조회할 수 없습니다.")
            return None
        
        # 사용자가 설정에서 선택한 난방 타입에 따라 파싱할 난방 요금의 테이블 행 이름 결정
        heating_label = "중앙난방" if self.heating_type == "central" else "난방전용"

        try:
            # 1. 먼저 요금 페이지에 접속하여 조회 가능한 월 목록(item-select)을 가져옵니다.
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            options = soup.select("select#item-select option")
            if not options:
                LOGGER.error("요금 조회 월(item-select) 목록을 찾지 못했습니다.")
                return None

            # 2. 당월과 전월에 해당하는 `item-select` 코드를 찾습니다.
            today = date.today()
            curr_month_str = today.strftime("%Y-%m-01")
            prev_month_str = (today - relativedelta(months=1)).strftime("%Y-%m-01")
            
            curr_month_code = next((opt['value'] for opt in options if opt.text == curr_month_str), None)
            prev_month_code = next((opt['value'] for opt in options if opt.text == prev_month_str), None)

            if not curr_month_code or not prev_month_code:
                LOGGER.error("당월(%s) 또는 전월(%s)의 요금 코드(item-select)를 찾지 못했습니다.", curr_month_str, prev_month_str)
                return None
            
            # 3. 찾은 코드를 사용하여 각 월의 요금 정보를 요청하고 파싱합니다.
            # 당월 요금 조회
            payload_curr = {"regionSeq": self.region, "seq": 0, "item-select": curr_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_curr) as response:
                response.raise_for_status()
                curr_prices = await self._fetch_prices_from_html(await response.text(), heating_label)

            # 전월 요금 조회
            payload_prev = {"regionSeq": self.region, "seq": 0, "item-select": prev_month_code}
            async with self.websession.post(self.URL_PRICE_PAGE, data=payload_prev) as response:
                response.raise_for_status()
                prev_prices = await self._fetch_prices_from_html(await response.text(), heating_label)

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
            LOGGER.error("부산도시가스 열량단가 스크래핑 중 오류 발생: %s", err)
            return None

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        주어진 기간의 평균열량을 API를 통해 조회하는 내부 헬퍼 함수입니다.
        """
        # 부산도시가스는 I_CALOR 코드로 'C000'을 사용합니다.
        payload = {
            "I_FDATE": start_date.strftime("%Y%m%d"),
            "I_TDATE": end_date.strftime("%Y%m%d"),
            "I_CALOR": "C000",
        }
        try:
            async with self.websession.post(self.URL_HEAT_API, data=payload) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

                if data and data.get("list"):
                    # API 응답에서 평균열량(E_CALOR) 값을 추출하여 float으로 변환
                    return float(data["list"][0]["E_CALOR"])

                LOGGER.warning("부산도시가스 평균열량 API 응답에 'list' 데이터가 없습니다.")
                return None
        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 부산도시가스 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        부산도시가스 API에서 전월 및 당월의 평균열량 데이터를 가져옵니다.
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

        LOGGER.error("부산도시가스의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_base_fee(self) -> float | None:
        """
        부산도시가스 웹사이트에서 현재 적용되는 기본요금을 스크래핑합니다.
        HTML에 포함된 JavaScript 코드에서 동적으로 설정되는 안내 문구의 내용을 파싱합니다.
        """
        try:
            # 기본요금은 현재 시점의 값만 필요하므로, GET 요청으로 최신 페이지를 가져옵니다.
            async with self.websession.get(self.URL_PRICE_PAGE) as response:
                response.raise_for_status()
                html_text = await response.text()

            # JavaScript 코드 `$("#baseDesc").html(...)` 패턴을 찾기 위한 정규식
            # re.DOTALL 옵션은 .이 줄바꿈 문자도 포함하도록 하여 여러 줄에 걸친 문자열도 찾게 합니다.
            script_match = re.search(r'\$\("#baseDesc"\)\.html\(([\'"])(.*?)\1\)', html_text, re.DOTALL)
            
            if not script_match:
                LOGGER.error("부산도시가스 기본요금 JavaScript 코드('#baseDesc').html(...)를 찾지 못했습니다.")
                return None

            # 정규식의 두 번째 그룹이 실제 안내 문구 내용입니다.
            text_content = script_match.group(2)
            
            # 안내 문구에서 숫자와 '원'이 함께 있는 부분을 찾습니다.
            fee_match = re.search(r"([\d,]+)\s*원", text_content)
            
            if fee_match:
                # 찾은 숫자 문자열에서 콤마(,)를 제거하고 float으로 변환하여 반환합니다.
                base_fee_str = fee_match.group(1).replace(",", "")
                return float(base_fee_str)

            LOGGER.error("기본요금 스크립트 내용에서 요금 숫자를 찾지 못했습니다: %s", text_content)
            return None

        except (ValueError, TypeError) as e:
            LOGGER.error("부산도시가스 기본요금 파싱 중 값 변환 오류 발생: %s", e)
            return None
        except Exception as err:
            LOGGER.error("부산도시가스 기본요금 스크래핑 중 오류 발생: %s", err)
            return None

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        부산도시가스의 취사/난방 경계값을 반환합니다.
        '취사전용'과 '난방전용' 요금제가 구분되어 있으므로 경계값은 0입니다.
        """
        return 0.0