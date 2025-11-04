# custom_components/city_gas_bill/providers/seoul_gas.py

"""
서울도시가스(Seoul Gas) 웹사이트에서 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import re  # 정규 표현식을 사용하기 위한 모듈
import logging

from bs4 import BeautifulSoup  # HTML 파싱을 위한 BeautifulSoup 라이브러리

from .base import GasProvider  # base.py에 정의된 부모 클래스를 가져옵니다.
from ..const import (
    # const.py에 정의된 데이터 키들을 가져와서 일관성을 유지합니다.
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE,
)

_LOGGER = logging.getLogger(__name__)

class SeoulGasProvider(GasProvider):
    """
    GasProvider를 상속받아 서울도시가스에 특화된 스크래핑 로직을 구현한 클래스입니다.
    """
    # 데이터를 가져올 웹사이트의 주소를 상수로 정의합니다.
    URL_HEAT = "https://www.seoulgas.co.kr/front/payment/selectHeat.do"    # 평균열량 조회 페이지
    URL_PRICE = "https://www.seoulgas.co.kr/front/payment/gasPayTable.do" # 요금표 페이지

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다. (파일 이름과 동일)"""
        return "seoul_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "서울도시가스"

    def _parse_heat_from_html(self, html_content: str, month_label: str) -> str | None:
        """
        평균열량 조회 페이지의 HTML 내용에서 실제 숫자 값을 파싱하는 내부 헬퍼 함수입니다.
        
        Args:
            html_content: 파싱할 전체 HTML 텍스트.
            month_label: 로그 메시지에 사용할 월 구분 라벨 (예: "current month").
        
        Returns:
            추출된 평균열량 값(문자열) 또는 실패 시 None.
        """
        # BeautifulSoup을 사용하여 HTML을 파싱 가능한 객체로 변환합니다.
        soup = BeautifulSoup(html_content, "html.parser")
        # CSS 선택자를 사용하여 id가 'content'인 div 태그를 찾습니다.
        content_div = soup.select_one("#content")
        if not content_div:
            _LOGGER.error("%s의 평균열량 데이터를 파싱하기 위한 메인 content div를 찾지 못했습니다.", month_label)
            return None
        
        # content div 안의 모든 <p> 태그(문단)를 순회합니다.
        for p_tag in content_div.find_all("p"):
            # <p> 태그의 텍스트에 "평균 열량"이라는 문자열이 포함되어 있는지 확인합니다.
            if "평균 열량" in p_tag.get_text():
                # 정규식을 사용하여 텍스트에서 소수점 형태의 숫자(예: "42.507")를 찾습니다.
                match = re.search(r"(\d+\.\d+)", p_tag.get_text())
                if match:
                    # 숫자를 찾았다면, 첫 번째 그룹(숫자 부분)을 반환합니다.
                    return match.group(1)
                    
        _LOGGER.error("%s의 평균열량 데이터를 파싱하지 못했습니다.", month_label)
        return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        서울도시가스 웹사이트에서 전월 및 당월의 평균열량 데이터를 스크래핑합니다.
        """
        today = date.today()
        first_day_curr_month = today.replace(day=1) # 이번 달 1일
        last_day_prev_month = first_day_curr_month - timedelta(days=1) # 지난달 말일
        first_day_prev_month = last_day_prev_month.replace(day=1) # 지난달 1일

        try:
            # --- 당월 평균열량 조회 ---
            # POST 요청에 필요한 파라미터 (조회 기간)
            params_curr = {"startDate": first_day_curr_month.strftime("%Y.%m.%d"), "endDate": today.strftime("%Y.%m.%d")}
            async with self.websession.post(self.URL_HEAT, data=params_curr) as response:
                response.raise_for_status() # HTTP 상태 코드가 200이 아니면 오류 발생
                # 응답받은 HTML을 헬퍼 함수에 넘겨 숫자 값을 추출합니다.
                curr_heat_str = self._parse_heat_from_html(await response.text(), "current month")

            # --- 전월 평균열량 조회 ---
            params_prev = {"startDate": first_day_prev_month.strftime("%Y.%m.%d"), "endDate": last_day_prev_month.strftime("%Y.%m.%d")}
            async with self.websession.post(self.URL_HEAT, data=params_prev) as response:
                response.raise_for_status()
                prev_heat_str = self._parse_heat_from_html(await response.text(), "previous month")

            # 두 값 중 하나라도 추출에 실패하면 None을 반환합니다.
            if not curr_heat_str or not prev_heat_str: return None
            
            # 성공적으로 추출한 문자열 값들을 float(실수)으로 변환하여 딕셔너리 형태로 반환합니다.
            return {
                DATA_CURR_MONTH_HEAT: float(curr_heat_str),
                DATA_PREV_MONTH_HEAT: float(prev_heat_str)
            }
        except Exception as err:
            _LOGGER.error("서울도시가스 평균열량 데이터 스크래핑 중 오류 발생: %s", err)
            return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        서울도시가스 웹사이트의 요금표에서 전월 및 당월의 열량단가(주택취사용)를 스크래핑합니다.
        """
        try:
            # 요금표 페이지에 GET 요청을 보냅니다.
            async with self.websession.get(self.URL_PRICE) as response:
                response.raise_for_status()
                soup = BeautifulSoup(await response.text(), "html.parser")
                
                # 요금표가 들어있는 테이블을 찾습니다.
                table = soup.select_one(".tblgas > table")
                if not table: return None
                
                # 테이블의 모든 헤더 셀(<th>)을 순회합니다.
                for th in table.find_all("th"):
                    # "취사"라는 단어가 포함된 헤더(주택취사용 요금 행)를 찾습니다.
                    if "취사" in th.get_text():
                        # 해당 헤더와 같은 행에 있는 모든 데이터 셀(<td>)들을 가져옵니다.
                        tds = th.find_next_siblings("td")
                        # 데이터 셀이 2개 이상(전월단가, 당월단가) 있는지 확인합니다.
                        if len(tds) >= 2:
                            # 각 셀의 텍스트에서 공백을 제거하고 float으로 변환하여 반환합니다.
                            return {
                                DATA_PREV_MONTH_PRICE: float(tds[0].get_text(strip=True)),
                                DATA_CURR_MONTH_PRICE: float(tds[1].get_text(strip=True))
                            }
                return None # "취사" 행을 찾지 못하면 None 반환
        except Exception as err:
            _LOGGER.error("서울도시가스 열량단가 데이터 스크래핑 중 오류 발생: %s", err)
            return None