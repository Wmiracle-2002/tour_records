from pathlib import Path
import logging

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


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
        "auth_sessions",
        "auth_rate_limits",
        "monthly_token_usage", "token_usage_calls", "token_quota_policy", "trip_changes",
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
        "knowledge_entries",
        "alembic_version",
    } <= tables


def test_account_migration_preserves_existing_user(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "20260930_01")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (username, password_hash) VALUES ('shared', 'old-hash')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT username, password_hash, role, status FROM users")).one()
    engine.dispose()
    assert row == ("shared", "old-hash", "user", "active")
