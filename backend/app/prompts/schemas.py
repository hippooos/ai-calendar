from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import ItemKind, PhaseADecision, PhaseBDecision, Priority, ProvenanceSource

Period = Literal["morning", "afternoon", "evening", "after_work", "any"]
Pacing = Literal["neutral", "distributed", "compact", "fragmented"]
EXERCISE_ACTIVITIES = {
    "exercise", "walking", "brisk_walking", "running", "stretching",
    "jump_rope", "bodyweight", "运动", "锻炼", "快走", "散步", "拉伸", "跳绳",
}


def is_exercise_activity(activity_type: str) -> bool:
    return activity_type.strip().lower() in EXERCISE_ACTIVITIES


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    field_path: str
    value: Any
    source: ProvenanceSource
    reason: str
    user_editable: bool
    display_label: str

    @model_validator(mode="after")
    def require_visible_ai_label(self) -> "Provenance":
        required = {
            ProvenanceSource.AI_ASSUMPTION: "AI猜测，可修改",
            ProvenanceSource.AI_SUGGESTION: "AI建议，可修改或删除",
        }.get(self.source)
        if required and self.display_label != required:
            raise ValueError(f"{self.source.value} 的 display_label 必须为“{required}”")
        return self


class Facts(StrictModel):
    date: date | None
    start_time: time | None
    end_time: time | None
    duration_minutes: int | None = Field(default=None, gt=0)
    deadline: date | None
    stated_frequency: str | None
    activity: str | None
    result_metric: str | None


class HardConstraints(StrictModel):
    allowed_weekdays: list[int] = Field(default_factory=list)
    required_periods: list[Period] = Field(default_factory=list)
    fixed_date: date | None = None
    fixed_start_time: time | None = None
    must_finish_before: datetime | None = None
    required_occurrences_within_window: int | None = Field(default=None, ge=1, le=30)
    required_frequency_per_week: int | None = Field(default=None, ge=1, le=7)
    minimum_gap_hours: int | None = Field(default=None, ge=0)

    @field_validator("allowed_weekdays")
    @classmethod
    def validate_iso_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 1 or day > 7 for day in value):
            raise ValueError("allowed_weekdays 必须使用 1 到 7 的 ISO 星期")
        if len(value) != len(set(value)):
            raise ValueError("allowed_weekdays 不得重复")
        return value


class SoftPreferences(StrictModel):
    preferred_periods: list[Period] = Field(default_factory=list)
    pacing: Pacing = "neutral"


class PhaseAItem(StrictModel):
    item_id: str
    kind: ItemKind
    source_text: str
    title: str
    facts: Facts
    hard_constraints: HardConstraints
    soft_preferences: SoftPreferences
    provenance: list[Provenance]
    critical_missing: list[str]
    assumptions: list[str]


class ClarificationQuestion(StrictModel):
    question_id: str
    priority: Literal[10, 20, 30, 40, 50]
    missing_field: str
    question: str
    covers_item_ids: list[str]
    input_type: Literal["single_choice", "free_text"] = "free_text"
    options: list["QuestionOption"] = Field(default_factory=list)
    allow_custom_input: bool = True


class QuestionOption(StrictModel):
    label: str
    value: str


class ManualRequired(StrictModel):
    reason_code: str
    message: str
    affected_item_ids: list[str]


class PhaseAResult(StrictModel):
    decision: PhaseADecision
    items: list[PhaseAItem]
    questions: list[ClarificationQuestion]
    manual_required: ManualRequired | None
    global_assumptions: list[str]

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, value: list[ClarificationQuestion]) -> list[ClarificationQuestion]:
        if len(value) > 3:
            raise ValueError("questions 最多只能有 3 项")
        priorities = [question.priority for question in value]
        if priorities != sorted(priorities):
            raise ValueError("questions 必须按 priority 升序排列")
        return value


class FixedEvent(StrictModel):
    source_item_id: str
    title: str
    date: date
    start_time: time
    end_time: time | None
    duration_minutes: int = Field(gt=0)
    assumptions: list[str]


class TaskTemplate(StrictModel):
    task_id: str
    title: str
    activity_type: str
    instructions: str
    duration_minutes: int = Field(gt=0, le=90)
    occurrences_within_window: int = Field(ge=1, le=30)
    frequency_per_week: int = Field(ge=1, le=7)
    min_gap_hours: int = Field(ge=0)
    depends_on: list[str]
    hard_constraints: HardConstraints
    soft_preferences: SoftPreferences
    source: ProvenanceSource
    provenance: list[Provenance]
    assumptions: list[str]

    @model_validator(mode="after")
    def require_exercise_gap(self) -> "TaskTemplate":
        if (
            is_exercise_activity(self.activity_type)
            and self.frequency_per_week >= 3
            and self.min_gap_hours < 36
        ):
            raise ValueError("每周 3 次及以上任务的 min_gap_hours 必须至少为 36")
        return self


class GoalPlan(StrictModel):
    source_item_id: str
    goal_title: str
    deadline: date | None
    deadline_provenance: Provenance | None
    importance: Priority
    urgency: Priority
    suggested_goal_horizon_days: int = Field(gt=0)
    task_templates: list[TaskTemplate]
    assumptions: list[str]


class PhaseBResult(StrictModel):
    decision: PhaseBDecision
    fixed_events: list[FixedEvent]
    goal_plans: list[GoalPlan]
    assumptions: list[str]


def validate_phase_transition(phase_a: PhaseAResult, phase_b: PhaseBResult) -> None:
    items = {item.item_id: item for item in phase_a.items}
    if phase_b.decision == PhaseBDecision.READY_FOR_SCHEDULING:
        expected_fixed_ids = [item.item_id for item in phase_a.items if item.kind == ItemKind.EXPLICIT_EVENT]
        actual_fixed_ids = [event.source_item_id for event in phase_b.fixed_events]
        if Counter(actual_fixed_ids) != Counter(expected_fixed_ids):
            raise ValueError("阶段 B 的固定事件必须与阶段 A 一一对应，不得遗漏或重复")

        expected_goal_ids = [item.item_id for item in phase_a.items if item.kind == ItemKind.ABSTRACT_GOAL]
        actual_goal_ids = [plan.source_item_id for plan in phase_b.goal_plans]
        if Counter(actual_goal_ids) != Counter(expected_goal_ids):
            raise ValueError("阶段 B 的目标计划必须与阶段 A 一一对应，不得遗漏或重复")

    for fixed_event in phase_b.fixed_events:
        source = items.get(fixed_event.source_item_id)
        if source is None or source.kind != ItemKind.EXPLICIT_EVENT:
            raise ValueError("固定事件必须引用阶段 A 的 explicit_event")
        expected = (source.title, source.facts.date, source.facts.start_time, source.facts.duration_minutes)
        actual = (fixed_event.title, fixed_event.date, fixed_event.start_time, fixed_event.duration_minutes)
        if actual != expected:
            raise ValueError("固定事件的标题或时间事实被阶段 B 修改")
        expected_end = source.facts.end_time
        if expected_end is None and source.facts.start_time is not None:
            expected_end = (
                datetime.combine(date.min, source.facts.start_time)
                + timedelta(minutes=source.facts.duration_minutes)
            ).time()
        if fixed_event.end_time not in {source.facts.end_time, expected_end}:
            raise ValueError("固定事件的标题或时间事实被阶段 B 修改")

    plans_by_source = {plan.source_item_id: plan for plan in phase_b.goal_plans}
    for source in phase_a.items:
        if source.kind != ItemKind.ABSTRACT_GOAL:
            continue
        plan = plans_by_source.get(source.item_id)
        if phase_b.decision == PhaseBDecision.READY_FOR_SCHEDULING and plan is None:
            raise ValueError("阶段 B 缺少抽象目标对应的 goal_plan")
        if plan is None:
            continue
        required_weekdays = source.hard_constraints.allowed_weekdays
        for task in plan.task_templates:
            if required_weekdays and task.hard_constraints.allowed_weekdays != required_weekdays:
                raise ValueError("阶段 B 丢失或修改了用户的硬星期约束")
            if source.hard_constraints.required_periods and task.hard_constraints.required_periods != source.hard_constraints.required_periods:
                raise ValueError("阶段 B 丢失或修改了用户的硬时段约束")
            if source.hard_constraints.must_finish_before and task.hard_constraints.must_finish_before != source.hard_constraints.must_finish_before:
                raise ValueError("阶段 B 丢失或修改了用户的硬截止时间")
            if source.hard_constraints.minimum_gap_hours is not None and task.min_gap_hours < source.hard_constraints.minimum_gap_hours:
                raise ValueError("阶段 B 低于用户指定的最小间隔")
        if source.hard_constraints.required_occurrences_within_window is not None:
            if sum(task.occurrences_within_window for task in plan.task_templates) != source.hard_constraints.required_occurrences_within_window:
                raise ValueError("阶段 B 修改了用户指定的任务次数")
        if source.hard_constraints.required_frequency_per_week is not None:
            if sum(task.frequency_per_week for task in plan.task_templates) != source.hard_constraints.required_frequency_per_week:
                raise ValueError("阶段 B 修改了用户指定的每周频率")
