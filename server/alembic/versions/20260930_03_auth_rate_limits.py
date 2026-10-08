"""Persist authentication attempt windows across restarts."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_03"
down_revision: str | None = "20260930_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limits")
