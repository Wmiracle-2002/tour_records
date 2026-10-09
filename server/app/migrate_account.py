"""Inspect or transfer one legacy user's content to an empty normal account."""

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ChatConversation, KnowledgeEntry, Record, RecordImage, Trip, TripChange,
    User, UserPreference,
)


def account_counts(db: Session, user_id: int) -> dict[str, int]:
    return {
        "trips": db.scalar(select(func.count()).select_from(Trip).where(Trip.user_id == user_id)) or 0,
        "records": db.scalar(select(func.count()).select_from(Record).join(Trip).where(Trip.user_id == user_id)) or 0,
        "images": db.scalar(select(func.count()).select_from(RecordImage).join(Record).join(Trip).where(Trip.user_id == user_id)) or 0,
        "conversations": db.scalar(select(func.count()).select_from(ChatConversation).where(ChatConversation.user_id == user_id)) or 0,
        "preferences": db.scalar(select(func.count()).select_from(UserPreference).where(UserPreference.user_id == user_id)) or 0,
        "knowledge": db.scalar(select(func.count()).select_from(KnowledgeEntry).where(KnowledgeEntry.user_id == user_id)) or 0,
    }


def transfer_account(db: Session, source_name: str, target_name: str, *, apply: bool = False) -> dict[str, int]:
    if source_name == target_name:
        raise ValueError("Source and target must differ")
    source = db.scalar(select(User).where(User.username == source_name))
    target = db.scalar(select(User).where(User.username == target_name))
    if source is None or target is None or source.role != "user" or target.role != "user":
        raise ValueError("Both source and target must be existing normal accounts")
    before = account_counts(db, source.id)
    if any(account_counts(db, target.id).values()):
        raise ValueError("Target account already has content; migration stopped")
    if not apply:
        return before

    trip_ids = db.scalars(select(Trip.id).where(Trip.user_id == source.id)).all()
    db.execute(update(Trip).where(Trip.user_id == source.id).values(user_id=target.id))
    db.execute(update(ChatConversation).where(ChatConversation.user_id == source.id).values(user_id=target.id))
    db.execute(update(UserPreference).where(UserPreference.user_id == source.id).values(user_id=target.id))
    db.execute(update(KnowledgeEntry).where(KnowledgeEntry.user_id == source.id).values(user_id=target.id))
    for trip_id in trip_ids:
        db.add(TripChange(user_id=target.id, trip_id=trip_id, kind="upsert"))
    target.photo_bytes_used = source.photo_bytes_used
    if account_counts(db, target.id) != before:
        db.rollback()
        raise RuntimeError("Migrated content counts differ; no changes committed")
    db.execute(delete(TripChange).where(TripChange.user_id == source.id))
    db.delete(source)
    db.commit()
    return before


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Existing legacy username")
    parser.add_argument("target", help="Existing empty target username")
    parser.add_argument("--apply", action="store_true", help="Commit the transfer")
    parser.add_argument("--backup", type=Path, help="Fresh SQLite backup destination required for --apply")
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(transfer_account(db, args.source, args.target), ensure_ascii=False))
        if not args.apply:
            return
    if args.backup is None or args.backup.exists():
        raise SystemExit("--apply requires a new --backup path")
    from app.core.config import get_settings
    url = get_settings().database_url
    if not url.startswith("sqlite:////"):
        raise SystemExit("Only absolute SQLite database paths are supported")
    with sqlite3.connect(url.removeprefix("sqlite:///")) as original, sqlite3.connect(args.backup) as backup:
        original.backup(backup)
        if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SystemExit("Backup integrity check failed")
    with SessionLocal() as db:
        counts = transfer_account(db, args.source, args.target, apply=True)
        print(json.dumps({"transferred": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
