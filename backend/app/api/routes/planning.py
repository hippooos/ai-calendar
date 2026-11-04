from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.routes.profile import ensure_profile
from app.domain.enums import PlanningStatus
from app.persistence.repositories import CalendarRepository, DraftRepository, PlanningSessionRepository
from app.persistence.tables import Draft, DraftItem, PlanningSession, UserProfile
from app.planning.orchestrator import InvalidStateTransition, PlanningOrchestrator
from app.planning.questions import present_questions
from app.planning.horizon import planning_window_days
from app.planning.scheduler import BusyInterval, ScheduleRequest, ScheduleTask, SleepWindow, schedule
from app.prompts.schemas import PhaseBResult, TaskTemplate

router = APIRouter(prefix="/api/planning/sessions", tags=["planning"])


class SubmitPayload(BaseModel):
    raw_input: str
    reference_now: datetime | None = None


class AnswersPayload(BaseModel):
    answers: dict[str, str]


def session_response(row) -> dict:
    return {"id":row.id,"status":row.status,"questions":present_questions(row.phase_a_json),"error_code":row.error_code}


def planning_context(db: Session) -> dict:
    profile = ensure_profile(db)
    return {
        "timezone": profile.timezone,
        "user_profile": {
            "work_start": profile.work_start,
            "work_end": profile.work_end,
            "sleep_start": profile.sleep_start,
            "sleep_end": profile.sleep_end,
            "preferences": profile.preferences_json,
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit(payload: SubmitPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    if not payload.raw_input.strip():
        raise HTTPException(422, "raw_input 不能为空")
    profile = ensure_profile(db)
    timezone_value = ZoneInfo(profile.timezone)
    reference_now = payload.reference_now or datetime.now(timezone.utc)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone_value)
    else:
        reference_now = reference_now.astimezone(timezone_value)
    orchestrator = PlanningOrchestrator(PlanningSessionRepository(db), request.app.state.llm_service)
    row = await orchestrator.submit(raw_input=payload.raw_input, reference_now=reference_now, context=planning_context(db))
    return session_response(row)


@router.post("/{session_id}/answers")
async def answer_questions(session_id: str, payload: AnswersPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    orchestrator = PlanningOrchestrator(PlanningSessionRepository(db), request.app.state.llm_service)
    try:
        row = await orchestrator.answer(session_id=session_id, answers=payload.answers, context=planning_context(db))
    except KeyError:
        raise HTTPException(404, "规划会话不存在")
    except (InvalidStateTransition, ValueError) as exc:
        raise HTTPException(409, str(exc))
    return session_response(row)


def parse_clock(value: str) -> time:
    return time.fromisoformat(value)


@router.post("/{session_id}/generate-draft", status_code=status.HTTP_201_CREATED)
async def generate_draft(session_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    repo = PlanningSessionRepository(db)
    orchestrator = PlanningOrchestrator(repo, request.app.state.llm_service)
    try:
        row = await orchestrator.build_templates(session_id=session_id, context=planning_context(db))
    except KeyError:
        raise HTTPException(404, "规划会话不存在")
    except InvalidStateTransition as exc:
        raise HTTPException(409, str(exc))
    phase_b = PhaseBResult.model_validate(row.phase_b_json)
    profile = ensure_profile(db)
    tz = ZoneInfo(profile.timezone)
    reference = row.reference_now
    if reference.tzinfo is None: reference = reference.replace(tzinfo=tz)
    else: reference = reference.astimezone(tz)
    window_days = planning_window_days(row.raw_input)
    window_end = reference + timedelta(days=window_days)
    busy_rows = CalendarRepository(db).overlapping(start=reference, end=window_end)
    calendar_busy = tuple(BusyInterval(event.start_at.astimezone(tz), event.end_at.astimezone(tz)) for event in busy_rows)
    fixed_slots = []
    for fixed in phase_b.fixed_events:
        start_at = datetime.combine(fixed.date, fixed.start_time, tz)
        end_at = datetime.combine(fixed.date, fixed.end_time, tz) if fixed.end_time else start_at + timedelta(minutes=fixed.duration_minutes)
        fixed_slots.append((fixed, start_at, end_at))
    fixed_busy = tuple(BusyInterval(start_at, end_at) for _, start_at, end_at in fixed_slots if reference <= start_at and end_at <= window_end)
    busy = calendar_busy + fixed_busy
    phase_a_items = {
        item.get("item_id"): item
        for item in (row.phase_a_json or {}).get("items", [])
    }

    def has_explicit_weekly_frequency(source_item_id: str) -> bool:
        source = phase_a_items.get(source_item_id, {})
        hard = source.get("hard_constraints", {})
        stated = str(source.get("facts", {}).get("stated_frequency") or "")
        return hard.get("required_frequency_per_week") is not None or "每周" in stated or "周末" in stated

    tasks = tuple(
        ScheduleTask(
            task_id=task.task_id,
            title=task.title,
            duration_minutes=task.duration_minutes,
            occurrences=task.occurrences_within_window,
            allowed_weekdays=tuple(task.hard_constraints.allowed_weekdays),
            required_periods=tuple(task.hard_constraints.required_periods),
            preferred_periods=tuple(task.soft_preferences.preferred_periods),
            min_gap_hours=task.min_gap_hours,
            depends_on=tuple(task.depends_on),
            must_finish_before=task.hard_constraints.must_finish_before
            or (datetime.combine(plan.deadline + timedelta(days=1), time.min, tz) if plan.deadline else None),
            frequency_per_week=task.frequency_per_week,
            enforce_frequency_per_week=has_explicit_weekly_frequency(plan.source_item_id),
            pacing=task.soft_preferences.pacing,
        )
        for plan in phase_b.goal_plans for task in plan.task_templates
    )
    task_templates = {
        task.task_id: task
        for plan in phase_b.goal_plans
        for task in plan.task_templates
    }
    scheduled = schedule(ScheduleRequest(reference, window_end, tasks, busy, SleepWindow(parse_clock(profile.sleep_start),parse_clock(profile.sleep_end)),parse_clock(profile.work_end)))
    scheduled_counts = {}
    for entry in scheduled.scheduled_items:
        scheduled_counts[entry.task_id] = scheduled_counts.get(entry.task_id, 0) + 1
    source_items = {item.get("item_id"): item for item in (row.phase_a_json or {}).get("items", [])}

    def user_required_occurrences(task) -> bool:
        source_item = source_items.get(next((plan.source_item_id for plan in phase_b.goal_plans if any(candidate.task_id == task.task_id for candidate in plan.task_templates)), ""), {})
        if source_item.get("hard_constraints", {}).get("required_occurrences_within_window") is not None:
            return True
        return any(
            entry.field_path == "task_template.occurrences_within_window" and entry.source.value == "user_input"
            for entry in task.provenance
        )

    adjusted_tasks = {
        entry.task_id: scheduled_counts.get(entry.task_id, 0)
        for entry in scheduled.unscheduled_items
        if not user_required_occurrences(task_templates[entry.task_id])
    }

    def capacity_note(task: TaskTemplate) -> str:
        gap = task.min_gap_hours
        if gap <= 0:
            return ""
        finish = task.hard_constraints.must_finish_before or window_end
        fit = max(0, int((finish - reference).total_seconds() // (gap * 3600)) + 1)
        return (
            f"容量参考：按最小间隔 {gap} 小时、{finish:%m月%d日%H:%M} 前"
            f"最多容纳约 {fit} 次，已排入 {scheduled_counts.get(task.task_id, 0)} 次。"
        )

    def template_for_draft(task_id: str) -> dict:
        task = task_templates[task_id]
        payload = task.model_dump(mode="json")
        if task_id in adjusted_tasks:
            payload["occurrences_within_window"] = adjusted_tasks[task_id]
            payload["provenance"].append({
                "field_path": "task_template.occurrences_within_window",
                "value": adjusted_tasks[task_id],
                "source": "system_derived",
                "reason": f"AI 原建议 {task.occurrences_within_window} 次，受截止时间、日历冲突和可用时段限制，已调整为 {adjusted_tasks[task_id]} 次。",
                "user_editable": True,
                "display_label": "系统推导",
            })
        return payload
    items = []
    for index, (fixed, start_at, end_at) in enumerate(fixed_slots):
        source_item = phase_a_items.get(fixed.source_item_id, {})
        provenance = source_item.get("provenance", [])
        if start_at < reference or end_at > window_end:
            items.append({"kind":"unscheduled","title":fixed.title,"start_at":None,"end_at":None,"provenance_json":provenance,"conflict_state":"outside_window","unscheduled_reason":f"明确安排不在未来{window_days}天规划窗口内"})
            continue
        other_fixed = tuple(
            BusyInterval(other_start, other_end)
            for other_index, (_, other_start, other_end) in enumerate(fixed_slots)
            if other_index != index and reference <= other_start and other_end <= window_end
        )
        has_conflict = any(start_at < interval.end and end_at > interval.start for interval in calendar_busy + other_fixed)
        items.append({"kind":"fixed","title":fixed.title,"start_at":start_at,"end_at":end_at,"provenance_json":provenance,"conflict_state":"busy_conflict" if has_conflict else None})
    for entry in scheduled.scheduled_items:
        template = task_templates[entry.task_id]
        template_payload = template_for_draft(entry.task_id)
        items.append({"kind":"scheduled","title":entry.title,"start_at":entry.start,"end_at":entry.end,"task_template_json":template_payload,"provenance_json":template_payload["provenance"],"conflict_state":None})
    for entry in scheduled.unscheduled_items:
        template = task_templates[entry.task_id]
        if entry.task_id in adjusted_tasks and adjusted_tasks[entry.task_id] > 0:
            continue
        template_payload = template_for_draft(entry.task_id)
        if entry.task_id in adjusted_tasks:
            reason = f"AI 建议在当前规划窗口内没有可用时段，未生成日程。{capacity_note(template)}"
        elif user_required_occurrences(template):
            reason = f"用户明确要求的 {entry.missing_occurrences} 次任务未能排入：{entry.reason} {capacity_note(template)}"
        else:
            reason = entry.reason
        items.append({"kind":"unscheduled","title":entry.title,"start_at":None,"end_at":None,"task_template_json":template_payload,"provenance_json":template_payload["provenance"],"conflict_state":"unscheduled","unscheduled_reason":reason})
    draft = DraftRepository(db).create_with_items(session_id=row.id, window_start=reference, window_end=window_end, items=items)
    repo.update(row, status=PlanningStatus.DRAFT_READY.value)
    return draft_response(draft, DraftRepository(db).get_items(draft.id), profile.timezone, db)


def draft_response(draft: Draft, items: list[DraftItem], timezone_name: str, db: Session) -> dict:
    tz = ZoneInfo(timezone_name)
    session = db.get(PlanningSession, draft.session_id)
    phase_b_json = session.phase_b_json if session and session.phase_b_json else {}
    assumptions = list(dict.fromkeys(phase_b_json.get("assumptions", [])))
    clarifications = [
        {"question": row.question, "answer": row.answer}
        for row in PlanningSessionRepository(db).list_answered(draft.session_id)
    ]

    def local(value: datetime | None) -> datetime | None:
        return value.astimezone(tz) if value is not None else None

    return {
        "id": draft.id,
        "session_id": draft.session_id,
        "status": draft.status,
        "window_start": local(draft.window_start),
        "window_end": local(draft.window_end),
        "window_days": round((draft.window_end - draft.window_start).total_seconds() / 86400),
        "assumptions": assumptions,
        "clarifications": clarifications,
        "items": [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "start_at": local(item.start_at),
                "end_at": local(item.end_at),
                "conflict_state": item.conflict_state,
                "unscheduled_reason": item.unscheduled_reason,
                "task_template": item.task_template_json,
                "provenance": item.provenance_json or [],
                "editable": draft.status == "ready",
            }
            for item in items
        ],
    }
