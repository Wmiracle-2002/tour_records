from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_region_migration_preserves_legacy_note_and_round_trips(tmp_path):
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    url = "sqlite:///" + (tmp_path / "regions.db").as_posix()
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "20260930_07")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,username,password_hash) VALUES (1,'legacy','unused')"))
        connection.execute(text("INSERT INTO knowledge_entries(id,user_id,category,title,body,city_code,city_name,tags) "
                                "VALUES (1,1,'note','旧笔记','旧正文','350100','福州市','[]')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT body,sections FROM knowledge_entries WHERE id=1")).one()
        assert row == ("旧正文", "[]")
    command.downgrade(config, "20260930_07")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT body FROM knowledge_entries WHERE id=1")).scalar_one() == "旧正文"
    engine.dispose()
