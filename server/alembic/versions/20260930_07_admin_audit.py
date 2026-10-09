"""Record administrator mutations without request bodies or secrets."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_07"
down_revision: str | None = "20260930_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("object_id", sa.String(80), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("admin_audit")
