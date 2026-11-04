from datetime import datetime, time, timedelta


def matches_period(value: time, period: str, work_end: time | None) -> bool:
    if period == "any":
        return True
    if period == "morning":
        return time(6) <= value < time(12)
    if period == "afternoon":
        return time(12) <= value < time(18)
    if period == "evening":
        return time(18) <= value < time(22)
    if period == "after_work":
        return (work_end or time(18)) <= value < time(23)
    return False


def candidate_key(
    start: datetime,
    preferred_periods: tuple[str, ...],
    work_end: time | None,
    existing_starts: tuple[datetime, ...] = (),
    pacing: str = "neutral",
) -> tuple[int, int, datetime]:
    preferred = not preferred_periods or any(matches_period(start.time(), period, work_end) for period in preferred_periods)
    same_day = any(value.date() == start.date() for value in existing_starts)
    pacing_penalty = 0
    if pacing == "distributed":
        pacing_penalty = 1 if same_day else 0
    elif pacing == "compact":
        pacing_penalty = 0 if same_day else 1
    elif pacing == "fragmented":
        # “碎片时间”要求分散：优先换天，其次避免把多次安排挤在 3 小时内的相邻时段
        pacing_penalty = 2 if same_day else 0
        if any(abs(value - start) < timedelta(hours=3) for value in existing_starts):
            pacing_penalty += 1
    return (0 if preferred else 1, pacing_penalty, start)
