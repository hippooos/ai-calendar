from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.persistence.repositories import DraftRepository, PlanningSessionRepository


@pytest.fixture
def api_and_draft():
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 8, 31, 2, tzinfo=timezone.utc)
    with factory() as db:
        session = PlanningSessionRepository(db).create(raw_input="安排会议", reference_now=now)
        draft = DraftRepository(db).create_with_items(
            session_id=session.id,
            window_start=now,
            window_end=now + timedelta(days=14),
            items=[
                {"kind": "fixed", "title": "客户会议", "start_at": now + timedelta(days=2, hours=5), "end_at": now + timedelta(days=2, hours=6)},
                {"kind": "scheduled", "title": "快走", "start_at": now + timedelta(days=3, hours=8), "end_at": now + timedelta(days=3, hours=8, minutes=30)},
            ],
        )
        item_ids = [item.id for item in DraftRepository(db).get_items(draft.id)]
        ids = SimpleNamespace(draft_id=draft.id, edited_item_id=item_ids[0], other_item_id=item_ids[1])
    return TestClient(create_app(settings=Settings(), session_factory=factory)), ids


def test_ready_draft_item_can_be_edited_and_persists(api_and_draft):
    api, ids = api_and_draft
    response = api.patch(f"/api/drafts/{ids.draft_id}/items/{ids.edited_item_id}", json={
        "title": "客户方案沟通",
        "start_at": "2026-09-02T15:30:00+08:00",
        "end_at": "2026-09-02T16:30:00+08:00",
    })
    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == ids.edited_item_id)
    assert item["title"] == "客户方案沟通"
    assert item["start_at"].endswith("15:30:00+08:00")
    persisted = api.get(f"/api/drafts/{ids.draft_id}").json()
    assert next(item for item in persisted["items"] if item["id"] == ids.edited_item_id)["title"] == "客户方案沟通"


def test_draft_edit_rejects_overlap_with_another_item(api_and_draft):
    api, ids = api_and_draft
    response = api.patch(f"/api/drafts/{ids.draft_id}/items/{ids.edited_item_id}", json={
        "title": "冲突会议",
        "start_at": "2026-09-03T18:00:00+08:00",
        "end_at": "2026-09-03T18:30:00+08:00",
    })
    assert response.status_code == 409
    assert response.json()["error_code"] == "REQUEST_ERROR"


def test_ready_item_can_be_deleted_but_confirmed_item_cannot(api_and_draft):
    api, ids = api_and_draft
    assert api.delete(f"/api/drafts/{ids.draft_id}/items/{ids.other_item_id}").status_code == 204
    assert all(item["id"] != ids.other_item_id for item in api.get(f"/api/drafts/{ids.draft_id}").json()["items"])
    assert api.post(f"/api/drafts/{ids.draft_id}/confirm", headers={"Idempotency-Key": "edit-test"}).status_code == 200
    response = api.delete(f"/api/drafts/{ids.draft_id}/items/{ids.edited_item_id}")
    assert response.status_code == 409
