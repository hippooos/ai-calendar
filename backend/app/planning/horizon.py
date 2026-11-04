import re


DEFAULT_PLANNING_WINDOW_DAYS = 14
MAX_PLANNING_WINDOW_DAYS = 30

_MONTH_HORIZON = re.compile(r"(?:最近|未来|接下来|往后)?\s*(?:一个|1)\s*月|30\s*天")


def planning_window_days(raw_input: str) -> int:
    """Use the requested one-month horizon while keeping the ordinary 14-day default."""
    return MAX_PLANNING_WINDOW_DAYS if _MONTH_HORIZON.search(raw_input) else DEFAULT_PLANNING_WINDOW_DAYS
