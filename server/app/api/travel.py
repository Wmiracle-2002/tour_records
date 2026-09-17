from datetime import date as Date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.api.auth import current_user
from app.models import Record, RecordType, Trip, User

router = APIRouter(tags=["travel"])


class TripFields(BaseModel):
    province_code: str = Field(pattern=r"^\d{6}$")
    city_code: str = Field(pattern=r"^\d{6}$")
    city_name: str = Field(min_length=1, max_length=100)
    start_date: Date
    end_date: Date

    @field_validator("city_name")
    @classmethod
    def nonblank_city(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("City name must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def valid_dates(self) -> "TripFields":
        if self.end_date < self.start_date:
            raise ValueError("Trip end date must not precede start date")
        return self


class TripPatch(BaseModel):
    province_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    city_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    city_name: str | None = Field(default=None, min_length=1, max_length=100)
    start_date: Date | None = None
    end_date: Date | None = None


class RecordFields(BaseModel):
    type: RecordType
    name: str = Field(min_length=1, max_length=100)
    date: Date
    rating: Decimal | None = Field(default=None, ge=1, le=5, decimal_places=1)
    cost: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Record name must not be blank")
        return value.strip()


class RecordPatch(BaseModel):
    type: RecordType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    date: Date | None = None
    rating: Decimal | None = Field(default=None, ge=1, le=5, decimal_places=1)
    cost: Decimal | None = Field(default=None, ge=0, le=10000000, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    trip: TripPatch | None = None


class RecordOut(RecordFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_id: int
    created_at: datetime


class TripOut(TripFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class TripDetail(TripOut):
    records: list[RecordOut]


class StatsOut(BaseModel):
    city_count: int
    trip_count: int
    total_cost: Decimal


def find_trip(db: Session, trip_id: int, user_id: int) -> Trip:
    trip = db.scalar(
        select(Trip)
        .where(Trip.id == trip_id, Trip.user_id == user_id)
        .options(selectinload(Trip.records))
    )
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def find_record(db: Session, record_id: int, user_id: int) -> Record:
    record = db.scalar(
        select(Record)
        .join(Trip)
        .where(Record.id == record_id, Trip.user_id == user_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


def trip_detail(trip: Trip) -> TripDetail:
    result = TripDetail.model_validate(trip)
    result.records.sort(key=lambda item: (item.date, item.id), reverse=True)
    return result


@router.post("/trips", response_model=TripOut, status_code=201)
def create_trip(
    payload: TripFields, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Trip:
    trip = Trip(user=user, **payload.model_dump())
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.get("/trips", response_model=list[TripDetail])
def list_trips(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[TripDetail]:
    trips = db.scalars(
        select(Trip)
        .where(Trip.user_id == user.id)
        .options(selectinload(Trip.records))
        .order_by(Trip.start_date.desc(), Trip.id.desc())
    ).all()
    return [trip_detail(trip) for trip in trips]


@router.get("/trips/{trip_id}", response_model=TripDetail)
def get_trip(
    trip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> TripDetail:
    return trip_detail(find_trip(db, trip_id, user.id))


@router.patch("/trips/{trip_id}", response_model=TripDetail)
def update_trip(
    trip_id: int, payload: TripPatch, db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TripDetail:
    trip = find_trip(db, trip_id, user.id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Trip fields cannot be null")
    start = changes.get("start_date", trip.start_date)
    end = changes.get("end_date", trip.end_date)
    if end < start or any(not start <= record.date <= end for record in trip.records):
        raise HTTPException(status_code=422, detail="Trip dates exclude records")
    for key, value in changes.items():
        if key == "city_name":
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="City name must not be blank")
        setattr(trip, key, value)
    db.commit()
    db.refresh(trip)
    return trip_detail(trip)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(
    trip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    trip = find_trip(db, trip_id, user.id)
    db.delete(trip)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/trips/{trip_id}/records", response_model=RecordOut, status_code=201)
def create_record(
    trip_id: int, payload: RecordFields, db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Record:
    trip = find_trip(db, trip_id, user.id)
    if not trip.start_date <= payload.date <= trip.end_date:
        raise HTTPException(status_code=422, detail="Record date is outside trip")
    record = Record(trip=trip, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/records/{record_id}", response_model=RecordOut)
def get_record(
    record_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Record:
    return find_record(db, record_id, user.id)


@router.patch("/records/{record_id}", response_model=RecordOut)
def update_record(
    record_id: int, payload: RecordPatch, db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Record:
    record = find_record(db, record_id, user.id)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("type", "name", "date"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(status_code=422, detail="Record name must not be blank")
    trip = find_trip(db, record.trip_id, user.id)
    trip_changes = changes.pop("trip", None) or {}
    if any(value is None for value in trip_changes.values()):
        raise HTTPException(status_code=422, detail="Trip fields cannot be null")
    start = trip_changes.get("start_date", trip.start_date)
    end = trip_changes.get("end_date", trip.end_date)
    date_value = changes.get("date", record.date)
    if end < start or not start <= date_value <= end or any(
        not start <= other.date <= end for other in trip.records if other.id != record.id
    ):
        raise HTTPException(status_code=422, detail="Trip dates exclude records")
    for key, value in trip_changes.items():
        if key == "city_name":
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="City name must not be blank")
        setattr(trip, key, value)
    for key, value in changes.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/records/{record_id}", status_code=204)
def delete_record(
    record_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    record = find_record(db, record_id, user.id)
    trip = db.get(Trip, record.trip_id)
    db.delete(record)
    db.flush()
    if not db.scalar(select(Record.id).where(Record.trip_id == trip.id).limit(1)):
        db.delete(trip)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=StatsOut)
def stats(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> StatsOut:
    city_count, trip_count = db.execute(
        select(func.count(func.distinct(Trip.city_code)), func.count(Trip.id)).where(
            Trip.user_id == user.id
        )
    ).one()
    total = db.scalar(
        select(func.sum(Record.cost))
        .join(Trip)
        .where(Trip.user_id == user.id)
    )
    return StatsOut(
        city_count=city_count,
        trip_count=trip_count,
        total_cost=(total or Decimal("0")).quantize(Decimal("0.01")),
    )
