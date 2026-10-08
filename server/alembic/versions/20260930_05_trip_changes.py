"""Add account-scoped trip change sequence for incremental sync."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_05"
down_revision: str | None = "20260930_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trip_changes",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trip_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
    )
    op.create_index("ix_trip_changes_user_id", "trip_changes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_trip_changes_user_id", table_name="trip_changes")
    op.drop_table("trip_changes")
