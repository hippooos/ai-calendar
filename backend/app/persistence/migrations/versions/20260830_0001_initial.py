"""initial phase-one tables"""
from alembic import op
import sqlalchemy as sa

revision = "20260830_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("user_profile",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("work_start", sa.String(5), nullable=False), sa.Column("work_end", sa.String(5), nullable=False),
        sa.Column("sleep_start", sa.String(5), nullable=False), sa.Column("sleep_end", sa.String(5), nullable=False),
        sa.Column("preferences_json", sa.JSON()))
    op.create_table("planning_sessions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=False), sa.Column("reference_now", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_a_version", sa.String(32)), sa.Column("prompt_b_version", sa.String(32)),
        sa.Column("phase_a_json", sa.JSON()), sa.Column("phase_b_json", sa.JSON()), sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.create_table("model_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("planning_sessions.id"), nullable=False),
        sa.Column("stage", sa.String(8), nullable=False), sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False), sa.Column("request_id", sa.String(100)),
        sa.Column("validated_json", sa.JSON()), sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("error_type", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index("ix_model_runs_session_id", "model_runs", ["session_id"])
    op.create_table("drafts",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("planning_sessions.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False), sa.Column("version", sa.Integer(), nullable=False))
    op.create_table("clarification_questions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("session_id", sa.String(36), sa.ForeignKey("planning_sessions.id"), nullable=False),
        sa.Column("question_id", sa.String(32), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("missing_field", sa.String(100), nullable=False), sa.Column("question", sa.Text(), nullable=False), sa.Column("answer", sa.Text()))
    op.create_table("draft_items",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("draft_id", sa.String(36), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)), sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("task_template_json", sa.JSON()), sa.Column("provenance_json", sa.JSON()),
        sa.Column("conflict_state", sa.String(32)), sa.Column("unscheduled_reason", sa.Text()))
    op.create_table("calendar_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("source", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_item_id", sa.String(36), sa.ForeignKey("draft_items.id")), sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_calendar_events_start_end", "calendar_events", ["start_at", "end_at"])
    op.create_table("confirmation_requests",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("draft_id", sa.String(36), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True), sa.Column("result_json", sa.JSON(), nullable=False))


def downgrade() -> None:
    op.drop_table("confirmation_requests")
    op.drop_index("ix_calendar_events_start_end", table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_table("draft_items")
    op.drop_table("drafts")
    op.drop_table("clarification_questions")
    op.drop_index("ix_model_runs_session_id", table_name="model_runs")
    op.drop_table("model_runs")
    op.drop_table("planning_sessions")
    op.drop_table("user_profile")
