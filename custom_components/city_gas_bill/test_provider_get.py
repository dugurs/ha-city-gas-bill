# custom_components/city_gas_bill/test_provider_get.py (최종 수정 버전)

import asyncio
import aiohttp
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

# --- 설정 시작 ---

# [1. 모킹] 'homeassistant' 모듈이 없는 문제를 해결하기 위해 가짜 모듈을 만듭니다.
MOCK_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.event",
    "homeassistant.util",
    "homeassistant.util.dt",
]
for module_name in MOCK_MODULES:
    sys.modules[module_name] = MagicMock()

# [2. 경로 설정]
script_dir = Path(__file__).parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

# [3. 임포트]
from city_gas_bill.providers.yesco_gas import YescoGasProvider
from city_gas_bill.const import (
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE,
)
# --- 설정 끝 ---


# --- 테스트할 지역 설정 ---
TEST_REGION = "1"  # "1": 서울, "8": 경기
# ---


async def main():
    """테스트를 실행하는 메인 비동기 함수"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
    )
    logging.info(f"예스코 프로바이더 로컬 테스트를 시작합니다. (테스트 지역 코드: {TEST_REGION})")

    # [수정] aiohttp에서 SSL 검증을 비활성화하는 올바른 방법입니다.
    # 1. SSL 검증을 비활성화하는 TCPConnector를 생성합니다.
    connector = aiohttp.TCPConnector(ssl=False)
    # 2. 생성한 connector를 ClientSession에 전달합니다.
    async with aiohttp.ClientSession(connector=connector) as session:
        provider = YescoGasProvider(websession=session, region=TEST_REGION)

        # 1. 평균열량 데이터 스크래핑 테스트
        try:
            logging.info("--- 1. 평균열량 데이터 스크래핑 테스트 실행 ---")
            heat_data = await provider.scrape_heat_data()
            if heat_data:
                logging.info(f"✅ [성공] 평균열량 데이터: {heat_data}")
            else:
                logging.error("❌ [실패] 평균열량 데이터가 None을 반환했습니다.")
        except Exception as e:
            logging.error(f"❌ [오류] 평균열량 테스트 중 예외 발생: {e}", exc_info=True)

        print("-" * 50)

        # 2. 열량단가 데이터 스크래핑 테스트
        try:
            logging.info("--- 2. 열량단가 데이터 스크래핑 테스트 실행 ---")
            price_data = await provider.scrape_price_data()
            if price_data:
                logging.info(f"✅ [성공] 열량단가 데이터: {price_data}")
            else:
                logging.error("❌ [실패] 열량단가 데이터가 None을 반환했습니다.")
        except Exception as e:
            logging.error(f"❌ [오류] 열량단가 테스트 중 예외 발생: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())