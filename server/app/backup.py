"""Backup and restore the local SQLite database."""

from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.config import get_settings

REQUIRED_TABLES = {"users", "trips", "records", "record_images"}


def database_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///") or ":memory:" in database_url:
        raise ValueError("Backup and restore require a file-based SQLite database URL")
    return Path(database_url.removeprefix("sqlite:///" )).expanduser().resolve()


def backup_database(database_url: str, destination: str | Path) -> Path:
    source = database_path(database_url)
    if not source.is_file():
        raise FileNotFoundError(f"Database file does not exist: {source}")
    target = Path(destination).expanduser().resolve()
    _copy_database(source, target)
    return target


def restore_database(database_url: str, source: str | Path) -> Path:
    target = database_path(database_url)
    backup = Path(source).expanduser().resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {backup}")
    if backup == target:
        raise ValueError("Backup source and database target must be different files")
    _copy_database(backup, target)
    return target


def _copy_database(source: Path, target: Path) -> None:
    if source == target:
        raise ValueError("Backup source and target must be different files")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with closing(sqlite3.connect(source)) as source_connection:
            _validate_database(source_connection)
            with closing(sqlite3.connect(temporary)) as target_connection:
                source_connection.backup(target_connection)
                _validate_database(target_connection)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_database(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise sqlite3.DatabaseError(f"SQLite integrity check failed: {integrity}")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = REQUIRED_TABLES - tables
    if missing:
        names = ", ".join(sorted(missing))
        raise sqlite3.DatabaseError(f"SQLite database is missing application tables: {names}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backup or restore the Footmarks SQLite database")
    parser.add_argument(
        "--database-url",
        help="SQLite database URL; defaults to FOOTMARKS_DATABASE_URL",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup_parser = commands.add_parser("backup", help="Create a database backup")
    backup_parser.add_argument("--output", required=True, help="Backup file path")

    restore_parser = commands.add_parser("restore", help="Restore a database backup")
    restore_parser.add_argument("--input", required=True, help="Backup file path")

    arguments = parser.parse_args(argv)
    database_url = arguments.database_url or get_settings().database_url
    try:
        if arguments.command == "backup":
            path = backup_database(database_url, arguments.output)
            print(f"Database backup created: {path}")
        else:
            path = restore_database(database_url, arguments.input)
            print(f"Database restored: {path}")
    except (OSError, sqlite3.DatabaseError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
