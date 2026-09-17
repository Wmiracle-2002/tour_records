from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Record, RecordImage, RecordType, Trip, User


def test_user_trip_record_image_relationships_and_cascades(db_session: Session) -> None:
    user = User(username="shared", password_hash="hashed")
    trip = Trip(
        user=user,
        province_code="110000",
        city_code="110100",
        city_name="北京市",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
    )
    record = Record(
        trip=trip,
        type=RecordType.ATTRACTION,
        name="故宫博物院",
        date=date(2026, 9, 2),
    )
    record.images.append(
        RecordImage(object_key="records/photo.jpg", original_filename="photo.jpg")
    )
    db_session.add(user)
    db_session.commit()

    assert trip.user_id == user.id
    assert record.trip_id == trip.id
    assert record.images[0].record_id == record.id

    db_session.delete(user)
    db_session.commit()

    assert db_session.scalars(select(Trip)).all() == []
    assert db_session.scalars(select(Record)).all() == []
    assert db_session.scalars(select(RecordImage)).all() == []
