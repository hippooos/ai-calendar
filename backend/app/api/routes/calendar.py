from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.routes.profile import ensure_profile
from app.persistence.repositories import CalendarRepository
from app.persistence.tables import CalendarEvent

router = APIRouter(prefix="/api/calendar/events", tags=["calendar"])


def serialize(row: CalendarEvent, timezone_name: str) -> dict:
    tz = ZoneInfo(timezone_name)
    return {"id":row.id,"source":row.source,"title":row.title,"start_at":row.start_at.astimezone(tz),"end_at":row.end_at.astimezone(tz)}


@router.get("")
def list_events(start: datetime, end: datetime, db: Session = Depends(get_db)) -> list[dict]:
    if end <= start: raise HTTPException(422, "end 必须晚于 start")
    timezone_name = ensure_profile(db).timezone
    return [serialize(event, timezone_name) for event in CalendarRepository(db).overlapping(start=start,end=end)]


class EventPatch(BaseModel):
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


@router.patch("/{event_id}")
def update_event(event_id: str, payload: EventPatch, db: Session = Depends(get_db)) -> dict:
    row = db.get(CalendarEvent, event_id)
    if row is None or row.deleted_at is not None: raise HTTPException(404, "日程不存在")
    for name, value in payload.model_dump(exclude_none=True).items(): setattr(row,name,value)
    if row.end_at <= row.start_at: raise HTTPException(422,"结束时间必须晚于开始时间")
    db.commit(); return serialize(row, ensure_profile(db).timezone)


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: str, db: Session = Depends(get_db)) -> Response:
    row = db.get(CalendarEvent,event_id)
    if row is None or row.deleted_at is not None: raise HTTPException(404,"日程不存在")
    row.deleted_at=datetime.now(timezone.utc); db.commit(); return Response(status_code=204)
