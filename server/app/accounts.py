"""Account cleanup shared by self-service and administrator deletion."""

from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AuthSession, Record, RecordImage, Trip, User


def delete_account(db: Session, request: Request, user: User) -> None:
    if user.status != "deleting":
        user.status = "deleting"
        db.execute(
            update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        db.commit()
    keys = db.scalars(
        select(RecordImage.object_key).join(Record).join(Trip).where(Trip.user_id == user.id)
    ).all()
    try:
        for key in keys:
            request.app.state.storage.delete(key)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Account photo cleanup failed; retry required") from error
    db.delete(user)
    db.commit()
