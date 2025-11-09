# custom_components/city_gas_bill/providers/incheon_gas.py

"""
인천도시가스(코원에너지서비스) 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations
from datetime import date, timedelta
import time
import random
import re  # 정규 표현식 사용
import logging
from typing import Final # Final 임포트

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

from .base import GasProvider
from ..const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING,
    LOGGER, # 공용 로거 사용
)

class IncheonGasProvider(GasProvider):
    """
    인천도시가스(코원에너지서비스)의 DWR 호출을 통해 데이터를 가져오는 클래스입니다.
    """
    
    # 데이터 조회를 위한 DWR 엔드포인트 URL
    URL_PRICE = "https://icgas.co.kr:8443/recruit/dwr/exec/ICGAS.getChargecost.dwr"
    URL_HEAT = "https://icgas.co.kr:8443/recruit/dwr/exec/PAY.getSimplePayCalListData.dwr"
    URL_BASE_FEE_PAGE = "https://icgas.co.kr:8443/recruit/chargecost.jsp"
    REGIONS: Final = {"1": "인천","2": "경기",}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "incheon_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "인천도시가스(코원)"

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """인천도시가스는 주택용 중앙난방 요금을 지원합니다."""
        return True

    async def _fetch_heat_for_period(self, start_date: date, end_date: date) -> float | None:
        """
        특정 기간 동안의 평균열량을 조회하는 내부 헬퍼 함수입니다.
        """
        # DWR 호출 시 고유한 세션 ID가 필요하므로, 랜덤 숫자와 현재 시간을 조합하여 생성합니다.
        session_id = f"{random.randint(1000, 9999)}_{int(time.time() * 1000)}"
        
        # 서버에 보낼 POST 요청 본문(payload)을 정의합니다.
        payload = {
            "callCount": "1",
            "c0-scriptName": "PAY", # 호출할 DWR 스크립트 이름
            "c0-methodName": "getSimplePayCalListData", # 호출할 메소드 이름
            "c0-id": session_id,
            "c0-param0": f"string:{start_date.strftime('%Y%m%d')}", # 파라미터 1: 조회 시작일
            "c0-param1": f"string:{end_date.strftime('%Y%m%d')}",   # 파라미터 2: 조회 종료일
            "xml": "true",
        }

        try:
            async with self.websession.post(self.URL_HEAT, data=payload) as response:
                response.raise_for_status()
                response_text = await response.text()

                # 응답으로 온 자바스크립트 텍스트에서 'var s0="..."' 부분을 찾습니다.
                # s0 변수 안에는 결과값이 담긴 HTML 조각이 들어있습니다.
                s0_match = re.search(r'var s0="(.+?)";', response_text, re.DOTALL)
                if not s0_match:
                    LOGGER.warning("DWR 응답에서 s0 변수(열량 데이터)를 찾지 못했습니다.")
                    return None
                
                html_content = s0_match.group(1) # 추출한 HTML 조각
                
                # HTML 조각 안에서 '42.507 MJ/Nm' 형태의 텍스트를 찾아 숫자 부분만 추출합니다.
                heat_match = re.search(r'(\d+\.\d+)\s*MJ/Nm', html_content)
                if heat_match:
                    return float(heat_match.group(1))
                
                LOGGER.warning("DWR 응답 HTML에서 열량 값을 찾지 못했습니다.")
                return None
        except Exception as err:
            LOGGER.error("%s부터 %s까지의 열량 데이터 조회 중 오류 발생: %s", start_date, end_date, err)
            return None

    async def _fetch_price_for_date(self, target_date: date, usage_type_str: str) -> float | None:
        """
        특정 날짜와 용도의 열량단가를 조회하는 내부 헬퍼 함수입니다.
        """
        session_id = f"{random.randint(1000, 9999)}_{int(time.time() * 1000)}"
        
        payload = {
            "callCount": "1",
            "c0-scriptName": "ICGAS",
            "c0-methodName": "getChargecost",
            "c0-id": session_id,
            "c0-param0": f"string:{self.region}",
            "c0-param1": f"string:{usage_type_str}", # 요금 종류 (예: 주택취사, 주택난방)
            "c0-param2": f"string:{target_date.strftime('%Y-%m-%d')}", # 조회 기준일
            "c0-param3": f"string:{usage_type_str}",
            "xml": "true",
        }

        try:
            async with self.websession.post(self.URL_PRICE, data=payload) as response:
                response.raise_for_status()
                response_text = await response.text()

                # 응답 텍스트에서 'var s5="22.5084"'와 같은 단가 부분을 찾아 숫자만 추출합니다.
                match = re.search(r'var s5="(\d+\.\d+)"', response_text)
                if match:
                    return float(match.group(1))
                
                LOGGER.warning("%s 날짜의 %s 단가 데이터(s5)를 DWR 응답에서 찾지 못했습니다.", target_date, usage_type_str)
                return None
        except Exception as err:
            LOGGER.error("%s 날짜의 %s 단가 조회 중 오류 발생: %s", target_date, usage_type_str, err)
            return None

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """전월 및 당월의 평균열량 데이터를 스크래핑합니다."""
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
        
        LOGGER.error("인천도시가스의 열량 데이터를 하나 또는 모두 가져오지 못했습니다.")
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """전월 및 당월의 열량단가 데이터를 스크래핑합니다."""
        today = date.today()
        first_day_curr_month = today.replace(day=1)
        first_day_prev_month = first_day_curr_month - relativedelta(months=1)

        # 사용자가 선택한 난방 타입에 따라 API에 전달할 난방 요금제 문자열을 결정합니다.
        if self.heating_type == "central_chp":
            heating_usage_type_str = "공동주택등열병합용"
        elif self.heating_type == "central_cogeneration":
            heating_usage_type_str = "공동주택열전용"
        else: # "residential"
            heating_usage_type_str = "주택난방"

        curr_cooking = await self._fetch_price_for_date(first_day_curr_month, "주택취사")
        prev_cooking = await self._fetch_price_for_date(first_day_prev_month, "주택취사")
        curr_heating = await self._fetch_price_for_date(first_day_curr_month, heating_usage_type_str)
        prev_heating = await self._fetch_price_for_date(first_day_prev_month, heating_usage_type_str)
        
        if all(p is not None for p in [curr_cooking, prev_cooking, curr_heating, prev_heating]):
            return {
                DATA_CURR_MONTH_PRICE_COOKING: curr_cooking,
                DATA_PREV_MONTH_PRICE_COOKING: prev_cooking,
                DATA_CURR_MONTH_PRICE_HEATING: curr_heating,
                DATA_PREV_MONTH_PRICE_HEATING: prev_heating,
            }
        
        LOGGER.error("인천도시가스의 취사/난방 단가 데이터를 모두 가져오지 못했습니다.")
        return None

    async def scrape_base_fee(self) -> float | None:
        """
        인천도시가스 웹사이트에서 현재 지역에 맞는 기본요금을 스크래핑합니다.
        """
        if not self.region:
            LOGGER.error("인천도시가스 공급사에 지역 코드가 설정되지 않아 기본요금을 조회할 수 없습니다.")
            return None

        try:
            async with self.websession.get(self.URL_BASE_FEE_PAGE) as response:
                response.raise_for_status()
                html_text = await response.text()
            
            region_name = self.REGIONS.get(self.region)
            if not region_name:
                LOGGER.warning("알 수 없는 지역 코드(%s)입니다. 기본요금을 조회할 수 없습니다.", self.region)
                return None
            
            pattern = rf"{region_name}\s*([\d,]+)\s*원/월"
            match = re.search(pattern, html_text)
            
            if match:
                base_fee_str = match.group(1).replace(",", "")
                return float(base_fee_str)

            LOGGER.error("기본요금 안내 문구에서 '%s' 지역의 요금 패턴을 찾지 못했습니다.", region_name)
            return None
            
        except (ValueError, TypeError) as e:
            LOGGER.error("인천도시가스 기본요금 파싱 중 값 변환 오류 발생: %s", e)
            return None
        except Exception as err:
            LOGGER.error("인천도시가스 기본요금 스크래핑 중 오류 발생: %s", err)
            return None
            
    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        인천도시가스의 취사/난방 경계값을 반환합니다.
        """
        return 516.0