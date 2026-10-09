"""Store user-confirmed region/category excerpts alongside their original note."""

from alembic import op
import sqlalchemy as sa

revision = "20261009_01"
down_revision = "20260930_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_entries", sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_entries") as batch:
        batch.drop_column("sections")
