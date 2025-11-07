# custom_components/city_gas_bill/__init__.py

"""The City Gas Bill integration."""
from __future__ import annotations
from datetime import datetime, timedelta, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_time_change, async_call_later
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN, 
    PLATFORMS, 
    LOGGER,
    CONF_READING_TIME,
    DATA_PREV_MONTH_HEAT, DATA_CURR_MONTH_HEAT,
    DATA_PREV_MONTH_PRICE_COOKING, DATA_PREV_MONTH_PRICE_HEATING,
    DATA_CURR_MONTH_PRICE_COOKING, DATA_CURR_MONTH_PRICE_HEATING
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

    async def _weekly_price_update(now):
        """매주 월요일에 열량단가 업데이트를 트리거하기 위한 콜백 함수입니다."""
        if now.weekday() == 0:
            LOGGER.info("예약된 주간 업데이트: 월요일이므로 열량단가 갱신을 시작합니다.")
            await coordinator.async_update_price_data() # 코디네이터의 열량단가 업데이트 메소드 호출
        else:
            LOGGER.debug("예약된 주간 업데이트: 월요일이 아니므로 건너뜁니다.")

    # 매주 월요일 새벽 1시에 _weekly_price_update 함수를 실행하도록 스케줄을 등록합니다.
    price_update_listener = async_track_time_change(hass, _weekly_price_update, hour=1, minute=0, second=0)

    # 설정에서 검침 시간을 가져와 매일 평균열량 업데이트 스케줄을 등록합니다.
    config = entry.options or entry.data
    # --- START: 수정된 코드 ---
    reading_time_input = config.get(CONF_READING_TIME, "00:00")
    update_time_obj = None
    try:
        reading_time_obj = None
        
        # 초(second)까지 포함된 "HH:MM:SS" 형식으로 파싱
        reading_time_obj = datetime.strptime(reading_time_input, "%H:%M:%S").time()
        
        if reading_time_obj is None:
            # 위에서 처리되지 않은 예외적인 타입일 경우, 에러를 발생시켜 except 구문으로 넘김
            raise TypeError(f"지원하지 않는 시간 형식입니다: {type(reading_time_input)}")

        update_time_obj = (datetime.combine(datetime.today(), reading_time_obj) - timedelta(minutes=5)).time()

    except (ValueError, TypeError, KeyError):
        # 문제가 발생했을 때 어떤 값이 들어왔는지 로그에 기록하여 디버깅을 돕습니다.
        LOGGER.warning(
            "검침 시간을 파싱할 수 없어 평균열량 자동 업데이트가 비활성화됩니다. (입력값: %s)",
            reading_time_input
        )
    # --- END: 수정된 코드 ---

    heat_update_listener = None
    if update_time_obj:
        async def _daily_heat_update(now):
            """매일 검침 시간 5분 전에 평균열량 업데이트를 트리거하는 콜백 함수입니다."""
            LOGGER.info("예약된 일일 업데이트: 평균열량 갱신을 시작합니다.")
            await coordinator.async_update_heat_data()

        heat_update_listener = async_track_time_change(
            hass, _daily_heat_update,
            hour=update_time_obj.hour, minute=update_time_obj.minute, second=0
        )

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
            DATA_PREV_MONTH_PRICE_COOKING: f"{entry.entry_id}_prev_month_price_cooking",
            DATA_PREV_MONTH_PRICE_HEATING: f"{entry.entry_id}_prev_month_price_heating",
            DATA_CURR_MONTH_PRICE_COOKING: f"{entry.entry_id}_curr_month_price_cooking",
            DATA_CURR_MONTH_PRICE_HEATING: f"{entry.entry_id}_curr_month_price_heating",
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
        "price_update_listener": price_update_listener,
        "heat_update_listener": heat_update_listener,
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
        
    # 최초 설정 시 기본요금을 자동으로 한 번 스크랩하는 로직
    if not entry.data.get("_initial_base_fee_scraped"):
        LOGGER.info("최초 설정 확인: 기본요금 자동 조회를 3초 후에 시도합니다.")

        async def _scrape_initial_base_fee(_=None):
            """엔티티가 준비될 시간을 기다린 후, 기본요금을 스크랩하고 값을 설정합니다."""
            LOGGER.debug("초기 기본요금 조회를 시작합니다.")
            base_fee = await coordinator.provider.scrape_base_fee()

            if base_fee is not None:
                ent_reg = er.async_get(hass)
                entity_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_base_fee")
                if entity_id:
                    LOGGER.info("조회된 초기 기본요금 %s원을 '%s' 엔티티에 설정합니다.", base_fee, entity_id)
                    await hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": entity_id, "value": base_fee},
                        blocking=False
                    )
                else:
                    LOGGER.warning("초기 기본요금을 설정할 '기본 요금' Number 엔티티를 아직 찾을 수 없습니다.")
            else:
                LOGGER.warning("초기 기본요금을 가져오는 데 실패했습니다. 수동으로 설정해주세요.")

            # 성공 여부와 관계없이 다시 실행되지 않도록 플래그를 업데이트합니다.
            new_data = {**entry.data, "_initial_base_fee_scraped": True}
            hass.config_entries.async_update_entry(entry, data=new_data)

        # 3초 후에 함수를 실행하여 엔티티가 생성될 시간을 확보합니다.
        async_call_later(hass, 3, _scrape_initial_base_fee)

    async def handle_update_price_service(call: ServiceCall) -> None:
        """사용자가 '열량단가 갱신' 서비스를 호출했을 때 실행됩니다."""
        LOGGER.info("서비스 호출로 열량단가 업데이트를 시작합니다.")
        # 저장된 코디네이터를 찾아 열량단가 업데이트를 요청합니다.
        # 이 통합구성요소는 단일 인스턴스만 허용하므로 entry_id로 직접 접근합니다.
        if coordinator:
            await coordinator.async_update_price_data()

    async def handle_update_heat_service(call: ServiceCall) -> None:
        """사용자가 '평균열량 갱신' 서비스를 호출했을 때 실행됩니다."""
        LOGGER.info("서비스 호출로 평균열량 업데이트를 시작합니다.")
        if coordinator:
            await coordinator.async_update_heat_data()
            
    # 새로운 서비스들을 Home Assistant에 등록합니다.
    hass.services.async_register(DOMAIN, "update_price_data", handle_update_price_service)
    hass.services.async_register(DOMAIN, "update_heat_data", handle_update_heat_service)
    
    # 통합구성요소가 제거될 때 등록했던 서비스도 함께 제거되도록 합니다.
    def remove_services():
        hass.services.async_remove(DOMAIN, "update_price_data")
        hass.services.async_remove(DOMAIN, "update_heat_data")
        
    entry.async_on_unload(remove_services)

    async def handle_update_base_fee_service(call: ServiceCall) -> None:
        """
        공급사 웹사이트에서 최신 기본요금을 가져와 Number 엔티티를 업데이트하는 서비스 핸들러입니다.
        """
        LOGGER.info("서비스 호출로 기본요금 업데이트를 시작합니다.")
        coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if not coordinator:
            LOGGER.error("코디네이터를 찾을 수 없어 기본요금을 업데이트할 수 없습니다.")
            return

        # 공급사의 기본요금 스크래핑 메소드 호출
        base_fee = await coordinator.provider.scrape_base_fee()

        if base_fee is not None:
            ent_reg = er.async_get(hass)
            entity_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{entry.entry_id}_base_fee")
            
            if entity_id:
                LOGGER.info("새로운 기본요금 %s원을 '%s' 엔티티에 설정합니다.", base_fee, entity_id)
                await hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": entity_id, "value": base_fee},
                    blocking=False
                )
            else:
                LOGGER.warning("'기본 요금' Number 엔티티를 찾을 수 없어 값을 업데이트하지 못했습니다.")
        else:
            LOGGER.warning("%s 공급사에서 기본요금을 가져오는 데 실패했습니다.", coordinator.provider.name)

    # 'city_gas_bill.update_base_fee' 서비스를 등록합니다.
    hass.services.async_register(DOMAIN, "update_base_fee", handle_update_base_fee_service)
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "update_base_fee"))

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
        data["price_update_listener"]()
        if data["heat_update_listener"]:
            data["heat_update_listener"]()
        data["coordinator_listener_remover"]()
    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    사용자가 UI에서 설정을 변경했을 때 호출되어, 통합구성요소를 다시 로드합니다.
    """
    await hass.config_entries.async_reload(entry.entry_id)