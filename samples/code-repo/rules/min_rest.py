"""Example rule (fictional): minimum rest before a duty that starts at home base."""

from rules.params import get_param


class MinRestHomeBase:
    """Checks that the rest before a home-base duty is long enough."""

    name = "MIN_REST_HOME_BASE"

    def required_hours(self, airline: str, previous_duty_hours: float) -> float:
        base = get_param(airline, "MIN_REST_HOME_BASE_HOURS")  # 10 for EXA since EXA-142
        return max(base, previous_duty_hours)

    def check(self, airline: str, previous_duty_hours: float, rest_hours: float) -> bool:
        return rest_hours >= self.required_hours(airline, previous_duty_hours)
