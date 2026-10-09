"""Add monthly token limits and per-call accounting."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_04"
down_revision: str | None = "20260930_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("monthly_token_limit", sa.Integer(), nullable=True))
    op.create_table(
        "monthly_token_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "period", name="uq_monthly_token_usage_user_period"),
    )
    op.create_index("ix_monthly_token_usage_user_id", "monthly_token_usage", ["user_id"])
    op.create_table(
        "token_usage_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_token_usage_calls_user_id", "token_usage_calls", ["user_id"])
    op.create_index("ix_token_usage_calls_period", "token_usage_calls", ["period"])
    op.create_table(
        "token_quota_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("default_limit", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("INSERT INTO token_quota_policy (id, default_limit) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table("token_quota_policy")
    op.drop_index("ix_token_usage_calls_period", table_name="token_usage_calls")
    op.drop_index("ix_token_usage_calls_user_id", table_name="token_usage_calls")
    op.drop_table("token_usage_calls")
    op.drop_index("ix_monthly_token_usage_user_id", table_name="monthly_token_usage")
    op.drop_table("monthly_token_usage")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("monthly_token_limit")
