# custom_components/city_gas_bill/providers/__init__.py

"""
City Gas Bill 통합구성요소의 공급사(Provider)들을 동적으로 발견하고 등록하는 역할을 합니다.
"""
import os
import importlib  # 파이썬 모듈을 동적으로(코드 실행 중에) 불러오기 위한 라이브러리
import inspect    # 모듈 안의 클래스 같은 객체들을 검사하기 위한 라이브러리
import logging
from pathlib import Path
from typing import Final

from .base import GasProvider  # 공급사의 기본 클래스

_LOGGER = logging.getLogger(__name__)

def discover_providers() -> dict[str, type[GasProvider]]:
    """
    'providers' 디렉토리 안에서 GasProvider를 상속받는 클래스들을
    동적으로 찾아내고 로드하여 딕셔너리 형태로 반환합니다.
    """
    providers = {}  # 발견된 공급사들을 저장할 빈 딕셔너리
    
    # 현재 이 파일(__init__.py)이 위치한 디렉토리의 경로를 가져옵니다.
    # 즉, '.../custom_components/city_gas_bill/providers/' 경로를 의미합니다.
    provider_dir = Path(__file__).parent

    # 해당 디렉토리 안에 있는 모든 파이썬 파일(*.py)을 순회합니다.
    for f in provider_dir.glob("*.py"):
        # 파일 이름에서 확장자(.py)를 제외한 부분을 가져옵니다 (예: "seoul_gas").
        module_name = f.stem
        
        # 자기 자신(__init__.py)이나 부모 클래스가 정의된 base.py 파일은 건너뜁니다.
        if module_name in ("__init__", "base"):
            continue

        try:
            # importlib을 사용하여 파일 이름을 기반으로 파이썬 모듈을 동적으로 불러옵니다.
            # (예: from . import seoul_gas 와 동일한 효과)
            module = importlib.import_module(f".{module_name}", __package__)
            
            # 불러온 모듈 안에 정의된 모든 클래스들을 검사합니다.
            for _, cls in inspect.getmembers(module, inspect.isclass):
                # 그 클래스가 GasProvider를 상속받았는지, 그리고 GasProvider 자체는 아닌지 확인합니다.
                if issubclass(cls, GasProvider) and cls is not GasProvider:
                    # 조건을 만족하는 클래스를 찾으면,
                    # 공급사 ID(파일 이름)를 키로, 클래스 자체를 값으로 하여 딕셔너리에 추가합니다.
                    provider_id = module_name
                    providers[provider_id] = cls
                    _LOGGER.debug("가스 공급사를 발견했습니다: %s", provider_id)
                    # 한 파일에 하나의 공급사만 있다고 가정하고 다음 파일로 넘어갑니다.
                    break 
        except Exception as e:
            # 모듈을 불러오거나 클래스를 검사하는 도중 오류가 발생하면 로그를 남깁니다.
            _LOGGER.error("%s 파일에서 공급사를 불러오는 데 실패했습니다: %s", f.name, e)

    return providers

# 위 함수를 실행하여 발견된 모든 공급사들을 AVAILABLE_PROVIDERS 라는 상수에 최종 저장합니다.
# 이 상수는 config_flow.py, coordinator.py 등 다른 파일에서 임포트하여 사용하게 됩니다.
AVAILABLE_PROVIDERS: Final = discover_providers()