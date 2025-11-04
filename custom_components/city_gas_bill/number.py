# custom_components/city_gas_bill/number.py

"""
City Gas Bill 통합구성요소의 숫자(Number) 플랫폼 파일입니다.
사용자가 UI에서 직접 설정값을 변경할 수 있는 엔티티들을 정의합니다.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import DOMAIN, DEFAULT_BASE_FEE, CONF_GAS_SENSOR, LOGGER
from .providers import AVAILABLE_PROVIDERS
from .const import CONF_PROVIDER

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """
    Number 플랫폼을 설정합니다.
    설정된 공급사 정보를 바탕으로 기기 정보를 생성하고, 각종 설정값 엔티티를 추가합니다.
    """
    provider_name = AVAILABLE_PROVIDERS[entry.data[CONF_PROVIDER]](None).name
    
    # 이 통합구성요소의 모든 엔티티를 하나로 묶어줄 기기(Device) 정보 정의
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=provider_name,
        entry_type="service",
        model="Gas Bill Calculator"
    )
    
    # 엔티티들을 Home Assistant에 등록합니다.
    async_add_entities([
        BaseFeeNumber(entry, device_info),
        MonthlyStartReadingNumber(hass, entry, device_info),
        PrevMonthHeatNumber(entry, device_info),
        CurrMonthHeatNumber(entry, device_info),
        PrevMonthPriceNumber(entry, device_info),
        CurrMonthPriceNumber(entry, device_info),
        CorrectionFactorNumber(entry, device_info),
        WinterReductionFeeNumber(entry, device_info),
        NonWinterReductionFeeNumber(entry, device_info),
    ])

class RestorableNumberEntity(NumberEntity, RestoreEntity):
    """
    HA 재시작 후에도 마지막 상태(값)를 복원할 수 있는 Number 엔티티의 기본 클래스입니다.
    """
    _attr_has_entity_name = True # 기기 이름을 제외한 엔티티 고유 이름만 사용
    _attr_mode = NumberMode.BOX # UI에서 슬라이더 대신 입력 상자 형태로 표시

    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo, default_value: float) -> None:
        """Number 엔티티를 초기화합니다."""
        # 번역 파일(en.json, ko.json)에서 사용할 키를 기반으로 고유 ID 생성
        self._attr_unique_id = f"{entry.entry_id}_{self.translation_key}"
        self._attr_device_info = device_info
        self._attr_native_value = default_value

    async def async_added_to_hass(self) -> None:
        """
        엔티티가 HA에 추가될 때 호출됩니다.
        이전에 저장된 상태가 있다면 그 값을 불러와 복원합니다.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._attr_native_value = float(last_state.state)
            except (ValueError, TypeError):
                LOGGER.warning("%s의 복원된 상태값을 파싱할 수 없습니다.", self.entity_id)

    async def async_set_native_value(self, value: float) -> None:
        """
        사용자가 UI에서 값을 변경했을 때 호출됩니다.
        새로운 값을 저장하고 상태를 업데이트합니다.
        """
        self._attr_native_value = value
        self.async_write_ha_state()

# --- 각 설정값 엔티티 클래스 정의 ---

class CorrectionFactorNumber(RestorableNumberEntity):
    """온압보정계수 설정을 위한 엔티티입니다."""
    _attr_translation_key = "correction_factor"
    _attr_icon = "mdi:gauge"
    _attr_native_unit_of_measurement = None
    # 보정계수는 보통 1.0 근처의 값이므로 정밀한 조정을 위해 작은 step을 사용합니다.
    _attr_native_min_value = 0.8; _attr_native_max_value = 1.2; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=1.0)

class PrevMonthHeatNumber(RestorableNumberEntity):
    """지난달 평균열량 엔티티입니다."""
    _attr_translation_key = "prev_month_heat"
    _attr_icon = "mdi:fire-alert"
    _attr_native_unit_of_measurement = "MJ/Nm³"
    _attr_native_min_value = 30.0; _attr_native_max_value = 50.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=43.0)

class CurrMonthHeatNumber(RestorableNumberEntity):
    """이번 달 평균열량 엔티티입니다."""
    _attr_translation_key = "curr_month_heat"
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "MJ/Nm³"
    _attr_native_min_value = 30.0; _attr_native_max_value = 50.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=43.0)

class PrevMonthPriceNumber(RestorableNumberEntity):
    """지난달 열량단가 엔티티입니다."""
    _attr_translation_key = "prev_month_price"
    _attr_icon = "mdi:cash-minus"
    _attr_native_unit_of_measurement = "KRW/MJ"
    _attr_native_min_value = 0.0; _attr_native_max_value = 100.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=22.3)

class CurrMonthPriceNumber(RestorableNumberEntity):
    """이번 달 열량단가 엔티티입니다."""
    _attr_translation_key = "curr_month_price"
    _attr_icon = "mdi:cash"
    _attr_native_unit_of_measurement = "KRW/MJ"
    _attr_native_min_value = 0.0; _attr_native_max_value = 100.0; _attr_native_step = 0.0001
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=22.3)

class BaseFeeNumber(RestorableNumberEntity):
    """기본요금 설정을 위한 엔티티입니다."""
    _attr_translation_key = "base_fee"
    _attr_icon = "mdi:cash"
    _attr_native_unit_of_measurement = "KRW"
    _attr_native_min_value = 0; _attr_native_max_value = 10000; _attr_native_step = 1.0
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=DEFAULT_BASE_FEE)

class WinterReductionFeeNumber(RestorableNumberEntity):
    """동절기(12~3월) 월별 경감액 설정을 위한 엔티티입니다."""
    _attr_translation_key = "winter_reduction_fee"
    _attr_icon = "mdi:weather-snowy"
    _attr_native_unit_of_measurement = "KRW"
    _attr_native_min_value = 0; _attr_native_max_value = 1000000; _attr_native_step = 1.0
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=0.0)

class NonWinterReductionFeeNumber(RestorableNumberEntity):
    """동절기 외(4~11월) 월별 경감액 설정을 위한 엔티티입니다."""
    _attr_translation_key = "non_winter_reduction_fee"
    _attr_icon = "mdi:weather-sunny"
    _attr_native_unit_of_measurement = "KRW"
    _attr_native_min_value = 0; _attr_native_max_value = 1000000; _attr_native_step = 1.0
    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        super().__init__(entry, device_info, default_value=0.0)

class MonthlyStartReadingNumber(RestorableNumberEntity):
    """
    월 검침 시작 시점의 계량기 값을 저장하는 엔티티입니다.
    매월 검침일에 자동으로 업데이트되거나, 사용자가 수동으로 수정할 수 있습니다.
    """
    _attr_translation_key = "monthly_start_reading"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "m³"
    # --- FIX: 정수 입력 강제 ---
    # 사용자가 UI에서 값을 입력할 때 소수점 없이 정수로만 입력되도록 step을 1로 설정합니다.
    _attr_native_min_value = 0; _attr_native_max_value = 999999; _attr_native_step = 1.0
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        self.hass = hass
        self._entry = entry
        super().__init__(entry, device_info, default_value=0.0)

    async def async_added_to_hass(self) -> None:
        """
        엔티티가 처음 추가될 때, 저장된 값이 0이면 현재 가스 계량기 값으로 초기화합니다.
        """
        await super().async_added_to_hass()
        # 이미 저장된 값이 0보다 크면 초기화하지 않고 그대로 사용합니다.
        if self.native_value > 0: return

        gas_sensor_id = self._entry.data[CONF_GAS_SENSOR]
        gas_state: State | None = self.hass.states.get(gas_sensor_id)
        
        # 가스 센서의 현재 상태가 유효한 경우에만 초기값을 설정합니다.
        if gas_state and gas_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                # --- FIX: 초기값도 정수로 변환 ---
                # 가스 센서 값에서 소수점을 버리고 정수 부분만 취합니다.
                initial_value = int(float(gas_state.state))
                self._attr_native_value = float(initial_value) # NumberEntity는 float형을 기본으로 사용하므로 형변환
                self.async_write_ha_state()
                LOGGER.info("'%s' 센서 값을 기반으로 초기 시작 검침값을 %s로 설정했습니다.", gas_sensor_id, initial_value)
            except (ValueError, TypeError):
                LOGGER.warning("'%s' 센서의 상태값을 숫자로 변환할 수 없어 초기값이 0으로 유지됩니다.", gas_sensor_id)