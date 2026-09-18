from datetime import date as Date, datetime
from decimal import Decimal

from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.api.auth import current_user
from app.models import Record, RecordImage, RecordType, Trip, User
from app.storage import ObjectStorage, StorageError, StorageNotConfigured

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


class ImageOut(BaseModel):
    id: int
    record_id: int
    object_key: str
    original_filename: str
    content_type: str | None
    size_bytes: int | None
    created_at: datetime
    url: str


class RecordOut(RecordFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_id: int
    created_at: datetime
    images: list[ImageOut] = Field(default_factory=list)


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
        .options(selectinload(Trip.records).selectinload(Record.images))
    )
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def find_record(db: Session, record_id: int, user_id: int) -> Record:
    record = db.scalar(
        select(Record)
        .join(Trip)
        .where(Record.id == record_id, Trip.user_id == user_id)
        .options(selectinload(Record.images))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


def image_detail(image: RecordImage, storage: ObjectStorage) -> ImageOut:
    return ImageOut(
        id=image.id,
        record_id=image.record_id,
        object_key=image.object_key,
        original_filename=image.original_filename,
        content_type=image.content_type,
        size_bytes=image.size_bytes,
        created_at=image.created_at,
        url=storage.url(image.object_key),
    )


def record_detail(record: Record, storage: ObjectStorage) -> RecordOut:
    return RecordOut(
        id=record.id,
        trip_id=record.trip_id,
        type=record.type,
        name=record.name,
        date=record.date,
        rating=record.rating,
        cost=record.cost,
        notes=record.notes,
        created_at=record.created_at,
        images=[image_detail(image, storage) for image in record.images],
    )


def trip_detail(trip: Trip, storage: ObjectStorage) -> TripDetail:
    result = TripDetail(
        id=trip.id,
        province_code=trip.province_code,
        city_code=trip.city_code,
        city_name=trip.city_name,
        start_date=trip.start_date,
        end_date=trip.end_date,
        created_at=trip.created_at,
        records=[record_detail(record, storage) for record in trip.records],
    )
    result.records.sort(key=lambda item: (item.date, item.id), reverse=True)
    return result


def storage_from(request: Request) -> ObjectStorage:
    return request.app.state.storage


def storage_http_error(error: StorageError) -> HTTPException:
    if isinstance(error, StorageNotConfigured):
        return HTTPException(status_code=503, detail="COS storage is not configured")
    return HTTPException(status_code=502, detail="COS storage operation failed")


def delete_objects(images: list[RecordImage], storage: ObjectStorage) -> None:
    try:
        for image in images:
            storage.delete(image.object_key)
    except StorageError as error:
        raise storage_http_error(error) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="COS storage operation failed") from error


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
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[TripDetail]:
    trips = db.scalars(
        select(Trip)
        .where(Trip.user_id == user.id)
        .options(selectinload(Trip.records).selectinload(Record.images))
        .order_by(Trip.start_date.desc(), Trip.id.desc())
    ).all()
    return [trip_detail(trip, storage_from(request)) for trip in trips]


@router.get("/trips/{trip_id}", response_model=TripDetail)
def get_trip(
    trip_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> TripDetail:
    return trip_detail(find_trip(db, trip_id, user.id), storage_from(request))


@router.patch("/trips/{trip_id}", response_model=TripDetail)
def update_trip(
    trip_id: int, payload: TripPatch, request: Request,
    db: Session = Depends(get_db), user: User = Depends(current_user),
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
    return trip_detail(trip, storage_from(request))


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(
    trip_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    trip = find_trip(db, trip_id, user.id)
    delete_objects([image for record in trip.records for image in record.images], storage_from(request))
    db.delete(trip)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/trips/{trip_id}/records", response_model=RecordOut, status_code=201)
def create_record(
    trip_id: int, payload: RecordFields, request: Request,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> Record:
    trip = find_trip(db, trip_id, user.id)
    if not trip.start_date <= payload.date <= trip.end_date:
        raise HTTPException(status_code=422, detail="Record date is outside trip")
    record = Record(trip=trip, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record_detail(record, storage_from(request))


@router.get("/records/{record_id}", response_model=RecordOut)
def get_record(
    record_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Record:
    return record_detail(find_record(db, record_id, user.id), storage_from(request))


@router.patch("/records/{record_id}", response_model=RecordOut)
def update_record(
    record_id: int, payload: RecordPatch, request: Request,
    db: Session = Depends(get_db), user: User = Depends(current_user),
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
    return record_detail(record, storage_from(request))


@router.delete("/records/{record_id}", status_code=204)
def delete_record(
    record_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Response:
    record = find_record(db, record_id, user.id)
    trip = db.get(Trip, record.trip_id)
    delete_objects(record.images, storage_from(request))
    db.delete(record)
    db.flush()
    if not db.scalar(select(Record.id).where(Record.trip_id == trip.id).limit(1)):
        db.delete(trip)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


MAX_IMAGE_COUNT = 9


def image_object_key(record_id: int, filename: str | None) -> str:
    suffix = PurePosixPath(filename or "").suffix.lower()
    if len(suffix) > 10 or not suffix.isascii() or not suffix[1:].isalnum():
        suffix = ""
    return f"records/{record_id}/{uuid4().hex}{suffix}"


@router.post("/records/{record_id}/images", response_model=ImageOut, status_code=201)
def upload_image(
    record_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ImageOut:
    record = find_record(db, record_id, user.id)
    if len(record.images) >= MAX_IMAGE_COUNT:
        raise HTTPException(status_code=422, detail="A record can have at most 9 images")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image files are supported")

    storage = storage_from(request)
    object_key = image_object_key(record_id, file.filename)
    try:
        file.file.seek(0)
        storage.upload(object_key, file.file, file.content_type)
    except StorageError as error:
        raise storage_http_error(error) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="COS storage operation failed") from error

    image = RecordImage(
        record_id=record_id,
        object_key=object_key,
        original_filename=(file.filename or "image")[:255],
        content_type=file.content_type,
        size_bytes=file.size,
    )
    try:
        db.add(image)
        db.commit()
        db.refresh(image)
    except Exception:
        try:
            storage.delete(object_key)
        except Exception:
            pass
        raise
    return image_detail(image, storage)


@router.get("/records/{record_id}/images", response_model=list[ImageOut])
def list_images(
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ImageOut]:
    record = find_record(db, record_id, user.id)
    storage = storage_from(request)
    try:
        return [image_detail(image, storage) for image in record.images]
    except StorageError as error:
        raise storage_http_error(error) from error


@router.delete("/images/{image_id}", status_code=204)
def delete_image(
    image_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    image = db.scalar(
        select(RecordImage)
        .join(Record)
        .join(Trip)
        .where(RecordImage.id == image_id, Trip.user_id == user.id)
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    delete_objects([image], storage_from(request))
    db.delete(image)
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
