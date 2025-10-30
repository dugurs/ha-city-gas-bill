# custom_components/city_gas_bill/__init__.py

"""The City Gas Bill integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_time_change, async_call_later
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN, 
    PLATFORMS, 
    LOGGER,
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE, DATA_CURR_MONTH_PRICE
)
from .coordinator import CityGasDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    사용자가 UI를 통해 통합구성요소를 추가할 때 호출되는 기본 설정 함수입니다.
    """
    # Home Assistant의 중앙 데이터 저장소에 이 통합구성요소만의 공간을 만듭니다.
    hass.data.setdefault(DOMAIN, {})

    # 데이터 업데이트를 총괄하는 코디네이터를 생성합니다.
    coordinator = CityGasDataUpdateCoordinator(hass, entry)
    # 설정이 추가된 직후, 첫 데이터 업데이트를 즉시 실행합니다.
    await coordinator.async_config_entry_first_refresh()

    async def _weekly_update(now):
        """매주 월요일에 데이터 업데이트를 트리거하기 위한 콜백 함수입니다."""
        # now.weekday()는 월요일이 0, 일요일이 6입니다.
        if now.weekday() == 0:
            LOGGER.info("예약된 주간 업데이트: 월요일이므로 데이터 갱신을 시작합니다.")
            await coordinator.async_request_refresh() # 코디네이터에게 데이터 업데이트를 요청
        else:
            LOGGER.debug("예약된 주간 업데이트: 월요일이 아니므로 건너뜁니다.")

    # 매주 월요일 새벽 1시에 _weekly_update 함수를 실행하도록 스케줄을 등록합니다.
    update_listener = async_track_time_change(hass, _weekly_update, hour=1, minute=0, second=0)

    @callback
    def update_number_entities():
        """
        코디네이터가 새로운 데이터를 성공적으로 가져왔을 때 호출되는 콜백 함수입니다.
        이 함수는 스크래핑된 새 데이터를 Number 엔티티(예: 전월 평균열량)에 반영합니다.
        """
        LOGGER.debug("코디네이터에 새 데이터가 있습니다. Number 엔티티를 업데이트합니다.")
        ent_reg = er.async_get(hass)
        
        # 업데이트할 데이터 키와 해당 Number 엔티티의 고유 ID를 매핑합니다.
        key_to_unique_id_map = {
            DATA_PREV_MONTH_HEAT: f"{entry.entry_id}_prev_month_heat",
            DATA_CURR_MONTH_HEAT: f"{entry.entry_id}_curr_month_heat",
            DATA_PREV_MONTH_PRICE: f"{entry.entry_id}_prev_month_price",
            DATA_CURR_MONTH_PRICE: f"{entry.entry_id}_curr_month_price",
        }

        # 각 항목에 대해 Number 엔티티의 값을 업데이트하는 서비스 콜을 실행합니다.
        for data_key, unique_id in key_to_unique_id_map.items():
            entity_id = ent_reg.async_get_entity_id("number", DOMAIN, unique_id)
            new_value = coordinator.data.get(data_key)

            if entity_id and new_value is not None:
                LOGGER.debug("%s 엔티티를 새 값(%s)으로 업데이트합니다.", entity_id, new_value)
                hass.async_create_task(
                    hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": entity_id, "value": new_value},
                        blocking=False,
                    )
                )

    # 코디네이터에 리스너를 등록하여, 데이터 업데이트가 성공할 때마다 update_number_entities가 실행되도록 합니다.
    coordinator_listener_remover = coordinator.async_add_listener(update_number_entities)

    # 생성된 코디네이터와 리스너들을 중앙 데이터 저장소에 보관합니다.
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "update_listener": update_listener,
        "coordinator_listener_remover": coordinator_listener_remover,
    }

    # 사용자가 옵션을 변경하면 통합구성요소를 리로드하도록 리스너를 추가합니다.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    # 이 통합구성요소가 사용하는 다른 플랫폼들(sensor, number, button)의 설정을 시작하도록 전달합니다.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # 최초 설정 시 엔티티들이 완전히 준비되도록 5초 후 리로드를 예약합니다 (안정성 확보).
    if not entry.data.get("_initial_reload_done"):
        LOGGER.info("최초 설정입니다. 5초 후 통합구성요소를 리로드하여 엔티티를 준비합니다.")
        async def _reload_integration(now):
            await hass.services.async_call(
                "homeassistant", "reload_config_entry",
                {"entry_id": entry.entry_id}, blocking=False
            )
        async_call_later(hass, 5, _reload_integration)
        # 리로드가 예약되었음을 기록하여 다음부터는 실행되지 않도록 합니다.
        new_data = {**entry.data, "_initial_reload_done": True}
        hass.config_entries.async_update_entry(entry, data=new_data)

    async def handle_update_service(call: ServiceCall) -> None:
        """
        사용자가 '데이터 갱신' 버튼을 누르거나 자동화에서 서비스를 호출했을 때 실행되는 함수입니다.
        """
        LOGGER.info("서비스 호출로 수동 데이터 업데이트를 시작합니다.")
        # 저장된 코디네이터를 찾아 데이터 업데이트를 요청합니다.
        for entry_id_key, data in hass.data[DOMAIN].items():
            if "coordinator" in data:
                await data["coordinator"].async_request_refresh()
                
    # `city_gas_bill.update_data` 라는 이름의 커스텀 서비스를 Home Assistant에 등록합니다.
    hass.services.async_register(DOMAIN, "update_data", handle_update_service)
    # 통합구성요소가 제거될 때 등록했던 서비스도 함께 제거되도록 합니다.
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "update_data"))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    사용자가 통합구성요소를 제거할 때 호출되는 함수입니다.
    """
    # sensor, number, button 플랫폼들을 먼저 제거합니다.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # 중앙 데이터 저장소에서 이 통합구성요소의 데이터를 삭제합니다.
        data = hass.data[DOMAIN].pop(entry.entry_id)
        # 등록했던 스케줄러와 리스너를 깨끗하게 정리합니다.
        data["update_listener"]()
        data["coordinator_listener_remover"]()
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    사용자가 UI에서 설정을 변경했을 때 호출되어, 통합구성요소를 다시 로드합니다.
    """
    await hass.config_entries.async_reload(entry.entry_id)