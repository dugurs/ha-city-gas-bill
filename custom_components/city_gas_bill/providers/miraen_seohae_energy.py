# custom_components/city_gas_bill/providers/miraen_seohae_energy.py

"""
미래엔서해에너지 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Final

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    LOGGER,
)

class MiraenSeoHaeEnergyProvider(GasProvider):
    """
    GasProvider를 상속받아 미래엔서해에너지에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    URL_HEAT_PAGE = "https://miraense.com/index.php"
    REGIONS: Final = {"chungnam": "충남"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "miraen_seohae_energy"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "미래엔서해에너지"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """미래엔서해에너지는 중앙난방을 지원합니다."""
        return True

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """주어진 기간의 평균열량을 조회하는 내부 헬퍼 함수입니다."""
        params = {
            "page": "html",
            "mc": "44",
            "stDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        try:
            async with self.websession.get(self.URL_HEAT_PAGE, params=params) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")

            # XPath //*[@id="wrap2"].../span.blue 에 해당하는 CSS 선택자
            heat_span = soup.select_one("div.average_rbox > span.blue")
            if not heat_span:
                LOGGER.error("미래엔서해에너지 평균열량 결과값이 포함된 span 태그를 찾지 못했습니다.")
                return None
            
            return float(heat_span.get_text(strip=True))
        except Exception as err:
            LOGGER.error("%s ~ %s 기간의 미래엔서해에너지 평균열량 조회 중 오류: %s", start_date, end_date, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """미래엔서해에너지 웹사이트에서 전월 및 당월 평균열량 데이터를 가져옵니다."""
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
        
        LOGGER.error("미래엔서해에너지의 평균열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_price_data(self) -> dict[str, float]:
        """
        미래엔서해에너지는 자동 열량단가 조회를 지원하지 않으므로, 빈 dict를 반환하여
        사용자가 수동으로 입력한 값을 덮어쓰지 않도록 합니다.
        """
        LOGGER.warning(
            "미래엔서해에너지는 자동 열량단가 조회를 지원하지 않습니다. "
            "고지서를 참고하여 '전월/당월 열량단가' 엔티티 값을 수동으로 입력해주세요."
        )
        return {}

    async def scrape_base_fee(self) -> float | None:
        """미래엔서해에너지의 기본요금은 1,000원으로 고정되어 있습니다."""
        return 1000.0

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """미래엔서해에너지는 취사/난방 경계값이 없으므로 0을 반환합니다."""
        return 0.0