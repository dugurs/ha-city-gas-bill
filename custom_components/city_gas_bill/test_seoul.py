# custom_components/city_gas_bill/test_seoul_gas.py

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
# 테스트할 공급사로 SeoulGasProvider를 임포트합니다.
from city_gas_bill.providers.seoul_gas import SeoulGasProvider

# --- 설정 끝 ---


# --- 테스트할 지역 및 용도 설정 ---
TEST_REGION = "01"  # 서울도시가스 기준 -> "01": 서울, "02": 경기
# 서울도시가스는 주택난방만 지원하므로 'residential'로 고정합니다.
TEST_USAGE_TYPE = "residential"
# ---


async def main():
    """테스트를 실행하는 메인 비동기 함수"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
    )
    logging.info(f"서울도시가스 프로바이더 로컬 테스트를 시작합니다.")
    logging.info(f"(테스트 지역 코드: {TEST_REGION}, 테스트 용도: {TEST_USAGE_TYPE})")

    # aiohttp에서 SSL 검증을 비활성화하는 TCPConnector를 생성합니다.
    connector = aiohttp.TCPConnector(ssl=False)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        # SeoulGasProvider 클래스를 초기화할 때 웹세션, 지역, 용도 정보를 전달합니다.
        provider = SeoulGasProvider(
            websession=session, 
            region=TEST_REGION, 
            usage_type=TEST_USAGE_TYPE
        )

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
    # 필요한 라이브러리가 설치되어 있는지 확인합니다.
    try:
        import aiohttp
        import bs4
        import dateutil
    except ImportError:
        print("="*50)
        print("오류: 테스트에 필요한 라이브러리가 설치되지 않았습니다.")
        print("아래 명령어를 실행하여 라이브러리를 설치해주세요.")
        print("pip install aiohttp beautifulsoup4 python-dateutil")
        print("="*50)
        sys.exit(1)
        
    asyncio.run(main())