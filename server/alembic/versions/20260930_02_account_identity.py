"""Add account role, status and revocable sessions."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_02"
down_revision: str | None = "20260930_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="user"))
        batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="active"))
        batch.add_column(sa.Column("requires_password_change", sa.Boolean(), nullable=False, server_default="0"))
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("requires_password_change")
        batch.drop_column("status")
        batch.drop_column("role")
