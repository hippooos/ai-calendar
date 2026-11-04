import json
from collections import Counter

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.prompts.schemas import PhaseAResult, PhaseBResult
from tests.e2e.test_phase_one_flow import GoalLLMService


def make_api(llm_service) -> TestClient:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return TestClient(
        create_app(
            settings=Settings(),
            session_factory=create_session_factory(engine),
            llm_service=llm_service,
        )
    )


class MissingStartTimeLLMService:
    async def run_phase_a(self, context):
        return PhaseAResult.model_validate({
            "decision": "needs_clarification",
            "items": [{
                "item_id": "event_1",
                "kind": "explicit_event",
                "source_text": "周三下午和客户开会，大概一小时",
                "title": "和客户开会",
                "facts": {
                    "date": "2026-09-02",
                    "start_time": None,
                    "end_time": None,
                    "duration_minutes": 60,
                    "deadline": None,
                    "stated_frequency": None,
                    "activity": "和客户开会",
                    "result_metric": None,
                },
                "hard_constraints": {
                    "allowed_weekdays": [3],
                    "required_periods": ["afternoon"],
                    "fixed_date": "2026-09-02",
                    "fixed_start_time": None,
                },
                "soft_preferences": {"preferred_periods": []},
                "provenance": [],
                "critical_missing": ["facts.start_time"],
                "assumptions": [],
            }],
            "questions": [{
                "question_id": "q_start_time",
                "priority": 30,
                "missing_field": "facts.start_time",
                "question": "周三下午几点开始和客户开会？",
                "covers_item_ids": ["event_1"],
            }],
            "manual_required": None,
            "global_assumptions": [],
        })

    async def run_phase_b(self, phase_a, context):
        raise AssertionError("需要追问时不应调用阶段 B")


class DeadlineExerciseLLMService(GoalLLMService):
    async def run_phase_a(self, context):
        payload = (await super().run_phase_a(context)).model_dump(mode="json")
        item = payload["items"][0]
        item["source_text"] = "我要在2026年9月30日前减掉5斤，未来两周每周一、周三、周五下班后运动30分钟"
        item["title"] = "9月30日前减掉5斤"
        item["facts"]["deadline"] = "2026-09-30"
        item["facts"]["result_metric"] = "减掉5斤"
        item["hard_constraints"]["required_periods"] = ["after_work"]
        return PhaseAResult.model_validate(payload)

    async def run_phase_b(self, phase_a, context):
        payload = (await super().run_phase_b(phase_a, context)).model_dump(mode="json")
        plan = payload["goal_plans"][0]
        plan["goal_title"] = "9月30日前减掉5斤"
        plan["deadline"] = "2026-09-30"
        plan["deadline_provenance"] = {
            "field_path": "goal_plans[0].deadline",
            "value": "2026-09-30",
            "source": "user_input",
            "reason": "用户明确给出期限",
            "user_editable": True,
            "display_label": "用户输入",
        }
        task = plan["task_templates"][0]
        task["title"] = "下班后快走30分钟"
        task["activity_type"] = "brisk_walking"
        task["instructions"] = "下班后以能正常交谈的速度快走30分钟"
        task["hard_constraints"]["required_periods"] = ["after_work"]
        return PhaseBResult.model_validate(payload)


def test_missing_start_time_in_known_period_returns_single_choice_options(capsys) -> None:
    api = make_api(MissingStartTimeLLMService())

    response = api.post("/api/planning/sessions", json={
        "raw_input": "周三下午和客户开会，大概一小时",
        "reference_now": "2026-08-30T10:00:00+08:00",
    })
    body = response.json()
    question = body["questions"][0]
    print("CASE_1=" + json.dumps(body, ensure_ascii=False))

    assert response.status_code == 201
    assert body["status"] == "needs_clarification"
    assert question["missing_field"] == "facts.start_time"
    assert question["input_type"] == "single_choice"
    assert question["options"] == [
        {"label": "13:00", "value": "13:00"},
        {"label": "14:00", "value": "14:00"},
        {"label": "15:00", "value": "15:00"},
        {"label": "16:00", "value": "16:00"},
        {"label": "17:00", "value": "17:00"},
    ]
    assert question["allow_custom_input"] is True


def test_confirmed_exercise_events_have_unique_dates(capsys) -> None:
    api = make_api(DeadlineExerciseLLMService())
    raw_input = "我要在2026年9月30日前减掉5斤，未来两周每周一、周三、周五下班后运动30分钟"

    session = api.post("/api/planning/sessions", json={
        "raw_input": raw_input,
        "reference_now": "2026-08-30T10:00:00+08:00",
    }).json()
    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()
    confirmation = api.post(
        f"/api/drafts/{draft['id']}/confirm",
        headers={"Idempotency-Key": "requested-exercise-example"},
    )
    events_response = api.get("/api/calendar/events", params={
        "start": "2026-08-30T10:00:00+08:00",
        "end": "2026-09-13T10:00:00+08:00",
    })
    events = events_response.json()
    print("CASE_2=" + json.dumps(events, ensure_ascii=False))

    dates = [event["start_at"][:10] for event in events]
    assert confirmation.status_code == 200
    assert events_response.status_code == 200
    assert dates == ["2026-08-31", "2026-09-02", "2026-09-04", "2026-09-07", "2026-09-09", "2026-09-11"]
    assert all(count == 1 for count in Counter(dates).values())
