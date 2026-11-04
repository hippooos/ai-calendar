from sqlalchemy import select

from app.domain.enums import CalendarSource, DraftStatus
from app.persistence.tables import CalendarEvent, ConfirmationRequest, Draft, DraftItem


class DraftStateError(RuntimeError):
    pass


class DraftValidationError(ValueError):
    pass


class DraftConflictError(RuntimeError):
    pass


class DraftService:
    def __init__(self, db) -> None:
        self.db = db

    def update_item(self, *, draft_id: str, item_id: str, title: str, start_at, end_at) -> Draft:
        draft = self.db.get(Draft, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != DraftStatus.READY.value:
            raise DraftStateError("only ready drafts can be edited")
        item = self.db.scalar(select(DraftItem).where(DraftItem.id == item_id, DraftItem.draft_id == draft_id))
        if item is None:
            raise KeyError(item_id)
        if not title.strip() or start_at.tzinfo is None or end_at.tzinfo is None or end_at <= start_at:
            raise DraftValidationError("草案项目的标题或时间无效")
        if start_at < draft.window_start or end_at > draft.window_end:
            raise DraftValidationError("草案项目必须位于14天窗口内")
        calendar_conflict = self.db.scalar(select(CalendarEvent.id).where(
            CalendarEvent.deleted_at.is_(None), CalendarEvent.start_at < end_at, CalendarEvent.end_at > start_at,
        ))
        draft_conflict = self.db.scalar(select(DraftItem.id).where(
            DraftItem.draft_id == draft_id,
            DraftItem.id != item_id,
            DraftItem.start_at.is_not(None),
            DraftItem.end_at.is_not(None),
            DraftItem.start_at < end_at,
            DraftItem.end_at > start_at,
        ))
        if calendar_conflict or draft_conflict:
            raise DraftConflictError("编辑后的时间与已有安排冲突")
        item.title = title.strip()
        item.start_at = start_at
        item.end_at = end_at
        if item.kind == "unscheduled":
            item.kind = "scheduled"
            item.conflict_state = None
            item.unscheduled_reason = None
        self.db.commit()
        return draft

    def delete_item(self, *, draft_id: str, item_id: str) -> None:
        draft = self.db.get(Draft, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != DraftStatus.READY.value:
            raise DraftStateError("only ready drafts can be edited")
        item = self.db.scalar(select(DraftItem).where(DraftItem.id == item_id, DraftItem.draft_id == draft_id))
        if item is None:
            raise KeyError(item_id)
        self.db.delete(item)
        self.db.commit()

    def confirm(self, *, draft_id: str, idempotency_key: str) -> dict:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key 不能为空")
        existing = self.db.scalar(select(ConfirmationRequest).where(ConfirmationRequest.idempotency_key == idempotency_key))
        if existing is not None:
            return existing.result_json
        draft = self.db.get(Draft, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != DraftStatus.READY.value:
            raise DraftStateError(f"draft must be ready, got {draft.status}")

        items = list(self.db.scalars(select(DraftItem).where(DraftItem.draft_id == draft_id).order_by(DraftItem.start_at, DraftItem.id)))
        scheduled = [item for item in items if item.start_at is not None and item.end_at is not None]
        try:
            draft.status = DraftStatus.CONFIRMING.value
            events = [
                CalendarEvent(
                    source=CalendarSource.AI.value,
                    title=item.title,
                    start_at=item.start_at,
                    end_at=item.end_at,
                    draft_item_id=item.id,
                )
                for item in scheduled
            ]
            self.db.add_all(events)
            self.db.flush()
            result = {"draft_id": draft.id, "event_ids": [event.id for event in events]}
            self.db.add(ConfirmationRequest(draft_id=draft.id, idempotency_key=idempotency_key, result_json=result))
            draft.status = DraftStatus.CONFIRMED.value
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def cancel(self, draft_id: str) -> Draft:
        draft = self.db.get(Draft, draft_id)
        if draft is None:
            raise KeyError(draft_id)
        if draft.status != DraftStatus.READY.value:
            raise DraftStateError(f"only ready drafts can be cancelled, got {draft.status}")
        draft.status = DraftStatus.CANCELLED.value
        self.db.commit()
        return draft
