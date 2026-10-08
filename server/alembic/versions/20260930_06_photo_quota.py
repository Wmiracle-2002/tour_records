"""Track uploaded photo bytes per account."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260930_06"
down_revision: str | None = "20260930_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("photo_bytes_used", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
        UPDATE users SET photo_bytes_used = COALESCE((
            SELECT SUM(record_images.size_bytes)
            FROM record_images
            JOIN records ON records.id = record_images.record_id
            JOIN trips ON trips.id = records.trip_id
            WHERE trips.user_id = users.id
        ), 0)
    """)


def downgrade() -> None:
    op.drop_column("users", "photo_bytes_used")
