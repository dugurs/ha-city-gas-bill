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

    def __init__(self, websession: aiohttp.ClientSession | None):
        """
        공급사를 초기화합니다.
        
        Args:
            websession: 웹사이트에 HTTP 요청을 보낼 때 사용할 aiohttp 클라이언트 세션입니다.
                        코디네이터로부터 전달받습니다.
        """
        self.websession = websession

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
    def name(self) -> str:
        """
        사용자에게 보여질 공급사의 이름(예: "서울도시가스")을 반환해야 합니다.
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