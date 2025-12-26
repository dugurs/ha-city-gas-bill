# custom_components/city_gas_bill/config_flow.py

"""
City Gas Bill 통합구성요소의 설정 흐름(Config Flow)을 처리하는 파일입니다.
사용자가 HA UI를 통해 설정을 입력하고 수정하는 과정을 담당합니다.
"""
from __future__ import annotations
from typing import Any

import voluptuous as vol  # 데이터 유효성 검증을 위한 라이브러리

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from .const import (
    DOMAIN, CONF_PROVIDER, CONF_PROVIDER_REGION, CONF_GAS_SENSOR,
    CONF_READING_DAY, CONF_READING_TIME, CONF_READING_CYCLE, CONF_HEATING_TYPE,
    CONF_USAGE_TYPE, CONF_SENSOR_RESETS_MONTHLY # 추가된 상수
)
from .providers import AVAILABLE_PROVIDERS # providers 폴더에서 동적으로 로드된 공급사 목록

def _get_data_schema(current_config: dict | None = None) -> vol.Schema:
    """
    사용자에게 보여줄 설정 폼의 스키마(구조)를 생성하는 헬퍼 함수입니다.
    이 함수는 최초 설정과 옵션 변경 시에 모두 재사용되어 코드 중복을 줄입니다.
    """
    if current_config is None:
        current_config = {}

    # providers 폴더에 있는 모든 공급사들을 가져와서 드롭다운 목록 형태로 만듭니다.
    provider_options: list[SelectOptionDict] = []
    for provider_id, provider_class in AVAILABLE_PROVIDERS.items():
        provider_instance = provider_class(None)
        
        for region_code, region_name in provider_instance.REGIONS.items():
            label = f"{region_name}, {provider_instance.name}"
            provider_options.append(
                SelectOptionDict(
                    value=f"{provider_id}|{region_code}",
                    label=label
                )
            )

    provider_options = sorted(provider_options, key=lambda item: item["label"])

    reading_cycle_options = [
        SelectOptionDict(value="disabled", label="매월"),
        SelectOptionDict(value="odd", label="격월 - 홀수월 (1,3,5...)"),
        SelectOptionDict(value="even", label="격월 - 짝수월 (2,4,6...)"),
        SelectOptionDict(value="quarterly_1", label="3개월 - 1, 4, 7, 10월"),
        SelectOptionDict(value="quarterly_2", label="3개월 - 2, 5, 8, 11월"),
        SelectOptionDict(value="quarterly_3", label="3개월 - 3, 6, 9, 12월"),
    ]

    # '난방 타입' 옵션을 세분화합니다.
    heating_type_options = [
        SelectOptionDict(value="residential", label="주택난방(개별)"),
        SelectOptionDict(value="central_cogeneration", label="중앙난방(공동열전용)"),
        SelectOptionDict(value="central_chp", label="중앙난방(공동열병합용)"),
    ]

    # '사용 용도' 드롭다운 메뉴에 표시될 옵션을 정의합니다.
    usage_type_options = [
        SelectOptionDict(value="combined", label="취사+난방 (경계값 사용)"),
        SelectOptionDict(value="cooking_only", label="취사전용 (취사단가만 사용)"),
        SelectOptionDict(value="heating_only", label="난방전용 (난방단가만 사용)"),
    ]

    default_provider_selection = current_config.get(CONF_PROVIDER)
    if current_config.get(CONF_PROVIDER_REGION):
        default_provider_selection = f"{default_provider_selection}|{current_config.get(CONF_PROVIDER_REGION)}"

    return vol.Schema({
        vol.Required(
            CONF_PROVIDER,
            default=default_provider_selection,
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=provider_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_USAGE_TYPE,
            default=current_config.get(CONF_USAGE_TYPE, "combined"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=usage_type_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_USAGE_TYPE
            )
        ),
        vol.Required(
            CONF_HEATING_TYPE,
            default=current_config.get(CONF_HEATING_TYPE, "residential"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=heating_type_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_HEATING_TYPE
            )
        ),
        vol.Required(
            CONF_GAS_SENSOR,
            default=current_config.get(CONF_GAS_SENSOR),
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="gas"),
        ),
        vol.Optional(
            CONF_SENSOR_RESETS_MONTHLY,
            default=current_config.get(CONF_SENSOR_RESETS_MONTHLY, False),
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_READING_DAY,
            default=current_config.get(CONF_READING_DAY, 26),
        ): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=28, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Coerce(int)
        ),
        vol.Required(
            CONF_READING_TIME,
            default=current_config.get(CONF_READING_TIME, "00:00"),
        ): selector.TimeSelector(),
        vol.Required(
            CONF_READING_CYCLE,
            default=current_config.get(CONF_READING_CYCLE, "disabled"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=reading_cycle_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_READING_CYCLE 
            )
        ),
    })

def _parse_provider_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """
    '공급사ID|지역코드' 형태의 입력값을 파싱하여 분리하는 헬퍼 함수입니다.
    """
    provider_selection = user_input.pop(CONF_PROVIDER)
    parts = provider_selection.split('|')
    user_input[CONF_PROVIDER] = parts[0]
    if len(parts) > 1:
        user_input[CONF_PROVIDER_REGION] = parts[1]
    return user_input

class CityGasBillConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    최초 설정(통합구성요소 추가) 과정을 처리하는 Config Flow 핸들러입니다.
    """
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """
        Config Flow와 Options Flow를 연결하는 메소드입니다.
        """
        return CityGasBillOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        'user' 단계의 설정 과정을 처리합니다.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        
        errors = {}
        
        if user_input is not None:
            provider_selection = user_input[CONF_PROVIDER]
            provider_id = provider_selection.split('|')[0]
            heating_type = user_input[CONF_HEATING_TYPE]
            
            provider_class = AVAILABLE_PROVIDERS.get(provider_id)
            # 세분화된 중앙난방 옵션을 모두 확인합니다.
            if provider_class and heating_type in ["central_cogeneration", "central_chp"] and not provider_class(None).SUPPORTS_CENTRAL_HEATING:
                errors["base"] = "central_heating_not_supported"
            else:
                data = _parse_provider_input(user_input)
                return self.async_create_entry(title="City Gas Bill", data=data)
        
        return self.async_show_form(
            step_id="user",
            data_schema=_get_data_schema(),
            errors=errors
        )

class CityGasBillOptionsFlowHandler(OptionsFlow):
    """
    이미 추가된 통합구성요소의 설정을 '구성' 버튼을 통해 변경하는 과정을 처리하는 Options Flow 핸들러입니다.
    """
    def __init__(self, config_entry: ConfigEntry) -> None:
        """옵션 흐름을 초기화합니다."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """'init' 단계의 옵션 설정 과정을 관리합니다."""
        errors = {}
        if user_input is not None:
            provider_selection = user_input[CONF_PROVIDER]
            provider_id = provider_selection.split('|')[0]
            heating_type = user_input[CONF_HEATING_TYPE]
            
            provider_class = AVAILABLE_PROVIDERS.get(provider_id)
            # 세분화된 중앙난방 옵션을 모두 확인합니다.
            if provider_class and heating_type in ["central_cogeneration", "central_chp"] and not provider_class(None).SUPPORTS_CENTRAL_HEATING:
                errors["base"] = "central_heating_not_supported"
            else:
                data = _parse_provider_input(user_input)
                return self.async_create_entry(title="", data=data)

        current_config = self._config_entry.options or self._config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=_get_data_schema(current_config),
            errors=errors
        )