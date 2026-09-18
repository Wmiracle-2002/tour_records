import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.backup import backup_database, main, restore_database
from app.database import Base
from app.models import User
from app.security import hash_password


def create_footmarks_database(path: Path) -> str:
    database_url = f"sqlite:///{path}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="shared", password_hash=hash_password("test-password")))
        session.commit()
    engine.dispose()
    return database_url


def test_backup_and_restore_round_trip(tmp_path: Path):
    database = tmp_path / "footmarks.db"
    database_url = create_footmarks_database(database)
    backup = tmp_path / "backups" / "footmarks-2026-09-17.db"

    assert backup_database(database_url, backup) == backup.resolve()
    assert backup.is_file()

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DELETE FROM users")
        connection.commit()

    restore_database(database_url, backup)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT username FROM users").fetchone() == ("shared",)


def test_restore_rejects_database_without_application_schema(tmp_path: Path):
    database = tmp_path / "footmarks.db"
    database_url = create_footmarks_database(database)
    invalid_backup = tmp_path / "invalid.db"
    with sqlite3.connect(invalid_backup) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(sqlite3.DatabaseError, match="missing application tables"):
        restore_database(database_url, invalid_backup)

    with Session(create_engine(database_url)) as session:
        assert session.scalar(select(User.username)) == "shared"


def test_backup_requires_file_based_sqlite_database(tmp_path: Path):
    with pytest.raises(ValueError, match="file-based SQLite"):
        backup_database("sqlite:///:memory:", tmp_path / "backup.db")


def test_backup_cli_accepts_explicit_database_url(tmp_path: Path):
    database = tmp_path / "footmarks.db"
    database_url = create_footmarks_database(database)
    backup = tmp_path / "backup.db"

    main(["--database-url", database_url, "backup", "--output", str(backup)])

    assert backup.is_file()
