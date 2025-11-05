# custom_components/city_gas_bill/providers/manual.py

"""
웹 스크래핑을 하지 않고, 사용자가 직접 데이터를 입력할 수 있도록 지원하는
'수동 입력' 공급사입니다.
"""
from __future__ import annotations
from typing import Final # Final 임포트

from .base import GasProvider  # 모든 공급사의 부모 클래스

class ManualProvider(GasProvider):
    """
    사용자가 직접 평균열량 및 열량단가 데이터를 관리하고자 할 때 사용하는 공급사 클래스입니다.
    """
    REGIONS: Final = {"manual": " 수동 입력"}

    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "manual"

    @property
    def name(self) -> str:
        """UI 설정 화면에 표시될 이름을 반환합니다."""
        return "직접 관리"

    async def scrape_heat_data(self) -> dict[str, float] | None:
        """
        평균열량 데이터를 스크래핑하지 않습니다.
        
        항상 None을 반환하여, 코디네이터가 사용자가 수동으로 입력한
        Number 엔티티의 값을 덮어쓰지 않도록 합니다.
        """
        return None

    async def scrape_price_data(self) -> dict[str, float] | None:
        """
        열량단가 데이터를 스크래핑하지 않습니다.
        
        항상 None을 반환하여, 코디네이터가 사용자가 수동으로 입력한
        Number 엔티티의 값을 덮어쓰지 않도록 합니다.
        """
        return None