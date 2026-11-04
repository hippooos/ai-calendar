from dataclasses import dataclass, field
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class SleepWindow:
    start: time
    end: time


@dataclass(frozen=True)
class ScheduleTask:
    task_id: str
    title: str
    duration_minutes: int
    occurrences: int
    allowed_weekdays: tuple[int, ...] = ()
    required_periods: tuple[str, ...] = ()
    preferred_periods: tuple[str, ...] = ()
    min_gap_hours: int = 0
    depends_on: tuple[str, ...] = ()
    must_finish_before: datetime | None = None
    frequency_per_week: int = 1
    enforce_frequency_per_week: bool = False
    pacing: str = "neutral"


@dataclass(frozen=True)
class ScheduleRequest:
    window_start: datetime
    window_end: datetime
    tasks: tuple[ScheduleTask, ...]
    busy: tuple[BusyInterval, ...] = ()
    sleep: SleepWindow = SleepWindow(time(23, 0), time(7, 0))
    work_end: time | None = None


@dataclass(frozen=True)
class ScheduledItem:
    task_id: str
    title: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class UnscheduledItem:
    task_id: str
    title: str
    missing_occurrences: int
    reason: str


@dataclass(frozen=True)
class ScheduleResult:
    scheduled_items: tuple[ScheduledItem, ...] = ()
    unscheduled_items: tuple[UnscheduledItem, ...] = ()


def schedule(request: ScheduleRequest) -> ScheduleResult:
    from app.planning.constraints import clock_in_sleep, intervals_overlap, within_period
    from app.planning.scoring import candidate_key

    if request.window_end <= request.window_start:
        raise ValueError("window_end 必须晚于 window_start")

    scheduled: list[ScheduledItem] = []
    unscheduled: list[UnscheduledItem] = []
    by_task: dict[str, list[ScheduledItem]] = {}

    for task in request.tasks:
        task_items: list[ScheduledItem] = []
        dependency_items = [item for dependency in task.depends_on for item in by_task.get(dependency, [])]
        dependency_missing = any(dependency not in by_task or not by_task[dependency] for dependency in task.depends_on)

        if not dependency_missing:
            duration = timedelta(minutes=task.duration_minutes)
            cursor = request.window_start
            minute_remainder = cursor.minute % 30
            if minute_remainder or cursor.second or cursor.microsecond:
                cursor = cursor.replace(second=0, microsecond=0) + timedelta(minutes=30 - minute_remainder)
            candidates: list[datetime] = []
            task_window_end = min(
                request.window_end,
                task.must_finish_before if task.must_finish_before is not None else request.window_end,
            )
            while cursor + duration <= task_window_end:
                end = cursor + duration
                if task.allowed_weekdays and cursor.isoweekday() not in task.allowed_weekdays:
                    cursor += timedelta(minutes=30)
                    continue
                if task.required_periods and not any(within_period(cursor, end, period, request.work_end) for period in task.required_periods):
                    cursor += timedelta(minutes=30)
                    continue
                last_instant = end - timedelta(microseconds=1)
                if clock_in_sleep(cursor.time(), request.sleep) or clock_in_sleep(last_instant.time(), request.sleep):
                    cursor += timedelta(minutes=30)
                    continue
                if dependency_items and cursor < max(item.end for item in dependency_items):
                    cursor += timedelta(minutes=30)
                    continue
                candidates.append(cursor)
                cursor += timedelta(minutes=30)

            occupied = list(request.busy)
            occupied.extend(BusyInterval(item.start, item.end) for item in scheduled)
            remaining_candidates = list(candidates)
            while remaining_candidates and len(task_items) < task.occurrences:
                candidate = min(
                    remaining_candidates,
                    key=lambda value: candidate_key(value, task.preferred_periods, request.work_end, tuple(item.start for item in task_items), task.pacing),
                )
                remaining_candidates.remove(candidate)
                candidate_end = candidate + duration
                if any(intervals_overlap(candidate, candidate_end, interval) for interval in occupied):
                    continue
                if task_items and any(abs(candidate - existing.start) < timedelta(hours=task.min_gap_hours) for existing in task_items):
                    continue
                if task.frequency_per_week >= 7 and any(candidate.date() == existing.start.date() for existing in task_items):
                    continue
                if task.enforce_frequency_per_week:
                    if any(candidate.date() == existing.start.date() for existing in task_items):
                        continue
                    candidate_week = candidate.isocalendar()[:2]
                    occurrences_this_week = sum(
                        existing.start.isocalendar()[:2] == candidate_week
                        for existing in task_items
                    )
                    if occurrences_this_week >= task.frequency_per_week:
                        continue
                item = ScheduledItem(task.task_id, task.title, candidate, candidate_end)
                task_items.append(item)
                scheduled.append(item)
                occupied.append(BusyInterval(candidate, candidate_end))

        by_task[task.task_id] = task_items
        missing = task.occurrences - len(task_items)
        if missing:
            reason = "依赖任务未排入" if dependency_missing else "没有满足全部硬约束和冲突规则的可用时段"
            unscheduled.append(UnscheduledItem(task.task_id, task.title, missing, reason))

    scheduled.sort(key=lambda item: (item.start, item.task_id))
    return ScheduleResult(tuple(scheduled), tuple(unscheduled))
