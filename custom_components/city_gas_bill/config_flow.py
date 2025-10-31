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

from .const import DOMAIN, CONF_PROVIDER, CONF_GAS_SENSOR, CONF_READING_DAY, CONF_READING_TIME, CONF_BIMONTHLY_CYCLE
from .providers import AVAILABLE_PROVIDERS # providers 폴더에서 동적으로 로드된 공급사 목록

def _get_data_schema(current_config: dict | None = None) -> vol.Schema:
    """
    사용자에게 보여줄 설정 폼의 스키마(구조)를 생성하는 헬퍼 함수입니다.
    이 함수는 최초 설정과 옵션 변경 시에 모두 재사용되어 코드 중복을 줄입니다.
    """
    if current_config is None:
        current_config = {}

    # providers 폴더에 있는 모든 공급사들을 가져와서 드롭다운 목록 형태로 만듭니다.
    # 이 덕분에 새로운 공급사 파일을 추가하기만 하면 자동으로 설정 목록에 나타납니다.
    provider_options: list[SelectOptionDict] = sorted(
        [
            SelectOptionDict(value=provider_id, label=provider(None).name)
            for provider_id, provider in AVAILABLE_PROVIDERS.items()
        ],
        key=lambda item: item["label"], # 가나다 순으로 정렬
    )

    # '검침 주기' 드롭다운 메뉴에 표시될 옵션을 정의합니다.
    # label: 사용자에게 보여지는 텍스트
    # value: 코드 내부에서 사용되는 값 ('disabled', 'odd', 'even')
    bimonthly_cycle_options = [
        SelectOptionDict(value="disabled", label="매월"),
        SelectOptionDict(value="odd", label="격월 - 홀수월"),
        SelectOptionDict(value="even", label="격월 - 짝수월"),
    ]

    # voluptuous를 사용하여 설정 폼의 각 필드를 정의합니다.
    return vol.Schema({
        # '도시가스 공급사' 필드 (드롭다운 메뉴)
        vol.Required(
            CONF_PROVIDER,
            default=current_config.get(CONF_PROVIDER), # 기존 설정값이 있으면 기본값으로 보여줌
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=provider_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        # '가스 사용량 센서' 필드 (엔티티 선택 도우미)
        vol.Required(
            CONF_GAS_SENSOR,
            default=current_config.get(CONF_GAS_SENSOR),
        ): selector.EntitySelector(
            # 사용자가 쉽게 찾을 수 있도록 'sensor' 도메인과 'gas' device_class를 가진 엔티티만 필터링합니다.
            selector.EntitySelectorConfig(domain="sensor", device_class="gas"),
        ),
        # '월 정기 검침일' 필드 (숫자 입력 상자)
        vol.Required(
            CONF_READING_DAY,
            default=current_config.get(CONF_READING_DAY, 26), # 기본값은 26일로 설정
        ): vol.All(
            selector.NumberSelector(
                # 입력값의 범위를 0(말일)부터 28일까지로 제한합니다.
                selector.NumberSelectorConfig(min=0, max=28, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Coerce(int) # 입력된 값을 정수(int) 타입으로 변환
        ),
        # '정기 검침시간' 필드 (시간 선택자)
        vol.Required(
            CONF_READING_TIME,
            default=current_config.get(CONF_READING_TIME, "00:00"),
        ): selector.TimeSelector(),
        # '검침 주기' 필드 (드롭다운 메뉴)
        vol.Required(
            CONF_BIMONTHLY_CYCLE,
            default=current_config.get(CONF_BIMONTHLY_CYCLE, "disabled"), # 기본값은 '매월'
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=bimonthly_cycle_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
                # 번역 파일(ko.json 등)에서 이 필드의 라벨("검침 주기")을 찾아 UI에 표시합니다.
                translation_key=CONF_BIMONTHLY_CYCLE 
            )
        ),
    })

class CityGasBillConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    최초 설정(통합구성요소 추가) 과정을 처리하는 Config Flow 핸들러입니다.
    """
    VERSION = 1 # 설정 데이터의 버전을 명시합니다. 나중에 스키마가 변경될 때 마이그레이션을 위해 사용됩니다.

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """
        Config Flow와 Options Flow를 연결하는 메소드입니다.
        HA가 '구성' 버튼을 눌렀을 때 Options Flow를 찾을 수 있도록 해줍니다.
        """
        return CityGasBillOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        'user' 단계의 설정 과정을 처리합니다. 사용자가 처음 통합구성요소를 추가할 때 호출됩니다.
        """
        # 이미 이 통합구성요소가 설정되어 있는지 확인합니다.
        if self._async_current_entries():
            # 이미 있다면, 중복 추가가 불가능하다는 메시지와 함께 설정을 중단합니다.
            return self.async_abort(reason="single_instance_allowed")
        
        # 사용자가 폼을 채우고 '제출' 버튼을 눌렀다면 user_input에 값이 들어옵니다.
        if user_input is not None:
            # 입력받은 설정값을 사용하여 새로운 설정 엔트리(ConfigEntry)를 생성하고 설정을 완료합니다.
            return self.async_create_entry(title="도시가스 요금", data=user_input)
        
        # user_input이 None이면, 사용자에게 설정 폼을 처음 보여주는 단계입니다.
        # _get_data_schema()를 호출하여 생성된 폼을 사용자에게 표시합니다.
        return self.async_show_form(step_id="user", data_schema=_get_data_schema())

class CityGasBillOptionsFlowHandler(OptionsFlow):
    """
    이미 추가된 통합구성요소의 설정을 '구성' 버튼을 통해 변경하는 과정을 처리하는 Options Flow 핸들러입니다.
    """
    def __init__(self, config_entry: ConfigEntry) -> None:
        """옵션 흐름을 초기화합니다."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """'init' 단계의 옵션 설정 과정을 관리합니다."""
        # 사용자가 옵션 변경 폼을 제출했다면 user_input에 값이 들어옵니다.
        if user_input is not None:
            # 빈 title과 함께 엔트리를 생성하여 기존 옵션을 업데이트하고 완료합니다.
            return self.async_create_entry(title="", data=user_input)

        # 현재 저장된 설정값(옵션 또는 최초 데이터)을 가져옵니다.
        current_config = self.config_entry.options or self.config_entry.data

        # 현재 설정값을 기본값으로 채운 폼을 사용자에게 보여줍니다.
        return self.async_show_form(
            step_id="init",
            data_schema=_get_data_schema(current_config),
        )