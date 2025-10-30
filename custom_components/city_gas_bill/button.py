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
    async_add_entities([UpdateDataButton(hass, entry, device_info)])


class UpdateDataButton(ButtonEntity):
    """
    공급사로부터 데이터를 수동으로 동기화(업데이트)하는 버튼을 나타내는 클래스입니다.
    """

    _attr_has_entity_name = True # 엔티티 이름(name)을 가집니다.
    # 번역 파일(ko.json, en.json)에서 이 버튼의 이름을 찾기 위한 키입니다.
    # ko.json -> "update_data": { "name": "데이터 지금 동기화" }
    _attr_translation_key = "update_data"
    _attr_icon = "mdi:cloud-refresh" # UI에 표시될 아이콘

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
    ) -> None:
        """업데이트 버튼을 초기화합니다."""
        self.hass = hass
        # 엔티티의 고유 ID를 설정합니다. (예: "엔트리ID_update_data")
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        """
        사용자가 UI에서 이 버튼을 눌렀을 때 호출되는 메소드입니다.
        """
        LOGGER.debug("'데이터 지금 동기화' 버튼이 눌렸습니다. update_data 서비스를 호출합니다.")
        
        # Home Assistant의 서비스 시스템을 통해 `city_gas_bill.update_data` 서비스를 호출합니다.
        # 이 서비스는 __init__.py 파일에 등록되어 있으며, 코디네이터의 데이터 업데이트를 트리거합니다.
        await self.hass.services.async_call(
            DOMAIN,          # 서비스 도메인 (city_gas_bill)
            "update_data",   # 서비스 이름
            {},              # 서비스에 전달할 파라미터 (없음)
            blocking=False,  # 이 서비스가 끝날 때까지 기다리지 않음 (비동기 호출)
        )