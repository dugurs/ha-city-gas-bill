# custom_components/city_gas_bill/coordinator.py

"""
City Gas Bill 통합구성요소의 DataUpdateCoordinator를 정의하는 파일입니다.
"""
from __future__ import annotations
import async_timeout  # 비동기 작업의 시간 초과를 처리하기 위한 라이브러리
import aiohttp  # 비동기 HTTP 요청을 위한 라이브러리

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntryError
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,  # HA의 데이터 업데이트 코디네이터 기본 클래스
    UpdateFailed,  # 업데이트 실패 시 발생시킬 예외
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession  # HA에서 권장하는 aiohttp 세션 생성 헬퍼
from homeassistant.util import dt as dt_util  # 날짜 및 시간 관련 유틸리티

from .const import DOMAIN, LOGGER, CONF_PROVIDER, CONF_PROVIDER_REGION, CONF_HEATING_TYPE
from .providers import AVAILABLE_PROVIDERS  # 사용 가능한 모든 공급사 목록
from .providers.base import GasProvider  # 공급사의 기본 클래스

class CityGasDataUpdateCoordinator(DataUpdateCoordinator):
    """
    도시가스 공급사로부터 데이터를 관리하고 업데이트하는 중앙 관리자 클래스입니다.
    이 클래스가 주기적으로 데이터를 가져오면, 연결된 모든 센서들이 이 데이터를 사용합니다.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """코디네이터를 초기화합니다."""
        self.config_entry = entry
        # HA에서 제공하는 비동기 웹 세션을 생성합니다. (SSL 검증 비활성화)
        # 여러 요청에 걸쳐 세션을 재사용하여 효율성을 높입니다.
        self.websession = async_create_clientsession(hass, verify_ssl=False)

        # 사용자가 설정에서 변경한 '옵션'이 있으면 그것을 우선 사용하고,
        # 없으면 최초 설정 시 입력한 '데이터'를 사용합니다.
        config = self.config_entry.options or self.config_entry.data
        provider_key = config[CONF_PROVIDER]  # 예: 'seoul_gas', 'incheon_gas'
        # 설정에서 지역 코드(region code)와 난방 타입(heating type)을 가져옵니다.
        provider_region = config.get(CONF_PROVIDER_REGION)
        heating_type = config.get(CONF_HEATING_TYPE)

        # 사용자가 선택한 공급사 키를 바탕으로 실제 공급사 클래스를 가져옵니다.
        provider_class = AVAILABLE_PROVIDERS.get(provider_key)
        if not provider_class:
            # 만약 알 수 없는 공급사가 선택되면, 설정 오류를 발생시킵니다.
            raise ConfigEntryError(f"'{provider_key}' 공급사를 찾을 수 없습니다.")
        
        # 선택된 공급사 클래스의 인스턴스를 생성하고 웹 세션, 지역, 난방 타입 정보를 전달합니다.
        self.provider: GasProvider = provider_class(
            self.websession,
            region=provider_region,
            heating_type=heating_type
        )

        # 마지막으로 데이터 업데이트에 성공한 시간을 기록하기 위한 변수입니다.
        self.last_update_success_timestamp = None
        
        # DataUpdateCoordinator의 기본 생성자를 호출합니다.
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} ({self.provider.name})",  # 로그에 표시될 코디네이터의 이름
        )

    async def _async_update_data(self) -> dict:
        """
        선택된 공급사를 통해 실제 데이터를 가져오는 핵심 메소드입니다.
        HA의 업데이트 주기에 따라 자동으로 호출됩니다.
        """
        # 사용자가 '수동 입력' 공급사를 선택한 경우, 웹 스크래핑을 건너뜁니다.
        if self.provider.id == "manual":
            LOGGER.debug("'수동 입력'이 선택되어 웹 스크래핑을 생략합니다.")
            self.last_update_success_timestamp = dt_util.utcnow() # 성공 시간만 현재로 기록
            return {}  # 빈 데이터를 반환하여 기존 값을 덮어쓰지 않도록 함

        try:
            # 네트워크 요청이 60초 이상 걸리면 시간 초과 오류를 발생시킵니다.
            async with async_timeout.timeout(60):
                # 선택된 공급사의 스크래핑 메소드를 비동기적으로 호출합니다.
                heat_data = await self.provider.scrape_heat_data()  # 평균열량 데이터
                price_data = await self.provider.scrape_price_data()  # 열량단가 데이터

                # 두 데이터 중 하나라도 가져오지 못했다면 실패로 처리합니다.
                if heat_data is None or price_data is None:
                    failed_items = []
                    if heat_data is None: failed_items.append("평균열량")
                    if price_data is None: failed_items.append("열량단가")
                    # 업데이트 실패 예외를 발생시켜 HA에 실패했음을 알립니다.
                    raise UpdateFailed(
                        f"{self.provider.name}로부터 필수 데이터({', '.join(failed_items)})를 가져오지 못했습니다."
                    )

                # 데이터 가져오기에 성공하면, 성공 시간을 기록합니다.
                self.last_update_success_timestamp = dt_util.utcnow()
                
                # 가져온 두 종류의 데이터를 하나의 딕셔너리로 합쳐서 반환합니다.
                # 이 반환된 값이 self.data에 저장되어 센서들이 사용하게 됩니다.
                return {**heat_data, **price_data}

        # 웹 통신 중 발생할 수 있는 네트워크 관련 오류를 처리합니다.
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"{self.provider.name}와 통신 중 오류가 발생했습니다: {err}")
        # 그 외 예상치 못한 모든 종류의 오류를 처리합니다.
        except Exception as err:
            raise UpdateFailed(f"{self.provider.name}에서 예기치 않은 오류가 발생했습니다: {err}")

    async def async_update_price_data(self) -> None:
        """열량단가 데이터만 선택적으로 업데이트합니다."""
        if self.provider.id == "manual":
            LOGGER.debug("수동 입력 모드이므로 열량단가 업데이트를 건너뜁니다.")
            return

        LOGGER.info("%s 공급사로부터 열량단가 데이터 업데이트를 시작합니다.", self.provider.name)
        try:
            async with async_timeout.timeout(60):
                price_data = await self.provider.scrape_price_data()
                if price_data is None:
                    raise UpdateFailed(f"{self.provider.name}로부터 열량단가 데이터를 가져오지 못했습니다.")

                self.last_update_success_timestamp = dt_util.utcnow()
                # 기존 데이터에 새로운 열량단가 데이터를 덮어씁니다.
                new_data = {**self.data, **price_data}
                self.async_set_updated_data(new_data)
        except Exception as err:
            raise UpdateFailed(f"{self.provider.name}에서 열량단가 업데이트 중 오류 발생: {err}")

    async def async_update_heat_data(self) -> None:
        """평균열량 데이터만 선택적으로 업데이트합니다."""
        if self.provider.id == "manual":
            LOGGER.debug("수동 입력 모드이므로 평균열량 업데이트를 건너뜁니다.")
            return

        LOGGER.info("%s 공급사로부터 평균열량 데이터 업데이트를 시작합니다.", self.provider.name)
        try:
            async with async_timeout.timeout(60):
                heat_data = await self.provider.scrape_heat_data()
                if heat_data is None:
                    raise UpdateFailed(f"{self.provider.name}로부터 평균열량 데이터를 가져오지 못했습니다.")

                self.last_update_success_timestamp = dt_util.utcnow()
                # 기존 데이터에 새로운 평균열량 데이터를 덮어씁니다.
                new_data = {**self.data, **heat_data}
                self.async_set_updated_data(new_data)
        except Exception as err:
            raise UpdateFailed(f"{self.provider.name}에서 평균열량 업데이트 중 오류 발생: {err}")