# custom_components/city_gas_bill/providers/incheon_gas.py

"""
인천도시가스(코원에너지서비스) 데이터를 스크래핑하는 공급사 구현 파일입니다.
"""
from __future__ import annotations

from .koone_base import KooneEnergyProvider # 최적화: 공통 로직을 담은 부모 클래스 임포트

class IncheonGasProvider(KooneEnergyProvider):
    """
    인천도시가스(코원에너지서비스)의 데이터를 가져오는 클래스입니다.
    실제 데이터 조회 로직은 KooneEnergyProvider에 위임합니다.
    """
    
    @property
    def id(self) -> str:
        """공급사 고유 ID를 반환합니다."""
        return "incheon_gas"

    @property
    def name(self) -> str:
        """UI에 표시될 공급사 이름을 반환합니다."""
        return "인천, 코원에너지서비스"
    
    @property
    def region_code(self) -> str:
        """단가 조회에 사용될 인천 지역 코드를 반환합니다."""
        return "1"