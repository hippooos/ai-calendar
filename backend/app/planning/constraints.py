from datetime import datetime, time

from app.planning.scheduler import BusyInterval, SleepWindow


def intervals_overlap(start: datetime, end: datetime, busy: BusyInterval) -> bool:
    return start < busy.end and end > busy.start


def clock_in_sleep(value: time, sleep: SleepWindow) -> bool:
    if sleep.start < sleep.end:
        return sleep.start <= value < sleep.end
    return value >= sleep.start or value < sleep.end


def within_period(start: datetime, end: datetime, period: str, work_end: time | None) -> bool:
    bounds = {
        "morning": (time(6), time(12)),
        "afternoon": (time(12), time(18)),
        "evening": (time(18), time(22)),
        "after_work": (work_end or time(18), time(23)),
        "any": (time(0), time(23, 59, 59)),
    }
    lower, upper = bounds[period]
    return start.time() >= lower and end.time() <= upper

