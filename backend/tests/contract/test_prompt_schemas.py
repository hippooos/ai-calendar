import pytest
from pydantic import ValidationError

from app.prompts.schemas import PhaseAResult, PhaseBResult, validate_phase_transition


def phase_a_payload() -> dict:
    return {
        "decision": "ready",
        "items": [
            {
                "item_id": "item_1",
                "kind": "explicit_event",
                "source_text": "9月2日15点到16点开会",
                "title": "开会",
                "facts": {
                    "date": "2026-09-02",
                    "start_time": "15:00",
                    "end_time": "16:00",
                    "duration_minutes": 60,
                    "deadline": None,
                    "stated_frequency": None,
                    "activity": "开会",
                    "result_metric": None,
                },
                "hard_constraints": {
                    "allowed_weekdays": [3],
                    "required_periods": [],
                    "fixed_date": "2026-09-02",
                    "fixed_start_time": "15:00",
                },
                "soft_preferences": {"preferred_periods": []},
                "provenance": [],
                "critical_missing": [],
                "assumptions": [],
            }
        ],
        "questions": [],
        "manual_required": None,
        "global_assumptions": [],
    }


def phase_b_payload() -> dict:
    return {
        "decision": "ready_for_scheduling",
        "fixed_events": [
            {
                "source_item_id": "item_1",
                "title": "开会",
                "date": "2026-09-02",
                "start_time": "15:00",
                "end_time": "16:00",
                "duration_minutes": 60,
                "assumptions": [],
            }
        ],
        "goal_plans": [],
        "assumptions": [],
    }


def test_phase_a_rejects_unknown_top_level_fields() -> None:
    payload = phase_a_payload() | {"unexpected": True}

    with pytest.raises(ValidationError, match="unexpected"):
        PhaseAResult.model_validate(payload)


def test_ai_assumption_requires_visible_editable_label() -> None:
    payload = phase_a_payload()
    payload["items"][0]["provenance"] = [
        {
            "field_path": "facts.duration_minutes",
            "value": 60,
            "source": "ai_assumption",
            "reason": "用户未提供时长",
            "user_editable": True,
            "display_label": "默认值",
        }
    ]

    with pytest.raises(ValidationError, match="AI猜测，可修改"):
        PhaseAResult.model_validate(payload)


def test_transition_rejects_changed_fixed_event_time() -> None:
    phase_a = PhaseAResult.model_validate(phase_a_payload())
    payload = phase_b_payload()
    payload["fixed_events"][0]["start_time"] = "15:30"
    phase_b = PhaseBResult.model_validate(payload)

    with pytest.raises(ValueError, match="固定事件"):
        validate_phase_transition(phase_a, phase_b)


def test_transition_allows_end_time_derived_from_start_and_duration() -> None:
    a_payload = phase_a_payload()
    a_payload["items"][0]["facts"]["end_time"] = None
    phase_a = PhaseAResult.model_validate(a_payload)
    phase_b = PhaseBResult.model_validate(phase_b_payload())

    validate_phase_transition(phase_a, phase_b)


def test_transition_rejects_incorrectly_derived_end_time() -> None:
    a_payload = phase_a_payload()
    a_payload["items"][0]["facts"]["end_time"] = None
    phase_a = PhaseAResult.model_validate(a_payload)
    b_payload = phase_b_payload()
    b_payload["fixed_events"][0]["end_time"] = "16:30"
    phase_b = PhaseBResult.model_validate(b_payload)

    with pytest.raises(ValueError, match="固定事件"):
        validate_phase_transition(phase_a, phase_b)


def test_transition_rejects_a_missing_fixed_event() -> None:
    phase_a = PhaseAResult.model_validate(phase_a_payload())
    payload = phase_b_payload()
    payload["fixed_events"] = []
    phase_b = PhaseBResult.model_validate(payload)

    with pytest.raises(ValueError, match="遗漏|一一对应"):
        validate_phase_transition(phase_a, phase_b)


def test_transition_rejects_a_duplicate_fixed_event() -> None:
    phase_a = PhaseAResult.model_validate(phase_a_payload())
    payload = phase_b_payload()
    payload["fixed_events"].append(dict(payload["fixed_events"][0]))
    phase_b = PhaseBResult.model_validate(payload)

    with pytest.raises(ValueError, match="重复|一一对应"):
        validate_phase_transition(phase_a, phase_b)


def test_transition_rejects_duplicate_goal_plans_for_one_source() -> None:
    a_payload = phase_a_payload()
    a_payload["items"][0]["kind"] = "abstract_goal"
    phase_a = PhaseAResult.model_validate(a_payload)
    b_payload = phase_b_payload()
    b_payload["fixed_events"] = []
    plan = {
        "source_item_id": "item_1", "goal_title": "准备面试", "deadline": None,
        "deadline_provenance": None, "importance": "medium", "urgency": "medium",
        "suggested_goal_horizon_days": 14, "task_templates": [], "assumptions": [],
    }
    b_payload["goal_plans"] = [plan, dict(plan)]
    phase_b = PhaseBResult.model_validate(b_payload)

    with pytest.raises(ValueError, match="重复|一一对应"):
        validate_phase_transition(phase_a, phase_b)


def test_transition_rejects_lost_hard_weekdays() -> None:
    a_payload = phase_a_payload()
    a_payload["items"][0]["kind"] = "abstract_goal"
    a_payload["items"][0]["facts"]["activity"] = "散步"
    phase_a = PhaseAResult.model_validate(a_payload)
    b_payload = phase_b_payload()
    b_payload["fixed_events"] = []
    b_payload["goal_plans"] = [
        {
            "source_item_id": "item_1",
            "goal_title": "规律散步",
            "deadline": None,
            "deadline_provenance": None,
            "importance": "medium",
            "urgency": "low",
            "suggested_goal_horizon_days": 56,
            "task_templates": [
                {
                    "task_id": "task_1",
                    "title": "散步",
                    "activity_type": "walking",
                    "instructions": "以舒适速度散步30分钟",
                    "duration_minutes": 30,
                    "occurrences_within_window": 6,
                    "frequency_per_week": 3,
                    "min_gap_hours": 36,
                    "depends_on": [],
                    "hard_constraints": {"allowed_weekdays": [], "required_periods": []},
                    "soft_preferences": {"preferred_periods": []},
                    "source": "user_input",
                    "provenance": [],
                    "assumptions": [],
                }
            ],
            "assumptions": [],
        }
    ]
    phase_b = PhaseBResult.model_validate(b_payload)

    with pytest.raises(ValueError, match="硬星期"):
        validate_phase_transition(phase_a, phase_b)


def test_three_weekly_exercise_sessions_require_36_hour_gap() -> None:
    payload = phase_b_payload()
    payload["fixed_events"] = []
    payload["goal_plans"] = [
        {
            "source_item_id": "item_1",
            "goal_title": "规律运动",
            "deadline": None,
            "deadline_provenance": None,
            "importance": "medium",
            "urgency": "low",
            "suggested_goal_horizon_days": 56,
            "task_templates": [
                {
                    "task_id": "task_1",
                    "title": "快走",
                    "activity_type": "brisk_walking",
                    "instructions": "以能正常交谈的速度快走30分钟",
                    "duration_minutes": 30,
                    "occurrences_within_window": 6,
                    "frequency_per_week": 3,
                    "min_gap_hours": 24,
                    "depends_on": [],
                    "hard_constraints": {"allowed_weekdays": [], "required_periods": []},
                    "soft_preferences": {"preferred_periods": []},
                    "source": "ai_suggestion",
                    "provenance": [],
                    "assumptions": [],
                }
            ],
            "assumptions": [],
        }
    ]

    with pytest.raises(ValidationError, match="36"):
        PhaseBResult.model_validate(payload)


def test_daily_study_task_can_use_a_shorter_gap() -> None:
    payload = phase_b_payload()
    payload["fixed_events"] = []
    payload["goal_plans"] = [{
        "source_item_id": "item_1",
        "goal_title": "AI面试准备",
        "deadline": "2026-09-03",
        "deadline_provenance": None,
        "importance": "high",
        "urgency": "high",
        "suggested_goal_horizon_days": 2,
        "task_templates": [{
            "task_id": "study_1",
            "title": "准备AI面试",
            "activity_type": "study",
            "instructions": "复习知识点并练习自我介绍",
            "duration_minutes": 60,
            "occurrences_within_window": 2,
            "frequency_per_week": 7,
            "min_gap_hours": 12,
            "depends_on": [],
            "hard_constraints": {"allowed_weekdays": [], "required_periods": []},
            "soft_preferences": {"preferred_periods": []},
            "source": "user_input",
            "provenance": [],
            "assumptions": [],
        }],
        "assumptions": [],
    }]

    PhaseBResult.model_validate(payload)


def test_study_task_does_not_require_a_hard_gap_when_user_did_not_specify_one() -> None:
    payload = phase_b_payload()
    payload["fixed_events"] = []
    payload["goal_plans"] = [{
        "source_item_id": "item_1", "goal_title": "面试准备", "deadline": None,
        "deadline_provenance": None, "importance": "high", "urgency": "high",
        "suggested_goal_horizon_days": 7, "assumptions": [], "task_templates": [{
            "task_id": "study_1", "title": "准备面试", "activity_type": "study",
            "instructions": "复习知识点", "duration_minutes": 30,
            "occurrences_within_window": 4, "frequency_per_week": 3,
            "min_gap_hours": 0, "depends_on": [],
            "hard_constraints": {"allowed_weekdays": [], "required_periods": []},
            "soft_preferences": {"preferred_periods": [], "pacing": "distributed"},
            "source": "ai_suggestion", "provenance": [], "assumptions": [],
        }],
    }]

    PhaseBResult.model_validate(payload)


def test_transition_rejects_lost_hard_period_and_finish_deadline() -> None:
    a_payload = phase_a_payload()
    a_payload["items"][0]["kind"] = "abstract_goal"
    a_payload["items"][0]["hard_constraints"].update({
        "required_periods": ["after_work"],
        "must_finish_before": "2026-09-02T15:00:00+08:00",
    })
    phase_a = PhaseAResult.model_validate(a_payload)
    b_payload = phase_b_payload()
    b_payload["fixed_events"] = []
    b_payload["goal_plans"] = [{
        "source_item_id": "item_1", "goal_title": "准备会议", "deadline": "2026-09-02",
        "deadline_provenance": None, "importance": "high", "urgency": "high",
        "suggested_goal_horizon_days": 1, "assumptions": [], "task_templates": [{
            "task_id": "prep_1", "title": "准备会议", "activity_type": "study",
            "instructions": "整理材料", "duration_minutes": 30,
            "occurrences_within_window": 1, "frequency_per_week": 1, "min_gap_hours": 0,
            "depends_on": [],
            "hard_constraints": {"allowed_weekdays": [3], "required_periods": []},
            "soft_preferences": {"preferred_periods": []}, "source": "user_input",
            "provenance": [], "assumptions": [],
        }],
    }]

    with pytest.raises(ValueError, match="硬时段|硬截止"):
        validate_phase_transition(phase_a, PhaseBResult.model_validate(b_payload))


def test_task_template_accepts_a_finish_before_hard_constraint() -> None:
    payload = phase_b_payload()
    payload["fixed_events"] = []
    payload["goal_plans"] = [{
        "source_item_id": "item_1",
        "goal_title": "面试准备",
        "deadline": "2026-09-03",
        "deadline_provenance": None,
        "importance": "high",
        "urgency": "high",
        "suggested_goal_horizon_days": 2,
        "task_templates": [{
            "task_id": "prepare_1", "title": "准备面试", "activity_type": "study",
            "instructions": "练习自我介绍", "duration_minutes": 60,
            "occurrences_within_window": 2, "frequency_per_week": 7,
            "min_gap_hours": 12, "depends_on": [],
            "hard_constraints": {
                "allowed_weekdays": [], "required_periods": [],
                "must_finish_before": "2026-09-03T14:00:00+08:00",
            },
            "soft_preferences": {"preferred_periods": []}, "source": "user_input",
            "provenance": [], "assumptions": [],
        }],
        "assumptions": [],
    }]

    result = PhaseBResult.model_validate(payload)

    assert result.goal_plans[0].task_templates[0].hard_constraints.must_finish_before.isoformat() == "2026-09-03T14:00:00+08:00"
