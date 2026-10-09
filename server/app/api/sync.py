"""Account-scoped paginated trip snapshot and ordered changes."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.auth import current_user
from app.api.travel import TripDetail, storage_from, trip_detail
from app.database import get_db
from app.models import Record, Trip, TripChange, User


router = APIRouter(prefix="/sync", tags=["sync"])


class TripSyncPage(BaseModel):
    upserts: list[TripDetail]
    deleted_ids: list[int]
    next_cursor: str
    has_more: bool


@router.get("/trips", response_model=TripSyncPage)
def sync_trips(
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TripSyncPage:
    if cursor is None:
        watermark = db.scalar(select(func.max(TripChange.seq)).where(TripChange.user_id == user.id)) or 0
        cursor = f"s:{watermark}:0"
    snapshot_match = re.fullmatch(r"s:(\d+):(\d+)", cursor)
    delta_match = re.fullmatch(r"d:(\d+)", cursor)
    if snapshot_match:
        watermark, after_id = map(int, snapshot_match.groups())
        trips = db.scalars(
            select(Trip)
            .where(Trip.user_id == user.id, Trip.id > after_id)
            .options(selectinload(Trip.records).selectinload(Record.images))
            .order_by(Trip.id).limit(limit + 1)
        ).all()
        more = len(trips) > limit
        selected = trips[:limit]
        next_cursor = f"s:{watermark}:{selected[-1].id}" if more else f"d:{watermark}"
        return TripSyncPage(
            upserts=[trip_detail(trip, storage_from(request)) for trip in selected],
            deleted_ids=[], next_cursor=next_cursor, has_more=more,
        )
    if delta_match:
        last_seq = int(delta_match.group(1))
        events = db.scalars(
            select(TripChange)
            .where(TripChange.user_id == user.id, TripChange.seq > last_seq)
            .order_by(TripChange.seq).limit(limit + 1)
        ).all()
        more = len(events) > limit
        selected_events = events[:limit]
        if not selected_events:
            return TripSyncPage(upserts=[], deleted_ids=[], next_cursor=cursor, has_more=False)
        latest = {event.trip_id: event.kind for event in selected_events}
        trip_ids = [trip_id for trip_id, kind in latest.items() if kind == "upsert"]
        trips = db.scalars(
            select(Trip)
            .where(Trip.user_id == user.id, Trip.id.in_(trip_ids))
            .options(selectinload(Trip.records).selectinload(Record.images))
        ).all() if trip_ids else []
        found = {trip.id for trip in trips}
        deleted = [trip_id for trip_id, kind in latest.items() if kind == "delete" or trip_id not in found]
        return TripSyncPage(
            upserts=[trip_detail(trip, storage_from(request)) for trip in trips],
            deleted_ids=deleted, next_cursor=f"d:{selected_events[-1].seq}", has_more=more,
        )
    raise HTTPException(status_code=422, detail="Invalid sync cursor")
