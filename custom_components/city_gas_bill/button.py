# custom_components/city_gas_bill/button.py

"""
City Gas Bill 통합구성요소의 버튼(Button) 플랫폼 파일입니다.
사용자가 수동으로 데이터 업데이트를 트리거할 수 있는 버튼을 생성합니다.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER, CONF_PROVIDER
from .providers import AVAILABLE_PROVIDERS

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Button 플랫폼을 설정합니다.
    통합구성요소가 로드될 때 Home Assistant에 의해 호출됩니다.
    """
    # 설정에서 선택된 공급사 이름을 가져옵니다.
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name
    
    # 이 버튼이 속할 기기(Device) 정보를 정의합니다.
    # 이렇게 하면 이 버튼이 다른 센서, 숫자 엔티티와 함께 '도시가스 요금' 기기 하위에 묶여서 표시됩니다.
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )

    # 생성할 버튼 엔티티(UpdateDataButton)를 리스트에 담아 Home Assistant에 추가합니다.
    async_add_entities([
        UpdatePriceDataButton(hass, entry, device_info),
        UpdateHeatDataButton(hass, entry, device_info),
        UpdateBaseFeeButton(hass, entry, device_info)
    ])


class UpdatePriceDataButton(ButtonEntity):
    """
    공급사로부터 열량단가 데이터를 수동으로 동기화하는 버튼을 나타내는 클래스입니다.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "update_price_data" # 번역 키 변경
    _attr_icon = "mdi:currency-krw" # 아이콘 변경

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """열량단가 업데이트 버튼을 초기화합니다."""
        self.hass = hass
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """사용자가 UI에서 이 버튼을 눌렀을 때 호출되는 메소드입니다."""
        LOGGER.debug("'열량단가 갱신' 버튼이 눌렸습니다. update_price_data 서비스를 호출합니다.")
        
        # `city_gas_bill.update_price_data` 서비스를 호출합니다.
        await self.hass.services.async_call(
            DOMAIN,
            "update_price_data", # 서비스 이름 변경
            {},
            blocking=False,
        )

class UpdateHeatDataButton(ButtonEntity):
    """
    공급사로부터 평균열량 데이터를 수동으로 동기화하는 버튼을 나타내는 클래스입니다.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "update_heat_data" # 새로운 번역 키
    _attr_icon = "mdi:fire-alert" # 새로운 아이콘

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """평균열량 업데이트 버튼을 초기화합니다."""
        self.hass = hass
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """사용자가 UI에서 이 버튼을 눌렀을 때 호출되는 메소드입니다."""
        LOGGER.debug("'평균열량 갱신' 버튼이 눌렸습니다. update_heat_data 서비스를 호출합니다.")
        
        # `city_gas_bill.update_heat_data` 서비스를 호출합니다.
        await self.hass.services.async_call(
            DOMAIN,
            "update_heat_data", # 새로운 서비스 이름
            {},
            blocking=False,
        )

class UpdateBaseFeeButton(ButtonEntity):
    """
    공급사로부터 기본요금을 수동으로 가져오는 버튼을 나타내는 클래스입니다.
    """
    _attr_has_entity_name = True
    _attr_translation_key = "update_base_fee" # 번역 키
    _attr_icon = "mdi:cash-sync" # 아이콘

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """기본요금 업데이트 버튼을 초기화합니다."""
        self.hass = hass
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """
        사용자가 UI에서 이 버튼을 눌렀을 때 호출되는 메소드입니다.
        """
        LOGGER.debug("'기본요금 가져오기' 버튼이 눌렸습니다. update_base_fee 서비스를 호출합니다.")
        
        # 'city_gas_bill.update_base_fee' 서비스를 호출합니다.
        await self.hass.services.async_call(
            DOMAIN,
            "update_base_fee", # 새로 추가된 서비스 이름
            {},
            blocking=False,
        )