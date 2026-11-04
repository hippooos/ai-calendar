from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select

from app.persistence.db import Base, create_session_factory, create_sqlite_engine
from app.persistence.repositories import DraftRepository, PlanningSessionRepository
from app.persistence.tables import CalendarEvent, ConfirmationRequest, Draft
from app.planning.drafts import DraftService


@pytest.fixture
def db():
    engine = create_sqlite_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        yield session


def make_draft(db, count=2):
    now = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
    session = PlanningSessionRepository(db).create(raw_input="安排散步", reference_now=now)
    items = [
        {"kind":"scheduled","title":f"散步 {index + 1}","start_at":now + timedelta(days=index + 1),"end_at":now + timedelta(days=index + 1, minutes=30)}
        for index in range(count)
    ]
    return DraftRepository(db).create_with_items(session_id=session.id, window_start=now, window_end=now + timedelta(days=14), items=items)


def test_confirm_writes_whole_draft_and_marks_it_confirmed(db) -> None:
    draft = make_draft(db)

    result = DraftService(db).confirm(draft_id=draft.id, idempotency_key="confirm-1")

    assert len(result["event_ids"]) == 2
    assert db.get(Draft, draft.id).status == "confirmed"
    assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 2


def test_repeating_same_confirmation_key_does_not_duplicate_events(db) -> None:
    draft = make_draft(db)
    service = DraftService(db)

    first = service.confirm(draft_id=draft.id, idempotency_key="same-key")
    second = service.confirm(draft_id=draft.id, idempotency_key="same-key")

    assert second == first
    assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 2
    assert db.scalar(select(func.count()).select_from(ConfirmationRequest)) == 1


def test_confirmation_rolls_back_every_event_when_flush_fails(db) -> None:
    draft = make_draft(db)

    def fail_batch(_session, _context, _instances):
        if sum(isinstance(row, CalendarEvent) for row in db.new) >= 2:
            raise RuntimeError("simulated database failure")

    event.listen(db, "before_flush", fail_batch)
    with pytest.raises(RuntimeError, match="simulated"):
        DraftService(db).confirm(draft_id=draft.id, idempotency_key="will-fail")
    event.remove(db, "before_flush", fail_batch)

    assert db.scalar(select(func.count()).select_from(CalendarEvent)) == 0
    assert db.get(Draft, draft.id).status == "ready"


def test_cancel_marks_unconfirmed_draft_cancelled(db) -> None:
    draft = make_draft(db, count=1)

    cancelled = DraftService(db).cancel(draft.id)

    assert cancelled.status == "cancelled"
