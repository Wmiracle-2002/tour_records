"""Add account-owned travel knowledge entries."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_01"
down_revision: str | None = "20260927_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("city_code", sa.String(6), nullable=False),
        sa.Column("city_name", sa.String(100), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "category IN ('note', 'travel_guide', 'food_guide', 'attraction_guide')",
            name="ck_knowledge_entry_category",
        ),
    )
    op.create_index("ix_knowledge_entries_user_id", "knowledge_entries", ["user_id"])
    op.create_index("ix_knowledge_entries_city_code", "knowledge_entries", ["city_code"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_entries_city_code", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_entries_user_id", table_name="knowledge_entries")
    op.drop_table("knowledge_entries")
