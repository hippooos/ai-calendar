from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.prompts.schemas import PhaseAResult, PhaseBResult
from tests.contract.test_prompt_schemas import phase_a_payload, phase_b_payload


class FakeLLMService:
    async def run_phase_a(self, context):
        return PhaseAResult.model_validate(phase_a_payload())

    async def run_phase_b(self, phase_a, context):
        return PhaseBResult.model_validate(phase_b_payload())


def client(app_mode="local", access_code=None, llm_service=None):
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    settings = Settings(app_mode=app_mode, app_access_code=access_code)
    return TestClient(create_app(settings=settings, session_factory=factory, llm_service=llm_service or FakeLLMService()))


class ClarificationLLMService(FakeLLMService):
    def __init__(self): self.calls = 0
    async def run_phase_a(self, context):
        self.calls += 1
        payload = phase_a_payload()
        if self.calls == 1:
            payload["decision"]="needs_clarification"
            payload["questions"]=[{"question_id":"q1","priority":20,"missing_field":"facts.date","question":"哪一天？","covers_item_ids":["item_1"]}]
        return PhaseAResult.model_validate(payload)


class ContextCapturingLLMService(FakeLLMService):
    def __init__(self):
        self.phase_a_context = None

    async def run_phase_a(self, context):
        self.phase_a_context = context
        return await super().run_phase_a(context)


class MonthWeekendLLMService(FakeLLMService):
    def __init__(self) -> None:
        self.phase_b_window_days = None

    async def run_phase_a(self, context):
        def goal(item_id, title, activity):
            return {
                "item_id": item_id, "kind": "abstract_goal", "source_text": title, "title": title,
                "facts": {"date": None, "start_time": None, "end_time": None, "duration_minutes": None,
                          "deadline": "2026-10-23", "stated_frequency": "每周末", "activity": activity,
                          "result_metric": None},
                "hard_constraints": {"allowed_weekdays": [6, 7], "required_periods": []},
                "soft_preferences": {"preferred_periods": [], "pacing": "distributed"},
                "provenance": [], "critical_missing": [], "assumptions": [],
            }
        return PhaseAResult.model_validate({
            "decision": "ready",
            "items": [goal("badminton", "周末打羽毛球", "打羽毛球"), goal("interview", "周末准备面试", "准备面试")],
            "questions": [], "manual_required": None, "global_assumptions": [],
        })

    async def run_phase_b(self, phase_a, context):
        self.phase_b_window_days = context.get("planning_window_days")

        def plan(source_id, title, activity, task_id):
            return {
                "source_item_id": source_id, "goal_title": title, "deadline": "2026-10-23",
                "deadline_provenance": None, "importance": "medium", "urgency": "medium",
                "suggested_goal_horizon_days": 30, "assumptions": [], "task_templates": [{
                    "task_id": task_id, "title": title, "activity_type": activity,
                    "instructions": title, "duration_minutes": 60, "occurrences_within_window": 4,
                    "frequency_per_week": 1, "min_gap_hours": 0, "depends_on": [],
                    "hard_constraints": {"allowed_weekdays": [6, 7], "required_periods": []},
                    "soft_preferences": {"preferred_periods": [], "pacing": "distributed"},
                    "source": "user_input", "provenance": [], "assumptions": [],
                }],
            }
        return PhaseBResult.model_validate({
            "decision": "ready_for_scheduling", "fixed_events": [],
            "goal_plans": [
                plan("badminton", "周末打羽毛球", "badminton", "badminton_task"),
                plan("interview", "周末准备面试", "study", "interview_task"),
            ],
            "assumptions": [],
        })


def test_local_api_completes_submit_draft_confirm_calendar_flow() -> None:
    api = client()
    submitted = api.post("/api/planning/sessions", json={"raw_input":"9月2日15点到16点开会","reference_now":"2026-08-30T10:00:00+08:00"})
    assert submitted.status_code == 201
    assert submitted.json()["status"] == "a_ready"

    session_id = submitted.json()["id"]
    generated = api.post(f"/api/planning/sessions/{session_id}/generate-draft")
    assert generated.status_code == 201
    assert generated.json()["status"] == "ready"
    assert len(generated.json()["items"]) == 1

    draft_id = generated.json()["id"]
    confirmed = api.post(f"/api/drafts/{draft_id}/confirm", headers={"Idempotency-Key":"flow-1"})
    assert confirmed.status_code == 200
    assert len(confirmed.json()["event_ids"]) == 1

    events = api.get("/api/calendar/events", params={"start":"2026-09-01T00:00:00+08:00","end":"2026-09-04T00:00:00+08:00"})
    assert events.status_code == 200
    assert [event["title"] for event in events.json()] == ["开会"]
    assert events.json()[0]["start_at"] == "2026-09-02T15:00:00+08:00"


def test_one_month_request_uses_a_30_day_draft_window_and_passes_it_to_phase_b() -> None:
    service = MonthWeekendLLMService()
    api = client(llm_service=service)
    submitted = api.post("/api/planning/sessions", json={
        "raw_input": "最近一个月我想周末都打打羽毛球和准备准备面试",
        "reference_now": "2026-09-23T10:00:00+08:00",
    }).json()

    draft = api.post(f"/api/planning/sessions/{submitted['id']}/generate-draft")

    assert draft.status_code == 201
    assert draft.json()["window_end"] == "2026-10-23T10:00:00+08:00"
    assert draft.json()["window_days"] == 30
    assert service.phase_b_window_days == 30
    assert len(draft.json()["items"]) == 8
    assert all(datetime.fromisoformat(item["start_at"]).isoweekday() in {6, 7} for item in draft.json()["items"])


def test_deployed_mode_requires_access_code_but_health_is_public() -> None:
    api = client(app_mode="deployed", access_code="owner-code")

    assert api.get("/healthz").status_code == 200
    assert api.get("/api/profile").status_code == 401
    assert api.get("/api/profile", headers={"X-Access-Code":"wrong"}).status_code == 401
    assert api.get("/api/profile", headers={"X-Access-Code":"owner-code"}).status_code == 200


def test_profile_can_be_updated_and_read() -> None:
    api = client()
    payload = {"timezone":"Asia/Shanghai","work_start":"09:00","work_end":"18:00","sleep_start":"23:00","sleep_end":"07:00"}

    updated = api.put("/api/profile", json=payload)
    loaded = api.get("/api/profile")

    assert updated.status_code == 200
    assert loaded.json() == payload


def test_planning_phase_a_receives_saved_profile_context() -> None:
    service = ContextCapturingLLMService()
    api = client(llm_service=service)
    api.put("/api/profile", json={
        "timezone":"Asia/Shanghai", "work_start":"08:30", "work_end":"17:30",
        "sleep_start":"22:30", "sleep_end":"06:30",
    })

    response = api.post("/api/planning/sessions", json={"raw_input":"下班后散步"})

    assert response.status_code == 201
    assert service.phase_a_context["timezone"] == "Asia/Shanghai"
    assert service.phase_a_context["user_profile"] == {
        "work_start":"08:30", "work_end":"17:30", "sleep_start":"22:30",
        "sleep_end":"06:30", "preferences":{},
    }


def test_planning_converts_utc_reference_time_to_the_profile_timezone_before_phase_a() -> None:
    service = ContextCapturingLLMService()
    api = client(llm_service=service)

    response = api.post("/api/planning/sessions", json={
        "raw_input": "明天下午开会",
        "reference_now": "2026-09-01T17:56:00Z",
    })

    assert response.status_code == 201
    assert service.phase_a_context["reference_now"] == "2026-09-02T01:56:00+08:00"


def test_calendar_event_can_be_edited_and_soft_deleted() -> None:
    api = client()
    submitted = api.post("/api/planning/sessions", json={"raw_input":"开会","reference_now":"2026-08-30T10:00:00+08:00"}).json()
    draft = api.post(f"/api/planning/sessions/{submitted['id']}/generate-draft").json()
    event_id = api.post(f"/api/drafts/{draft['id']}/confirm", headers={"Idempotency-Key":"crud-1"}).json()["event_ids"][0]

    edited = api.patch(f"/api/calendar/events/{event_id}", json={"title":"客户会议"})
    deleted = api.delete(f"/api/calendar/events/{event_id}")

    assert edited.json()["title"] == "客户会议"
    assert deleted.status_code == 204


def test_clarification_answer_advances_existing_session() -> None:
    api = client(llm_service=ClarificationLLMService())
    submitted = api.post("/api/planning/sessions", json={"raw_input":"安排开会"}).json()

    answered = api.post(f"/api/planning/sessions/{submitted['id']}/answers", json={"answers":{"q1":"2026年9月2日"}})

    assert answered.status_code == 200
    assert answered.json()["id"] == submitted["id"]
    assert answered.json()["status"] == "a_ready"
