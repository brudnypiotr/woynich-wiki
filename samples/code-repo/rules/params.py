"""Rule parameters per airline (fictional)."""

PARAMS = {
    "EXA": {"MIN_REST_HOME_BASE_HOURS": 10, "MIN_REST_AWAY_HOURS": 10, "EXTENDED_REST_HOURS": 36},
    "DEFAULT": {"MIN_REST_HOME_BASE_HOURS": 12, "MIN_REST_AWAY_HOURS": 10, "EXTENDED_REST_HOURS": 36},
}


def get_param(airline: str, name: str):
    return PARAMS.get(airline, PARAMS["DEFAULT"]).get(name, PARAMS["DEFAULT"][name])
