from copy import deepcopy
from datetime import date, datetime, timedelta
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.prompts.phase_a import SYSTEM_PROMPT as PHASE_A_SYSTEM_PROMPT
from app.prompts.phase_b import SYSTEM_PROMPT as PHASE_B_SYSTEM_PROMPT
from app.prompts.schemas import PhaseAResult, PhaseBResult, is_exercise_activity, validate_phase_transition
from app.planning.phase_a_normalization import normalize_before_event_deadlines


PERIOD_DEFAULT_STARTS = {
    "morning": ("09:00", "上午"),
    "afternoon": ("14:00", "下午"),
    "evening": ("19:00", "晚上"),
    "after_work": ("18:00", "下班后"),
    "上午": ("09:00", "上午"),
    "下午": ("14:00", "下午"),
    "晚上": ("19:00", "晚上"),
    "下班后": ("18:00", "下班后"),
}


class ModelOutputValidationError(ValueError):
    """A schema failure with the model response retained for local diagnosis."""

    def __init__(self, *, raw_output: dict[str, Any], validation_errors: list[dict[str, Any]]) -> None:
        super().__init__("模型输出未通过结构校验")
        self.raw_output = raw_output
        self.validation_errors = validation_errors


def validation_error_details(error: ValidationError) -> list[dict[str, Any]]:
    """Keep a JSON-safe, concise copy of Pydantic's field-level errors."""
    return [
        {
            "loc": item["loc"],
            "msg": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]


def normalize_assumption_lists(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("source") == "ai_assumption":
            value["display_label"] = "AI猜测，可修改"
        elif value.get("source") == "ai_suggestion":
            value["display_label"] = "AI建议，可修改或删除"
        for key, child in value.items():
            if key == "assumptions" and isinstance(child, list):
                value[key] = [
                    item.get("reason") or item.get("display_label") or item.get("field_path") or "AI 补充说明"
                    if isinstance(item, dict) else item
                    for item in child
                ]
            else:
                normalize_assumption_lists(child)
    elif isinstance(value, list):
        for child in value:
            normalize_assumption_lists(child)


_PROVENANCE_SOURCE_VALUES = ("user_input", "user_profile", "system_derived", "ai_assumption", "ai_suggestion")


def repair_provenance_source(value: Any) -> str | None:
    """Repair misspelled provenance sources (the model wrote 'ai_assuggestion')."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _PROVENANCE_SOURCE_VALUES:
        return key
    if key.startswith("ai"):
        if "sugg" in key:
            return "ai_suggestion"
        if "assum" in key:
            return "ai_assumption"
    if "system" in key:
        return "system_derived"
    if "profile" in key:
        return "user_profile"
    if "user" in key:
        return "user_input"
    return None


def normalize_provenance_lists(value: Any) -> None:
    """Repair provenance fields anywhere in the model output: the schema expects
    a list of objects, but the model sometimes emits strings, a dict, or null.
    Malformed entries can never pass validation, so dropping them is safe."""
    if isinstance(value, dict):
        provenance = value.get("provenance")
        if provenance is not None and not (
            isinstance(provenance, list) and all(isinstance(entry, dict) for entry in provenance)
        ):
            value["provenance"] = (
                [entry for entry in provenance if isinstance(entry, dict)] if isinstance(provenance, list) else []
            )
        for entry in value.get("provenance") or []:
            if isinstance(entry, dict):
                repaired = repair_provenance_source(entry.get("source"))
                if repaired:
                    entry["source"] = repaired
        for child in value.values():
            normalize_provenance_lists(child)
    elif isinstance(value, list):
        for child in value:
            normalize_provenance_lists(child)


def normalize_question_covers(raw: dict[str, Any]) -> None:
    """Question targets must be item_id strings; models sometimes index them (2)."""
    items = raw.get("items")
    if not isinstance(items, list):
        return
    item_ids = [item.get("item_id") for item in items if isinstance(item, dict) and item.get("item_id")]
    questions = raw.get("questions")
    if not isinstance(questions, list):
        return
    for question in questions:
        if not isinstance(question, dict):
            continue
        covers = question.get("covers_item_ids")
        if not isinstance(covers, list):
            continue
        repaired = []
        for value in covers:
            if isinstance(value, str) and value:
                repaired.append(value)
            elif isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= len(item_ids):
                repaired.append(str(item_ids[value - 1]))
        question["covers_item_ids"] = repaired


_TOP_LEVEL_FIELDS = {"decision", "items", "questions", "manual_required", "global_assumptions"}
_PHASE_B_TOP_LEVEL_FIELDS = {"decision", "fixed_events", "goal_plans", "assumptions"}
_ITEM_FIELDS = {"item_id", "kind", "source_text", "title", "facts", "hard_constraints", "soft_preferences",
                "provenance", "critical_missing", "assumptions"}
_FACT_FIELDS = {"date", "start_time", "end_time", "duration_minutes", "deadline", "stated_frequency",
                "activity", "result_metric"}
_HARD_CONSTRAINT_FIELDS = {"allowed_weekdays", "required_periods", "fixed_date", "fixed_start_time",
                           "must_finish_before", "required_occurrences_within_window",
                           "required_frequency_per_week", "minimum_gap_hours"}
_SOFT_PREFERENCE_FIELDS = {"preferred_periods", "pacing"}
_QUESTION_FIELDS = {"question_id", "priority", "missing_field", "question", "covers_item_ids",
                    "input_type", "options", "allow_custom_input"}
_PROVENANCE_FIELDS = {"field_path", "value", "source", "reason", "user_editable", "display_label"}
_GOAL_PLAN_FIELDS = {"source_item_id", "goal_title", "deadline", "deadline_provenance", "importance",
                     "urgency", "suggested_goal_horizon_days", "task_templates", "assumptions"}
_TASK_FIELDS = {"task_id", "title", "activity_type", "instructions", "duration_minutes",
                "occurrences_within_window", "frequency_per_week", "min_gap_hours", "depends_on",
                "hard_constraints", "soft_preferences", "source", "provenance", "assumptions"}
_FIXED_EVENT_FIELDS = {"source_item_id", "title", "date", "start_time", "end_time",
                       "duration_minutes", "assumptions"}


def _drop_unknown(container: dict[str, Any], allowed: set[str]) -> list[str]:
    unknown = [key for key in container if key not in allowed]
    for key in unknown:
        container.pop(key)
    return unknown


def _drop_unknown_constraints(container: Any, label: str, assumptions: Any) -> None:
    if not isinstance(container, dict):
        return
    dropped = _drop_unknown(container, _HARD_CONSTRAINT_FIELDS if label == "hard_constraints"
                            else _SOFT_PREFERENCE_FIELDS)
    if dropped and isinstance(assumptions, list):
        assumptions.append(f"模型输出了不支持的 {label} 字段 {dropped}，已忽略")


_CN_WEEKDAY_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


def _repair_allowed_weekdays(constraints: dict[str, Any], assumptions: list) -> None:
    """The schema requires a list of ISO day numbers, but the model sometimes
    emits a scalar, a string, or worse; repair what is parseable."""
    value = constraints.get("allowed_weekdays")
    if isinstance(value, list):
        constraints["allowed_weekdays"] = [day for day in value if isinstance(day, int) and 1 <= day <= 7]
        return
    repaired = None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 7:
        repaired = [value]
    elif isinstance(value, str):
        digits = [int(ch) for ch in value if ch in "1234567"]
        digits.extend(_CN_WEEKDAY_DIGITS[ch] for ch in value if ch in _CN_WEEKDAY_DIGITS)
        repaired = sorted(set(digits)) or None
    if repaired is not None:
        constraints["allowed_weekdays"] = repaired
        assumptions.append(f"模型把星期约束写成了 {value!r}，已修复为 {repaired}")
    else:
        constraints["allowed_weekdays"] = []
        assumptions.append(f"模型输出的星期约束 {value!r} 无法解析，已忽略")


def normalize_unknown_keys(raw: dict[str, Any]) -> None:
    """The gateway cannot enforce the schema, so models sometimes invent field
    names (e.g. required_occurrences_within_week). Unknown keys are fatal under
    extra="forbid", so strip them and keep a visible note for constraint-level
    drops instead of failing the whole draft."""
    _drop_unknown(raw, _TOP_LEVEL_FIELDS)
    items = raw.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        _drop_unknown(item, _ITEM_FIELDS)
        facts = item.get("facts")
        if isinstance(facts, dict):
            _drop_unknown(facts, _FACT_FIELDS)
        assumptions = item.get("assumptions")
        if not isinstance(assumptions, list):
            item["assumptions"] = assumptions = []
        hard_constraints = item.get("hard_constraints")
        if isinstance(hard_constraints, dict):
            _repair_allowed_weekdays(hard_constraints, assumptions)
        for label in ("hard_constraints", "soft_preferences"):
            _drop_unknown_constraints(item.get(label), label, assumptions)
        provenance = item.get("provenance")
        for entry in provenance if isinstance(provenance, list) else []:
            if isinstance(entry, dict):
                _drop_unknown(entry, _PROVENANCE_FIELDS)
    questions = raw.get("questions")
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            continue
        _drop_unknown(question, _QUESTION_FIELDS)
        options = question.get("options")
        for option in options if isinstance(options, list) else []:
            if isinstance(option, dict):
                _drop_unknown(option, {"label", "value"})


def normalize_phase_b_unknown_keys(raw: dict[str, Any]) -> None:
    """Same field-name tolerance for phase B's goal_plans / fixed_events shape."""
    _drop_unknown(raw, _PHASE_B_TOP_LEVEL_FIELDS)
    plans = raw.get("goal_plans")
    for plan in plans if isinstance(plans, list) else []:
        if not isinstance(plan, dict):
            continue
        if "source_item_id" not in plan and "goal_id" in plan:
            plan["source_item_id"] = plan.pop("goal_id")
        if "goal_title" not in plan and "title" in plan:
            plan["goal_title"] = plan.pop("title")
        _drop_unknown(plan, _GOAL_PLAN_FIELDS)
        deadline_provenance = plan.get("deadline_provenance")
        if isinstance(deadline_provenance, dict):
            _drop_unknown(deadline_provenance, _PROVENANCE_FIELDS)
        tasks = plan.get("task_templates")
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            _drop_unknown(task, _TASK_FIELDS)
            task_assumptions = task.get("assumptions")
            if not isinstance(task_assumptions, list):
                task["assumptions"] = task_assumptions = []
            task_hard_constraints = task.get("hard_constraints")
            if isinstance(task_hard_constraints, dict):
                _repair_allowed_weekdays(task_hard_constraints, task_assumptions)
            for label in ("hard_constraints", "soft_preferences"):
                _drop_unknown_constraints(task.get(label), label, task_assumptions)
            provenance = task.get("provenance")
            for entry in provenance if isinstance(provenance, list) else []:
                if isinstance(entry, dict):
                    _drop_unknown(entry, _PROVENANCE_FIELDS)
    events = raw.get("fixed_events")
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict):
            _drop_unknown(event, _FIXED_EVENT_FIELDS)


def normalize_task_duration_cap(raw: dict[str, Any]) -> None:
    """The schema caps a single task at 90 minutes but the gateway cannot enforce
    it, so clamp oversized durations here instead of failing the whole draft."""
    plans = raw.get("goal_plans", [])
    for plan in plans if isinstance(plans, list) else []:
        if not isinstance(plan, dict):
            continue
        tasks = plan.get("task_templates", [])
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            duration = task.get("duration_minutes")
            if isinstance(duration, int) and not isinstance(duration, bool) and 0 < duration <= 90:
                continue
            try:
                parsed = int(duration)
            except (TypeError, ValueError):
                continue
            if parsed <= 0:
                continue
            clamped = min(parsed, 90)
            task["duration_minutes"] = clamped
            provenance = task.get("provenance")
            if not isinstance(provenance, list):
                task["provenance"] = provenance = []
            provenance.append({
                "field_path": "task_template.duration_minutes",
                "value": clamped,
                "source": "system_derived",
                "reason": f"模型建议 {parsed} 分钟，超过单任务 90 分钟上限，已调整为 {clamped} 分钟。",
                "user_editable": True,
                "display_label": "系统推导",
            })


def normalize_period_start_times(raw: dict[str, Any]) -> None:
    """Normalize model-written time periods.

    Abstract goals get a visible default clock time (AI assumption). Explicit
    events keep the clarification signal: the period moves into
    required_periods, start_time is cleared, so the forced follow-up asks the
    user for the exact clock time instead of silently guessing one.
    """
    items = raw.get("items", [])
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        facts = item.get("facts")
        if not isinstance(facts, dict):
            continue
        constraints = item.setdefault("hard_constraints", {})
        if not isinstance(constraints, dict):
            item["hard_constraints"] = constraints = {}
        _normalize_period_aliases(constraints, item.get("soft_preferences"))
        period = facts.get("start_time")
        mapped = PERIOD_DEFAULT_STARTS.get(period)
        if mapped is None:
            continue
        start_time, label = mapped
        canonical = _canonical_period(mapped)
        if item.get("kind") == "explicit_event":
            facts["start_time"] = None
            if constraints.get("fixed_start_time") in PERIOD_DEFAULT_STARTS:
                constraints["fixed_start_time"] = None
            if canonical and canonical not in constraints.get("required_periods", []):
                constraints["required_periods"].append(canonical)
            missing = item.setdefault("critical_missing", [])
            if "facts.start_time" not in missing:
                missing.append("facts.start_time")
            item.setdefault("provenance", []).append({
                "field_path": "hard_constraints.required_periods",
                "value": canonical,
                "source": "user_input",
                "reason": f"用户明确提到{label}开始，具体时间待确认",
                "user_editable": True,
                "display_label": "用户输入",
            })
            continue
        facts["start_time"] = start_time
        if constraints.get("fixed_start_time") in PERIOD_DEFAULT_STARTS:
            constraints["fixed_start_time"] = start_time
        if canonical and canonical not in constraints.setdefault("required_periods", []):
            constraints["required_periods"].append(canonical)
        provenance = item.setdefault("provenance", [])
        for field_path, value in (("facts.start_time", start_time), ("hard_constraints.fixed_start_time", start_time)):
            entry = next((candidate for candidate in provenance if candidate.get("field_path") == field_path), None)
            if entry is None:
                provenance.append({
                    "field_path": field_path,
                    "value": value,
                    "source": "ai_assumption",
                    "reason": f"用户选择{label}，具体开始时间默认猜测为{start_time}",
                    "user_editable": True,
                    "display_label": "AI猜测，可修改",
                })
            else:
                entry.update({
                    "value": value,
                    "source": "ai_assumption",
                    "reason": f"用户选择{label}，具体开始时间默认猜测为{start_time}",
                    "user_editable": True,
                    "display_label": "AI猜测，可修改",
                })


def normalize_shared_weekend_constraints(raw: dict[str, Any], user_input: str | None) -> None:
    """Apply one shared “weekend ... and ...” clause to every goal in that clause."""
    if not user_input:
        return
    match = re.search(r"周末[^，。；]*(?:和|以及|及|、)[^，。；]+", user_input)
    if match is None or any(token in match.group(0) for token in ("工作日", "平时", "周内")):
        return
    items = raw.get("items")
    if not isinstance(items, list):
        return
    goals = [item for item in items if isinstance(item, dict) and item.get("kind") == "abstract_goal"]
    if len(goals) < 2:
        return
    changed = False
    for item in goals:
        constraints = item.get("hard_constraints")
        if not isinstance(constraints, dict) or constraints.get("allowed_weekdays"):
            continue
        constraints["allowed_weekdays"] = [6, 7]
        provenance = item.setdefault("provenance", [])
        if isinstance(provenance, list):
            provenance.append({
                "field_path": "hard_constraints.allowed_weekdays",
                "value": [6, 7],
                "source": "user_input",
                "reason": "原文中的周末位于连接多个目标的共享短语之前，因此同时约束这些目标",
                "user_editable": True,
                "display_label": "用户输入",
            })
        changed = True
    if changed:
        assumptions = raw.setdefault("global_assumptions", [])
        note = "“周末”按原句结构同时约束并列目标；可在草案中修改"
        if isinstance(assumptions, list) and note not in assumptions:
            assumptions.append(note)


_PRE_ACTION_KEYWORDS = ("请假", "休假", "调休")
_WEEKDAY_TOKENS = {
    "星期一": 1, "星期二": 2, "星期三": 3, "星期四": 4, "星期五": 5, "星期六": 6, "星期日": 7, "星期天": 7,
    "周一": 1, "周二": 2, "周三": 3, "周四": 4, "周五": 5, "周六": 6, "周日": 7, "周天": 7,
    "礼拜一": 1, "礼拜二": 2, "礼拜三": 3, "礼拜四": 4, "礼拜五": 5, "礼拜六": 6, "礼拜天": 7, "礼拜日": 7,
}
_RELATIVE_WEEKDAY_SKIP = ("下周", "这周", "本周", "上周", "每个", "每周")


def normalize_relative_weekdays(
    raw: dict[str, Any], reference_now: str | None, user_input: str | None
) -> None:
    """A bare weekday mention ("周三") must mean the nearest upcoming occurrence.

    Models regularly drift a full week when the mentioned weekday is close, so
    snap any explicit event that landed a week or more away back to the nearest
    upcoming date carrying that weekday.
    """
    if not reference_now or not user_input:
        return
    if any(token in user_input for token in _RELATIVE_WEEKDAY_SKIP):
        return
    found = {weekday for token, weekday in _WEEKDAY_TOKENS.items() if token in user_input}
    if len(found) != 1:
        return
    target_weekday = found.pop()
    try:
        today = date.fromisoformat(str(reference_now)[:10])
    except ValueError:
        return
    nearest = today + timedelta(days=(target_weekday - today.isoweekday()) % 7)
    items = raw.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "explicit_event":
            continue
        facts = item.get("facts")
        if not isinstance(facts, dict) or not facts.get("date"):
            continue
        try:
            current = date.fromisoformat(str(facts["date"]))
        except ValueError:
            continue
        if current.isoweekday() != target_weekday or (current - today).days < 7:
            continue
        facts["date"] = nearest.isoformat()
        constraints = item.get("hard_constraints")
        if isinstance(constraints, dict) and constraints.get("fixed_date"):
            constraints["fixed_date"] = facts["date"]
        provenance = item.get("provenance")
        if not isinstance(provenance, list):
            item["provenance"] = provenance = []
        provenance.append({
            "field_path": "facts.date",
            "value": facts["date"],
            "source": "ai_assumption",
            "reason": f"用户说的是最近一次到来的周{'一二三四五六日'[target_weekday - 1]}，按 {facts['date']} 解析",
            "user_editable": True,
            "display_label": "AI猜测，可修改",
        })
        assumptions = item.get("assumptions")
        if isinstance(assumptions, list):
            assumptions.append(f"日期按最近一次到来的周{'一二三四五六日'[target_weekday - 1]}解析（{facts['date']}，可修改）")


def normalize_pre_action_events(
    raw: dict[str, Any], reference_now: str | None = None, timezone_name: str = "Asia/Shanghai"
) -> None:
    """Pre-actions such as taking leave must happen before the main activities.

    Models often emit the leave item with an empty date, which silently drops it
    from the draft. When sibling events already have dates, default the pre-action
    to the day before the earliest main activity (never before today) and mark it
    as a visible, editable AI assumption.
    """
    items = raw.get("items")
    if not isinstance(items, list):
        return
    def is_pre_action(item: dict[str, Any]) -> bool:
        text = f"{item.get('title', '')}{item.get('source_text', '')}"
        return any(keyword in text for keyword in _PRE_ACTION_KEYWORDS)

    dated = [
        str(item["facts"]["date"]) for item in items
        if isinstance(item, dict)
        and item.get("kind") == "explicit_event"
        and not is_pre_action(item)
        and isinstance(item.get("facts"), dict)
        and item["facts"].get("date")
    ]
    if not dated:
        return
    try:
        main_day = min(date.fromisoformat(value) for value in dated)
    except ValueError:
        return
    today: date | None = None
    now_local: datetime | None = None
    if reference_now:
        try:
            reference = datetime.fromisoformat(str(reference_now))
        except ValueError:
            reference = None
        if reference is not None:
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=ZoneInfo(timezone_name))
            now_local = reference.astimezone(ZoneInfo(timezone_name))
            today = now_local.date()
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "explicit_event":
            continue
        text = f"{item.get('title', '')}{item.get('source_text', '')}"
        if not is_pre_action(item):
            continue
        facts = item.get("facts")
        if not isinstance(facts, dict):
            continue
        current_raw = facts.get("date")
        current_day: date | None = None
        if current_raw:
            try:
                current_day = date.fromisoformat(str(current_raw))
            except ValueError:
                current_day = None
        if current_day is not None and current_day < main_day and not (today and current_day < today):
            continue

        target = main_day - timedelta(days=1)
        full_day = "一天" in text or "全天" in text
        start_time = "09:00"
        current_duration = facts.get("duration_minutes")
        duration = current_duration if isinstance(current_duration, int) and current_duration > 0 else (480 if full_day else 60)
        if today and target < today:
            target = today
        if today and target == today:
            # 前一天已过或就是今天：改排今天，并从下一个整点开始，避免落在已过去的时间
            if now_local is not None:
                next_hour = (now_local + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                target = next_hour.date()
                start_time = next_hour.strftime("%H:%M")
                if target >= main_day:
                    target = today
                    start_time = "23:00"
                duration = min(duration, 60)
        facts["date"] = target.isoformat()
        facts["start_time"] = start_time
        facts["duration_minutes"] = duration
        constraints = item.get("hard_constraints")
        if isinstance(constraints, dict):
            constraints["fixed_date"] = facts["date"]
            constraints["fixed_start_time"] = start_time
            constraints["allowed_weekdays"] = [target.isoweekday()]
        provenance = item.get("provenance")
        if not isinstance(provenance, list):
            item["provenance"] = provenance = []
        same_day = target >= main_day
        provenance_by_path = {
            entry.get("field_path"): entry
            for entry in provenance
            if isinstance(entry, dict) and entry.get("field_path")
        }
        updates = (
            ("facts.date", facts["date"], "请假需在主活动前一天完成" if not same_day else "主活动前一天已过，请假改排在主活动当天"),
            ("facts.start_time", start_time, "按当前时间之后的第一个整点占位" if target == today else "前置事务按上午九点占位"),
            ("facts.duration_minutes", duration, "请假一天按全天占位" if full_day and duration == 480 else "请假手续按一小时占位"),
            ("hard_constraints.fixed_date", facts["date"], "与请假日期保持一致"),
            ("hard_constraints.fixed_start_time", start_time, "与请假开始时间保持一致"),
            ("hard_constraints.allowed_weekdays", [target.isoweekday()], "与请假日期的星期保持一致"),
        )
        for field_path, value, reason in updates:
            entry = provenance_by_path.get(field_path)
            replacement = {
                "field_path": field_path, "value": value, "source": "ai_assumption", "reason": reason,
                "user_editable": True, "display_label": "AI猜测，可修改",
            }
            if entry is None:
                provenance.append(replacement)
            else:
                entry.update(replacement)
        assumptions = item.get("assumptions")
        if isinstance(assumptions, list):
            assumptions[:] = [note for note in assumptions if "请假安排" not in note and "请假已改排" not in note]
            note = (
                f"请假安排在主活动前一天（{facts['date']}，AI 假设，可修改）" if not same_day
                else f"主活动前一天已过，请假已改排到主活动当天（{facts['date']}，AI 假设，可修改）"
            )
            assumptions.append(note)


def _canonical_period(mapped: tuple[str, str]) -> str | None:
    return next(
        (key for key, value in PERIOD_DEFAULT_STARTS.items() if value == mapped and key.isascii()),
        None,
    )


_PERIOD_ALIASES = {"上午": "morning", "下午": "afternoon", "傍晚": "evening", "晚上": "evening", "下班后": "after_work"}


def strip_forbidden_display_labels(raw: dict[str, Any]) -> None:
    """The model sometimes copies provenance display labels onto containers that
    forbid extra fields (task templates, plans, fixed events). Real display
    labels live inside provenance entries, so dropping the stray copies is safe."""
    plans = raw.get("goal_plans", [])
    for plan in plans if isinstance(plans, list) else []:
        if not isinstance(plan, dict):
            continue
        plan.pop("display_label", None)
        tasks = plan.get("task_templates", [])
        for task in tasks if isinstance(tasks, list) else []:
            if isinstance(task, dict):
                task.pop("display_label", None)
    events = raw.get("fixed_events", [])
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict):
            event.pop("display_label", None)


def _normalize_period_aliases(constraints: dict[str, Any], soft_preferences: Any) -> None:
    """Map Chinese period names onto the schema's ascii period enums."""
    containers = [constraints]
    if isinstance(soft_preferences, dict):
        containers.append(soft_preferences)
    for container, key in ((containers[0], "required_periods"), (containers[-1], "preferred_periods")):
        periods = container.get(key)
        if isinstance(periods, list):
            container[key] = [_PERIOD_ALIASES.get(p, p) for p in periods if isinstance(p, str)]


def normalize_fact_deadlines(raw: dict[str, Any]) -> None:
    """facts.deadline is a calendar date; exact deadlines belong in must_finish_before."""
    items = raw.get("items", [])
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        facts = item.get("facts")
        if not isinstance(facts, dict):
            continue
        deadline = facts.get("deadline")
        if isinstance(deadline, str) and "T" in deadline:
            facts["deadline"] = deadline.split("T", 1)[0]
            provenance = item.get("provenance")
            for entry in provenance if isinstance(provenance, list) else []:
                if isinstance(entry, dict) and entry.get("field_path") == "facts.deadline":
                    entry["value"] = facts["deadline"]


def normalize_deadline_provenance(raw: dict[str, Any]) -> None:
    """Accept the one-item array typo without accepting ambiguous provenance."""
    plans = raw.get("goal_plans", [])
    if not isinstance(plans, list):
        return
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        value = plan.get("deadline_provenance")
        if isinstance(value, list) and len(value) <= 1:
            plan["deadline_provenance"] = value[0] if value else None


def normalize_goal_plan_deadlines(raw: dict[str, Any]) -> None:
    plans = raw.get("goal_plans", [])
    if not isinstance(plans, list):
        return
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        deadline = plan.get("deadline")
        if isinstance(deadline, str) and "T" in deadline:
            plan["deadline"] = deadline.split("T", 1)[0]
            provenance = plan.get("deadline_provenance")
            if isinstance(provenance, dict):
                provenance["value"] = plan["deadline"]


def normalize_ai_invented_non_exercise_gaps(raw: dict[str, Any]) -> None:
    """AI pacing may influence ordering, but it must not become a hard gap for non-exercise tasks."""
    plans = raw.get("goal_plans", [])
    if not isinstance(plans, list):
        return
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        tasks = plan.get("task_templates", [])
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if is_exercise_activity(str(task.get("activity_type", ""))):
                continue
            provenance = task.get("provenance", [])
            gap_entry = next((entry for entry in provenance if entry.get("field_path") == "task_template.min_gap_hours"), None)
            if gap_entry and gap_entry.get("source") == "user_input":
                continue
            if task.get("min_gap_hours", 0) == 0:
                continue
            task["min_gap_hours"] = 0
            replacement = {
                "field_path": "task_template.min_gap_hours",
                "value": 0,
                "source": "system_derived",
                "reason": "非运动任务未包含用户明确间隔，不设置硬间隔",
                "user_editable": True,
                "display_label": "系统推导",
            }
            if gap_entry is None:
                provenance.append(replacement)
            else:
                gap_entry.update(replacement)


_COMPOUND_ACTIVITY_GROUPS = (
    ("请假", ("请假", "休假", "调休")),
    ("办事流程", ("处理流程", "办理流程", "办事流程")),
    ("注册登记", ("开学注册", "现场登记")),
    ("宣讲活动", ("宣讲会", "交流会")),
)


def compound_activity_coverage_errors(raw: dict[str, Any], user_input: str | None) -> list[str]:
    """Detect high-signal compound trips that the model collapsed into fewer items."""
    if not user_input:
        return []
    required = [
        (label, keywords)
        for label, keywords in _COMPOUND_ACTIVITY_GROUPS
        if any(keyword in user_input for keyword in keywords)
    ]
    if len(required) < 3:
        return []
    items = [item for item in raw.get("items", []) if isinstance(item, dict) and item.get("kind") == "explicit_event"]
    matched_ids: list[str] = []
    missing: list[str] = []
    for label, keywords in required:
        matches = []
        for item in items:
            text = f"{item.get('title', '')}{item.get('source_text', '')}{(item.get('facts') or {}).get('activity', '')}"
            if any(keyword in text for keyword in keywords):
                matches.append(str(item.get("item_id", "")))
        if not matches:
            missing.append(label)
        else:
            matched_ids.append(matches[0])
    errors = []
    if missing:
        errors.append(f"复合行程缺少独立事项：{'、'.join(missing)}")
    if len(set(matched_ids)) < len(matched_ids):
        errors.append("复合行程的请假、办事、注册和宣讲活动必须分别使用独立 item")
    return errors


class JSONCompletionClient(Protocol):
    async def complete_json(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class PlanningLLMService:
    def __init__(self, client: JSONCompletionClient) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        return getattr(self._client, "model_name", type(self._client).__name__)

    async def run_phase_a(self, context: dict[str, Any]) -> PhaseAResult:
        raw = await self._client.complete_json(system_prompt=PHASE_A_SYSTEM_PROMPT, payload=context)
        raw = deepcopy(raw)
        try:
            normalize_provenance_lists(raw)
            normalize_unknown_keys(raw)
            normalize_question_covers(raw)
            normalize_assumption_lists(raw)
            normalize_shared_weekend_constraints(raw, context.get("user_input"))
            normalize_period_start_times(raw)
            normalize_fact_deadlines(raw)
            normalize_before_event_deadlines(raw, context.get("timezone", "Asia/Shanghai"))
            normalize_relative_weekdays(raw, context.get("reference_now"), context.get("user_input"))
            normalize_pre_action_events(
                raw, context.get("reference_now"), context.get("timezone", "Asia/Shanghai")
            )
            if raw.get("manual_required") is False:
                raw["manual_required"] = None
            if raw.get("decision") == "ready":
                raw_items = raw.get("items", [])
                missing_start_items = [
                    item for item in raw.get("items", [])
                    if isinstance(raw_items, list)
                    and isinstance(item, dict)
                    and item.get("kind") == "explicit_event"
                    and isinstance(item.get("facts"), dict)
                    and item["facts"].get("start_time") is None
                ]
                if missing_start_items:
                    raw["decision"] = "needs_clarification"
                    questions = list(raw.get("questions", []))
                    covered_missing_fields = {
                        (question.get("missing_field"), item_id)
                        for question in questions
                        for item_id in question.get("covers_item_ids", [])
                    }
                    for index, item in enumerate(missing_start_items[:3]):
                        missing = item.setdefault("critical_missing", [])
                        if "facts.start_time" not in missing:
                            missing.append("facts.start_time")
                        if ("facts.start_time", item["item_id"]) in covered_missing_fields:
                            continue
                        questions.append({
                            "question_id": f"q_start_time_{index + 1}",
                            "priority": 30,
                            "missing_field": "facts.start_time",
                            "question": f"“{item.get('title', '这项安排')}”几点开始？",
                            "covers_item_ids": [item["item_id"]],
                            "input_type": "single_choice",
                            "options": [],
                            "allow_custom_input": True,
                        })
                    raw["questions"] = sorted(questions, key=lambda item: item["priority"])[:3]
        except Exception as exc:
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=[{
                    "loc": ["normalization"],
                    "msg": f"{type(exc).__name__}: {exc}",
                    "type": "internal.normalization_error",
                }],
            ) from exc
        semantic_errors = compound_activity_coverage_errors(raw, context.get("user_input"))
        if semantic_errors:
            if not context.get("semantic_retry_attempted"):
                return await self.run_phase_a({
                    **context,
                    "semantic_retry_attempted": True,
                    "previous_invalid_phase_a_result": raw,
                    "semantic_validation_errors": semantic_errors,
                })
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=[{
                    "loc": ["items"],
                    "msg": "; ".join(semantic_errors),
                    "type": "value_error.semantic_coverage",
                }],
            )
        try:
            return PhaseAResult.model_validate(raw)
        except ValidationError as error:
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=validation_error_details(error),
            ) from error

    async def run_phase_b(self, phase_a: PhaseAResult, context: dict[str, Any]) -> PhaseBResult:
        payload = {**context, "phase_a_result": phase_a.model_dump(mode="json")}
        raw = await self._client.complete_json(system_prompt=PHASE_B_SYSTEM_PROMPT, payload=payload)
        raw = deepcopy(raw)
        try:
            normalize_provenance_lists(raw)
            normalize_phase_b_unknown_keys(raw)
            normalize_assumption_lists(raw)
            normalize_deadline_provenance(raw)
            normalize_goal_plan_deadlines(raw)
            normalize_ai_invented_non_exercise_gaps(raw)
            strip_forbidden_display_labels(raw)
            normalize_task_duration_cap(raw)
            phase_a_items = {item.item_id: item for item in phase_a.items}
            raw_plans = raw.get("goal_plans", [])
            for plan in raw_plans if isinstance(raw_plans, list) else []:
                if not isinstance(plan, dict):
                    continue
                if "source_item_id" not in plan and "goal_id" in plan:
                    plan["source_item_id"] = plan.pop("goal_id")
                if "goal_title" not in plan and "title" in plan:
                    plan["goal_title"] = plan.pop("title")
                source_item = phase_a_items.get(plan.get("source_item_id"))
                tasks = plan.get("task_templates")
                for task in tasks if isinstance(tasks, list) else []:
                    if not isinstance(task, dict):
                        continue
                    if isinstance(task.get("source"), dict):
                        task["source"] = "user_input" if source_item and source_item.facts.activity else "ai_suggestion"
        except Exception as exc:
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=[{
                    "loc": ["normalization"],
                    "msg": f"{type(exc).__name__}: {exc}",
                    "type": "internal.normalization_error",
                }],
            ) from exc
        try:
            phase_b = PhaseBResult.model_validate(raw)
        except ValidationError as error:
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=validation_error_details(error),
            ) from error
        try:
            validate_phase_transition(phase_a, phase_b)
        except ValueError as error:
            if not context.get("transition_retry_attempted"):
                return await self.run_phase_b(phase_a, {
                    **context,
                    "transition_retry_attempted": True,
                    "previous_invalid_phase_b_result": raw,
                    "transition_validation_error": str(error),
                })
            raise ModelOutputValidationError(
                raw_output=raw,
                validation_errors=[{
                    "loc": ["phase_transition"],
                    "msg": str(error),
                    "type": "value_error.phase_transition",
                }],
            ) from error
        return phase_b
