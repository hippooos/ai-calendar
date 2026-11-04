from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.persistence.repositories import DraftRepository
from app.persistence.tables import Draft
from app.planning.drafts import DraftConflictError, DraftService, DraftStateError, DraftValidationError
from app.api.routes.planning import draft_response
from app.api.routes.profile import ensure_profile

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


class DraftItemPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime


@router.get("/{draft_id}")
def get_draft(draft_id: str, db: Session = Depends(get_db)) -> dict:
    draft = db.get(Draft, draft_id)
    if draft is None: raise HTTPException(404, "草案不存在")
    profile = ensure_profile(db)
    return draft_response(draft, DraftRepository(db).get_items(draft_id), profile.timezone, db)


@router.patch("/{draft_id}/items/{item_id}")
def update_draft_item(draft_id: str, item_id: str, payload: DraftItemPatch, db: Session = Depends(get_db)) -> dict:
    try:
        draft = DraftService(db).update_item(draft_id=draft_id, item_id=item_id, **payload.model_dump())
    except KeyError:
        raise HTTPException(404, "草案或草案项目不存在")
    except (DraftConflictError, DraftStateError) as exc:
        raise HTTPException(409, str(exc))
    except DraftValidationError as exc:
        raise HTTPException(422, str(exc))
    profile = ensure_profile(db)
    return draft_response(draft, DraftRepository(db).get_items(draft_id), profile.timezone, db)


@router.delete("/{draft_id}/items/{item_id}", status_code=204)
def delete_draft_item(draft_id: str, item_id: str, db: Session = Depends(get_db)) -> Response:
    try:
        DraftService(db).delete_item(draft_id=draft_id, item_id=item_id)
    except KeyError:
        raise HTTPException(404, "草案或草案项目不存在")
    except DraftStateError as exc:
        raise HTTPException(409, str(exc))
    return Response(status_code=204)


@router.post("/{draft_id}/confirm")
def confirm(draft_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), db: Session = Depends(get_db)) -> dict:
    try: return DraftService(db).confirm(draft_id=draft_id, idempotency_key=idempotency_key)
    except KeyError: raise HTTPException(404, "草案不存在")
    except DraftStateError as exc: raise HTTPException(409, str(exc))


@router.post("/{draft_id}/cancel", status_code=204)
def cancel(draft_id: str, db: Session = Depends(get_db)) -> Response:
    try: DraftService(db).cancel(draft_id)
    except KeyError: raise HTTPException(404, "草案不存在")
    except DraftStateError as exc: raise HTTPException(409, str(exc))
    return Response(status_code=204)
