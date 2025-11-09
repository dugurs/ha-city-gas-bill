# custom_components/city_gas_bill/test_all_providers.py

"""
City Gas Bill 통합구성요소의 모든 공급사(Provider)를 한 번에 테스트하기 위한
통합 테스트 스CRIPT입니다.
"""

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

# [3. 테스트할 모든 공급사 클래스 임포트]
from city_gas_bill.providers.seoul_gas import SeoulGasProvider
from city_gas_bill.providers.incheon_gas import IncheonGasProvider
from city_gas_bill.providers.yesco_gas import YescoGasProvider
from city_gas_bill.providers.koone_gas import KooneGasProvider
from city_gas_bill.providers.busan_gas import BusanGasProvider
from city_gas_bill.providers.kiturami_gas import KituramiGasProvider
from city_gas_bill.providers.samchully_gas import SamchullyGasProvider
from city_gas_bill.providers.daeryun_ens import DaeryunENSProvider
from city_gas_bill.providers.chungbuk_gas import ChungbukGasProvider # --- START: 수정된 코드 ---

# --- 설정 끝 ---


# --- 여기에 테스트할 공급사와 설정을 추가하거나 주석 처리하여 관리합니다. ---
PROVIDERS_TO_TEST = [
    # {
    #     "name": "서울도시가스",
    #     "class": SeoulGasProvider,
    #     "region": "01",  # "01": 서울, "02": 경기
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "인천도시가스 (인천)",
    #     "class": IncheonGasProvider,
    #     "region": "1",   # "1": 인천, "2": 경기
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "인천도시가스 (경기, 중앙난방)",
    #     "class": IncheonGasProvider,
    #     "region": "2",
    #     "usage_type": "central", # 중앙난방 테스트
    # },
    # {
    #     "name": "예스코",
    #     "class": YescoGasProvider,
    #     "region": "1",   # "1": 서울, "8": 경기
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "코원에너지서비스 (서울)",
    #     "class": KooneGasProvider,
    #     "region": "274", # "274": 서울, "275": 경기
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "코원에너지서비스 (경기)",
    #     "class": KooneGasProvider,
    #     "region": "275", 
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "부산도시가스 (주택난방)",
    #     "class": BusanGasProvider,
    #     "region": "276", # "276": 부산
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "부산도시가스 (중앙난방)",
    #     "class": BusanGasProvider,
    #     "region": "276",
    #     "usage_type": "central", # 중앙난방 테스트
    # },
    # {
    #     "name": "귀뚜라미에너지",
    #     "class": KituramiGasProvider,
    #     "region": "seoul", # "seoul": 서울
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "삼천리 도시가스 (경기, 주택난방)",
    #     "class": SamchullyGasProvider,
    #     "region": "0001",  # "0001": 경기, "0002": 인천
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "삼천리 도시가스 (인천, 주택난방)",
    #     "class": SamchullyGasProvider,
    #     "region": "0002",
    #     "usage_type": "residential",
    # },
    # {
    #     "name": "삼천리 도시가스 (경기, 중앙난방)",
    #     "class": SamchullyGasProvider,
    #     "region": "0001",
    #     "usage_type": "central", # 중앙난방 테스트
    # },
    # {
    #     "name": "대륜이엔에스",
    #     "class": DaeryunENSProvider,
    #     "region": "seoul", # "seoul": 서울, "gyeonggi": 경기
    #     "usage_type": "residential",
    # },
    # --- START: 수정된 코드 ---
    {
        "name": "참빛충북도시가스 (주택난방)",
        "class": ChungbukGasProvider,
        "region": "chungbuk",
        "usage_type": "residential",
    },
    {
        "name": "참빛충북도시가스 (중앙난방)",
        "class": ChungbukGasProvider,
        "region": "chungbuk",
        "usage_type": "central",
    },
    # --- END: 수정된 코드 ---
]
# ---


async def run_provider_test(session, config):
    """단일 공급사에 대한 테스트를 실행하는 함수"""
    provider_name = config["name"]
    logging.info(f"===== {provider_name} 테스트 시작 =====")
    logging.info(f"(지역: {config['region']}, 용도: {config['usage_type']})")

    try:
        # 설정에 따라 동적으로 공급사 인스턴스 생성
        provider = config["class"](
            websession=session,
            region=config["region"],
            usage_type=config["usage_type"]
        )

        # 1. 평균열량 테스트
        logging.info("--- 1. 평균열량 데이터 테스트 ---")
        heat_data = await provider.scrape_heat_data()
        if heat_data:
            logging.info(f"✅ [성공] 평균열량: {heat_data}")
        else:
            # 의도적으로 None을 반환하는 경우 경고로 처리합니다.
            logging.warning("⚠️ [알림] 평균열량 자동 조회를 지원하지 않거나 실패했습니다 (결과: None).")

        # 2. 열량단가 테스트
        logging.info("--- 2. 열량단가 데이터 테스트 ---")
        price_data = await provider.scrape_price_data()
        # None일 경우만 실패로 처리하고, 빈 딕셔너리({})는 성공(변동 없음)으로 간주합니다.
        if price_data is not None:
            logging.info(f"✅ [성공] 열량단가: {price_data if price_data else '변동 없음'}")
        else:
            # 의도적으로 None을 반환하는 경우 경고로 처리합니다.
            logging.warning("⚠️ [알림] 열량단가 자동 조회를 지원하지 않거나 실패했습니다 (결과: None).")

        # 3. 기본요금 테스트
        logging.info("--- 3. 기본요금 데이터 테스트 ---")
        base_fee = await provider.scrape_base_fee()
        if base_fee is not None:
            logging.info(f"✅ [성공] 기본요금: {base_fee}")
        else:
            logging.error("❌ [실패] 기본요금 데이터가 None을 반환했습니다.")

        # 4. 취사난방경계 테스트
        logging.info("--- 4. 취사난방경계 데이터 테스트 ---")
        if hasattr(provider, "scrape_cooking_heating_boundary"):
            boundary_data = await provider.scrape_cooking_heating_boundary()
            if boundary_data is not None:
                logging.info(f"✅ [성공] 취사난방경계: {boundary_data} MJ")
            else:
                logging.warning("⚠️ [알림] 취사난방경계 데이터를 가져오지 못했거나 지원하지 않습니다.")
        else:
            logging.info("ℹ️ [정보] 이 공급사는 취사난방경계 스크래핑을 지원하지 않습니다.")

    except Exception as e:
        logging.error(f"💥 [{provider_name}] 테스트 중 심각한 예외 발생: {e}", exc_info=True)
    
    logging.info(f"===== {provider_name} 테스트 종료 =====\n")


async def main():
    """테스트를 실행하는 메인 비동기 함수"""
    logging.basicConfig(
        level=logging.INFO, # DEBUG로 변경하면 더 상세한 로그를 볼 수 있습니다.
        format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
    )
    logging.info("모든 도시가스 공급사 프로바이더 로컬 테스트를 시작합니다.")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 설정된 모든 공급사에 대해 순차적으로 테스트 실행
        for config in PROVIDERS_TO_TEST:
            await run_provider_test(session, config)


if __name__ == "__main__":
    # 필요한 라이브러리가 설치되어 있는지 확인
    try:
        import aiohttp
        import bs4
        from dateutil.relativedelta import relativedelta
    except ImportError:
        print("="*50)
        print("오류: 테스트에 필요한 라이브러리가 설치되지 않았습니다.")
        print("아래 명령어를 실행하여 라이브러리를 설치해주세요.")
        print("pip install aiohttp beautifulsoup4 python-dateutil")
        print("="*50)
        sys.exit(1)
        
    asyncio.run(main())