from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from tests.e2e.test_phase_one_flow import GoalLLMService


def client() -> TestClient:
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return TestClient(create_app(
        settings=Settings(),
        session_factory=create_session_factory(engine),
        llm_service=GoalLLMService(),
    ))


def test_generated_and_reloaded_draft_contains_frontend_display_fields() -> None:
    api = client()
    session = api.post("/api/planning/sessions", json={
        "raw_input": "未来两周每周一、周三、周五晚上散步30分钟",
        "reference_now": "2026-08-31T09:00:00+08:00",
    }).json()

    response = api.post(f"/api/planning/sessions/{session['id']}/generate-draft")

    assert response.status_code == 201
    draft = response.json()
    assert "assumptions" in draft
    assert draft["window_end"] > draft["window_start"]
    assert {"task_template", "provenance", "editable"} <= set(draft["items"][0])
    assert draft["items"][0]["task_template"]["activity_type"] == "walking"
    assert draft["items"][0]["task_template"]["instructions"] == "以舒适速度散步30分钟"
    assert draft["items"][0]["editable"] is True

    reloaded = api.get(f"/api/drafts/{draft['id']}")
    assert reloaded.status_code == 200
    assert reloaded.json() == draft


def test_confirm_endpoint_is_idempotent_for_frontend_retries() -> None:
    api = client()
    session = api.post("/api/planning/sessions", json={
        "raw_input": "未来两周每周一、周三、周五晚上散步30分钟",
        "reference_now": "2026-08-31T09:00:00+08:00",
    }).json()
    draft = api.post(f"/api/planning/sessions/{session['id']}/generate-draft").json()

    first = api.post(f"/api/drafts/{draft['id']}/confirm", headers={"Idempotency-Key": "frontend-stable-key"})
    second = api.post(f"/api/drafts/{draft['id']}/confirm", headers={"Idempotency-Key": "frontend-stable-key"})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    events = api.get("/api/calendar/events", params={
        "start": draft["window_start"],
        "end": draft["window_end"],
    }).json()
    assert len(events) == len(first.json()["event_ids"])
