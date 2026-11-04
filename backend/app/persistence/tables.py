from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.persistence.db import Base


def uuid_string() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime 必须包含时区")
        utc_value = value.astimezone(timezone.utc)
        return utc_value.replace(tzinfo=None) if dialect.name == "sqlite" else utc_value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class PlanningSession(Base):
    __tablename__ = "planning_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    reference_now: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    prompt_a_version: Mapped[str | None] = mapped_column(String(32))
    prompt_b_version: Mapped[str | None] = mapped_column(String(32))
    phase_a_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    phase_b_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class UserProfile(Base):
    __tablename__ = "user_profile"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="default")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    work_start: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    work_end: Mapped[str] = mapped_column(String(5), nullable=False, default="18:00")
    sleep_start: Mapped[str] = mapped_column(String(5), nullable=False, default="23:00")
    sleep_end: Mapped[str] = mapped_column(String(5), nullable=False, default="07:00")
    preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("planning_sessions.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_field: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("planning_sessions.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(8), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    validated_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    diagnostic_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("planning_sessions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class DraftItem(Base):
    __tablename__ = "draft_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    task_template_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    provenance_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    conflict_state: Mapped[str | None] = mapped_column(String(32))
    unscheduled_reason: Mapped[str | None] = mapped_column(Text)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (Index("ix_calendar_events_start_end", "start_at", "end_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    draft_item_id: Mapped[str | None] = mapped_column(ForeignKey("draft_items.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ConfirmationRequest(Base):
    __tablename__ = "confirmation_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
