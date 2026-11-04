from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.domain.enums import DraftStatus, PlanningStatus
from app.persistence.tables import CalendarEvent, ClarificationQuestion, Draft, DraftItem, ModelRun, PlanningSession


class PlanningSessionRepository:
    def __init__(self, db: Session) -> None: self.db = db
    def create(self, *, raw_input: str, reference_now: datetime) -> PlanningSession:
        row = PlanningSession(status=PlanningStatus.RECEIVED.value, raw_input=raw_input, reference_now=reference_now)
        self.db.add(row)
        self.db.commit()
        return row

    def get(self, session_id: str) -> PlanningSession | None:
        return self.db.get(PlanningSession, session_id)

    def list_all(self) -> list[PlanningSession]:
        return list(self.db.scalars(select(PlanningSession).order_by(PlanningSession.created_at, PlanningSession.id)))

    def update(self, row: PlanningSession, **changes: Any) -> PlanningSession:
        for name, value in changes.items():
            setattr(row, name, value)
        self.db.commit()
        return row

    def claim_status(self, session_id: str, *, expected: str, claimed: str) -> bool:
        result = self.db.execute(
            update(PlanningSession)
            .where(PlanningSession.id == session_id, PlanningSession.status == expected)
            .values(status=claimed)
        )
        self.db.commit()
        return result.rowcount == 1

    def replace_questions(
        self,
        session_id: str,
        questions: list[dict[str, Any]],
        *,
        keep_answered: bool = False,
    ) -> None:
        query = delete(ClarificationQuestion).where(ClarificationQuestion.session_id == session_id)
        if keep_answered:
            query = query.where(ClarificationQuestion.answer.is_(None))
        self.db.execute(query)
        existing = set(self.db.scalars(
            select(ClarificationQuestion.question_id).where(ClarificationQuestion.session_id == session_id)
        ))
        self.db.add_all(
            ClarificationQuestion(session_id=session_id, **question)
            for question in questions
            if question["question_id"] not in existing
        )
        self.db.commit()

    def list_answered(self, session_id: str) -> list[ClarificationQuestion]:
        statement = (
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id, ClarificationQuestion.answer.is_not(None))
            .order_by(ClarificationQuestion.priority, ClarificationQuestion.id)
        )
        return list(self.db.scalars(statement))

    def save_answers(self, session_id: str, answers: dict[str, str]) -> None:
        rows = list(self.db.scalars(select(ClarificationQuestion).where(ClarificationQuestion.session_id == session_id)))
        known = {row.question_id: row for row in rows}
        unknown = set(answers) - set(known)
        if unknown:
            raise ValueError(f"未知 question_id: {sorted(unknown)}")
        for question_id, answer in answers.items():
            known[question_id].answer = answer
        self.db.commit()

    def get_answers(self, session_id: str) -> dict[str, str]:
        rows = self.db.scalars(select(ClarificationQuestion).where(ClarificationQuestion.session_id == session_id, ClarificationQuestion.answer.is_not(None)))
        return {row.question_id: row.answer for row in rows}


class ModelRunRepository:
    def __init__(self, db: Session) -> None: self.db = db

    def record(self, **values: Any) -> ModelRun:
        row = ModelRun(**values)
        self.db.add(row)
        self.db.commit()
        return row

    def list_for_session(self, session_id: str) -> list[ModelRun]:
        statement = select(ModelRun).where(ModelRun.session_id == session_id).order_by(ModelRun.created_at, ModelRun.id)
        return list(self.db.scalars(statement))


class DraftRepository:
    def __init__(self, db: Session) -> None: self.db = db
    def create_with_items(
        self,
        *,
        session_id: str,
        window_start: datetime,
        window_end: datetime,
        items: list[dict[str, Any]],
    ) -> Draft:
        draft = Draft(
            session_id=session_id,
            status=DraftStatus.READY.value,
            window_start=window_start,
            window_end=window_end,
        )
        self.db.add(draft)
        self.db.flush()
        self.db.add_all(DraftItem(draft_id=draft.id, **item) for item in items)
        self.db.commit()
        return draft

    def get_items(self, draft_id: str) -> list[DraftItem]:
        statement = select(DraftItem).where(DraftItem.draft_id == draft_id).order_by(DraftItem.start_at, DraftItem.id)
        return list(self.db.scalars(statement))


class CalendarRepository:
    def __init__(self, db: Session) -> None: self.db = db
    def add(self, **kwargs: Any) -> CalendarEvent:
        event = CalendarEvent(**kwargs)
        self.db.add(event)
        self.db.commit()
        return event

    def overlapping(self, *, start: datetime, end: datetime) -> list[CalendarEvent]:
        statement = (
            select(CalendarEvent)
            .where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.start_at < end,
                CalendarEvent.end_at > start,
            )
            .order_by(CalendarEvent.start_at, CalendarEvent.id)
        )
        return list(self.db.scalars(statement))
