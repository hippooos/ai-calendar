from datetime import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.persistence.tables import UserProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfilePayload(BaseModel):
    timezone: str = "Asia/Shanghai"
    work_start: time = time(9)
    work_end: time = time(18)
    sleep_start: time = time(23)
    sleep_end: time = time(7)


def serialize(row: UserProfile) -> dict[str, str]:
    return {"timezone":row.timezone,"work_start":row.work_start,"work_end":row.work_end,"sleep_start":row.sleep_start,"sleep_end":row.sleep_end}


def ensure_profile(db: Session) -> UserProfile:
    row = db.get(UserProfile, "default")
    if row is None:
        row = UserProfile(
            id="default", timezone="Asia/Shanghai", work_start="09:00", work_end="18:00",
            sleep_start="23:00", sleep_end="07:00", preferences_json={},
        )
        db.add(row)
        db.commit()
    return row


@router.get("")
def get_profile(db: Session = Depends(get_db)) -> dict[str, str]:
    return serialize(ensure_profile(db))


@router.put("")
def put_profile(payload: ProfilePayload, db: Session = Depends(get_db)) -> dict[str, str]:
    row = ensure_profile(db)
    values = payload.model_dump()
    values = {name:(value.strftime("%H:%M") if isinstance(value,time) else value) for name,value in values.items()}
    for name, value in values.items(): setattr(row, name, value)
    db.add(row); db.commit()
    return serialize(row)
