from pathlib import Path
import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_initial_schema(tmp_path: Path) -> None:
    agent_logger = logging.getLogger("app.api.agent")
    database_path = tmp_path / "migration.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    assert not agent_logger.disabled

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "users",
        "trips",
        "records",
        "record_images",
        "chat_conversations",
        "chat_messages",
        "agent_conversation_memory",
        "agent_conversation_summaries",
        "agent_tool_runs",
        "agent_tool_results",
        "user_preferences",
        "alembic_version",
    } <= tables
