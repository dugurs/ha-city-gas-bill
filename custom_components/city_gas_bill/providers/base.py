# custom_components/city_gas_bill/providers/base.py

"""
모든 도시가스 공급사(Provider) 클래스들의 기본이 되는 추상 클래스를 정의합니다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod  # 추상 기본 클래스를 만들기 위한 모듈
import aiohttp  # 비동기 HTTP 요청을 위한 타입 힌팅용

class GasProvider(ABC):
    """
    모든 지역별 도시가스 공급사를 위한 추상 기본 클래스입니다.
    새로운 공급사를 추가하려면 반드시 이 클래스를 상속받아야 합니다.
    """

    def __init__(self, websession: aiohttp.ClientSession | None, region: str | None = None, usage_type: str | None = None):
        """
        공급사를 초기화합니다.
        
        Args:
            websession: 웹사이트에 HTTP 요청을 보낼 때 사용할 aiohttp 클라이언트 세션입니다.
                        코디네이터로부터 전달받습니다.
            region: 공급사가 지역별로 다른 로직을 가져야 할 때 사용되는 지역 코드입니다.
            usage_type: 사용자가 설정에서 선택한 가스 용도 (예: "residential", "central").
        """
        self.websession = websession
        self.region = region
        self.usage_type = usage_type

    # --- 아래의 4개 속성/메소드는 @abstractmethod로 선언되어 ---
    # --- 이 클래스를 상속받는 모든 자식 클래스에서 반드시 구현해야 합니다. ---
    # --- 만약 하나라도 구현하지 않으면, Home Assistant 시작 시 오류가 발생합니다. ---

    @property
    @abstractmethod
    def id(self) -> str:
        """
        공급사의 고유 ID를 반환해야 합니다.
        이 ID는 파일 이름(예: seoul_gas.py -> "seoul_gas")과 일치해야 하며,
        내부적으로 공급사를 식별하는 데 사용됩니다.
        """

    @property
    @abstractmethod
    def REGIONS(self) -> dict[str, str]:
        """
        이 공급사가 지원하는 지역 목록을 반환해야 합니다.
        - Key: API 호출 등에 사용될 내부적인 지역 코드 (문자열)
        - Value: UI에 표시될 지역 이름 (문자열)
        예: {"1": "서울", "8": "경기"}
        """

    @property
    def SUPPORTS_CENTRAL_HEATING(self) -> bool:
        """
        이 공급사가 '중앙난방' 요금제를 지원하는지 여부를 반환합니다.
        자식 클래스에서 중앙난방을 지원하는 경우 True로 재정의해야 합니다.
        """
        return False

    @property
    @abstractmethod
    def name(self) -> str:
        """
        사용자에게 보여질 공급사이름 (예: "서울도시가스")을 반환해야 합니다.
        이 이름은 설정 UI의 드롭다운 목록에 표시됩니다.
        """

    @abstractmethod
    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        웹사이트에서 '평균열량' 데이터를 스크래핑하는 비동기 메소드입니다.
        성공 시, 아래와 같은 형식의 딕셔너리를 반환해야 합니다:
        {
            "prev_month_heat": 42.5,
            "curr_month_heat": 43.0
        }
        실패 시에는 None을 반환해야 합니다.
        """

    @abstractmethod
    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        웹사이트에서 '열량단가' 데이터를 스크래핑하는 비동기 메소드입니다.
        성공 시, 아래와 같은 형식의 딕셔너리를 반환해야 합니다:
        {
            "prev_month_price": 22.1,
            "curr_month_price": 22.3
        }
        실패 시에는 None을 반환해야 합니다.
        """

    @abstractmethod
    async def scrape_base_fee(self) -> float | None:
        """
        웹사이트에서 '기본요금' 데이터를 스크래핑하는 비동기 메소드입니다.
        성공 시, 숫자(float)를 반환해야 합니다.
        실패 시에는 None을 반환해야 합니다.
        지원하지 않는 경우에도 None을 반환합니다.
        """

    async def scrape_cooking_heating_boundary(self) -> float | None:
        """
        (선택적) 웹사이트에서 '취사/난방 경계값(MJ)'을 스크래핑하는 비동기 메소드입니다.
        이 기능을 지원하는 공급사는 이 메소드를 재정의(override)해야 합니다.
        성공 시 숫자(float)를, 실패 또는 미지원 시 None을 반환합니다.
        """
        return None