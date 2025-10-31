from __future__ import annotations
from datetime import date, timedelta
import calendar
from dateutil.relativedelta import relativedelta


class GasBillCalculator:
    """가스 요금 계산을 담당하는 공용 계산기 클래스.

    - 검침 주기(검침일)를 기준으로 기간 분할(전월/당월 일수)을 계산합니다.
    - 보정계수와 열량/단가 정보를 받아 총 요금을 산출합니다.
    - 격월(odd/even) 결제 사이클의 합산 여부 판단/집계를 제공합니다.
    """

    def __init__(self, reading_day: int) -> None:
        self._reading_day = reading_day

    def get_last_reading_date(self, today: date) -> date:
        """오늘 날짜와 설정된 검침일을 바탕으로 직전 검침일을 반환합니다.

        reading_day가 0이면 말일 검침을 의미합니다.
        """
        if self._reading_day == 0:
            day = calendar.monthrange(today.year, today.month)[1]
            if today.day == day:
                return today
            last_month = today - relativedelta(months=1)
            return last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
        if today.day >= self._reading_day:
            return today.replace(day=self._reading_day)
        return (today - relativedelta(months=1)).replace(day=self._reading_day)

    def get_next_reading_date(self, start_date: date) -> date:
        """직전 검침일 기준 다음 검침일(+1개월)을 반환합니다.

        reading_day가 0이면 다음 달 말일을 반환합니다.
        """
        next_month = start_date + relativedelta(months=1)
        if self._reading_day == 0:
            return next_month.replace(day=calendar.monthrange(next_month.year, next_month.month)[1])
        return next_month.replace(day=self._reading_day)

    def split_days_for_period(self, today: date) -> tuple[date, int, int, int]:
        """검침 주기를 기준으로 전월/당월에 해당하는 일수 분해.

        반환값: (검침시작일, 전월일수, 당월일수, 총일수)
        """
        start_of_period = self.get_last_reading_date(today)
        prev_month_days, curr_month_days = 0, 0
        if today >= start_of_period:
            first_day_of_curr_month = today.replace(day=1)
            if start_of_period < first_day_of_curr_month:
                last_day_of_prev_month = first_day_of_curr_month - timedelta(days=1)
                prev_month_days = (last_day_of_prev_month - start_of_period).days + 1
            curr_month_start = max(start_of_period, first_day_of_curr_month)
            curr_month_days = (today - curr_month_start).days + 1
        total_days = prev_month_days + curr_month_days
        return start_of_period, prev_month_days, curr_month_days, total_days

    def compute_total_bill_from_usage(
        self,
        corrected_usage: float,
        base_fee: float,
        prev_heat: float,
        curr_heat: float,
        prev_price: float,
        curr_price: float,
        today: date,
    ) -> tuple[int, dict]:
        """보정된 월사용량과 요율 정보를 바탕으로 총요금과 속성을 계산합니다.

        - corrected_usage: 보정계수 적용 후 사용량
        - base_fee: 기본요금
        - prev/curr_heat, prev/curr_price: 전월/당월 열량·단가
        - today: 계산 기준일(보통 현재일)
        반환: (총요금[반올림 정수], 속성 dict)
        """
        start_of_period, prev_days, curr_days, total_days = self.split_days_for_period(today)
        if total_days <= 0:
            total_fee = round(base_fee * 1.1)
            attrs = {
                "start_date": start_of_period.isoformat(),
                "end_date": today.isoformat(),
                "days_total": 0,
            }
            return total_fee, attrs

        prev_usage = corrected_usage * (prev_days / total_days)
        curr_usage = corrected_usage * (curr_days / total_days)
        prev_fee = prev_usage * prev_heat * prev_price
        curr_fee = curr_usage * curr_heat * curr_price
        total_fee = round((base_fee + prev_fee + curr_fee) * 1.1)
        attrs = {
            "start_date": start_of_period.isoformat(),
            "end_date": today.isoformat(),
            "days_total": total_days,
            "days_prev_month": prev_days,
            "days_curr_month": curr_days,
            "prev_month_calculated_fee": round(prev_fee),
            "curr_month_calculated_fee": round(curr_fee),
        }
        return total_fee, attrs


    # -------- 격월 헬퍼 --------
    @staticmethod
    def is_billing_month(today: date, bimonthly_cycle: str | None) -> bool:
        """해당 날짜가 격월 결제 사이클의 청구월인지 여부를 반환합니다.

        bimonthly_cycle: "odd" | "even" | "disabled"
        """
        if not bimonthly_cycle or bimonthly_cycle == "disabled":
            return False
        is_odd = today.month % 2 == 1
        is_even = not is_odd
        if bimonthly_cycle == "odd":
            return is_odd
        if bimonthly_cycle == "even":
            return is_even
        return False

    @classmethod
    def aggregate_bimonthly(cls, current_value: float, prev_value: float, today: date, bimonthly_cycle: str | None) -> float:
        """격월 청구월에는 직전값과 합산, 그 외에는 현재값만 반환합니다."""
        if cls.is_billing_month(today, bimonthly_cycle):
            return current_value + prev_value
        return current_value


