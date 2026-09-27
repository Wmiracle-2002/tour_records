"""Add per-conversation memory, summaries, and tool result index."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260927_02"
down_revision: str | None = "20260927_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_conversation_memory",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("summary_cursor_message_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_table(
        "agent_conversation_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("first_message_id", sa.Integer(), nullable=False),
        sa.Column("last_message_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["first_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["last_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "first_message_id",
            "last_message_id",
            "chunk_index",
            name="uq_agent_summary_source_chunk",
        ),
    )
    op.create_index(
        "ix_agent_conversation_summaries_conversation_id",
        "agent_conversation_summaries",
        ["conversation_id"],
    )
    op.create_table(
        "agent_tool_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "status IN ('completed', 'failed', 'unavailable')",
            name="ck_agent_tool_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_tool_runs_conversation_id", "agent_tool_runs", ["conversation_id"]
    )
    op.create_index(
        "ix_agent_tool_runs_source_message_id",
        "agent_tool_runs",
        ["source_message_id"],
    )
    op.create_index("ix_agent_tool_runs_tool_name", "agent_tool_runs", ["tool_name"])
    op.create_index("ix_agent_tool_runs_called_at", "agent_tool_runs", ["called_at"])
    op.create_table(
        "agent_tool_results",
        sa.Column("tool_run_id", sa.String(length=36), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tool_run_id"], ["agent_tool_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tool_run_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_tool_results")
    op.drop_index("ix_agent_tool_runs_called_at", table_name="agent_tool_runs")
    op.drop_index("ix_agent_tool_runs_tool_name", table_name="agent_tool_runs")
    op.drop_index("ix_agent_tool_runs_source_message_id", table_name="agent_tool_runs")
    op.drop_index("ix_agent_tool_runs_conversation_id", table_name="agent_tool_runs")
    op.drop_table("agent_tool_runs")
    op.drop_index(
        "ix_agent_conversation_summaries_conversation_id",
        table_name="agent_conversation_summaries",
    )
    op.drop_table("agent_conversation_summaries")
    op.drop_table("agent_conversation_memory")
