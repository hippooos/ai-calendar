"""persist local diagnostics for invalid model output"""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0002"
down_revision = "20260830_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_runs", sa.Column("diagnostic_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_runs", "diagnostic_json")
