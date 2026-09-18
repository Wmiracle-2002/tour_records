from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agent.tools.internal_db import TripInfo, create_internal_db_tools
from app.agent.tools.layer import ToolLayer, ToolRegistry
from app.models import Record, RecordType, Trip, User
from app.security import hash_password


def add_user(db: Session, username: str) -> User:
    user = User(username=username, password_hash=hash_password("test-password"))
    db.add(user)
    db.flush()
    return user


def add_trip(
    db: Session,
    user: User,
    city_code: str,
    city_name: str,
    start_date: date,
    end_date: date,
) -> Trip:
    trip = Trip(
        user_id=user.id,
        province_code=city_code[:2] + "0000",
        city_code=city_code,
        city_name=city_name,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(trip)
    db.flush()
    return trip


def add_record(
    db: Session,
    trip: Trip,
    name: str,
    record_type: RecordType,
    record_date: date,
    rating: str | None = None,
    cost: str | None = None,
) -> Record:
    record = Record(
        trip_id=trip.id,
        type=record_type,
        name=name,
        date=record_date,
        rating=Decimal(rating) if rating is not None else None,
        cost=Decimal(cost) if cost is not None else None,
    )
    db.add(record)
    db.flush()
    return record


def tool_layer(db: Session, user_id: int) -> ToolLayer:
    registry = ToolRegistry()
    for tool in create_internal_db_tools(db, user_id):
        registry.register(tool)
    return ToolLayer(registry)


def test_get_travel_summary_returns_aggregates(db_session: Session) -> None:
    user = add_user(db_session, "summary-user")
    beijing = add_trip(
        db_session,
        user,
        "110100",
        "北京市",
        date(2026, 9, 1),
        date(2026, 9, 3),
    )
    add_record(
        db_session,
        beijing,
        "故宫",
        RecordType.ATTRACTION,
        date(2026, 9, 1),
        rating="4.5",
        cost="100.00",
    )
    add_record(
        db_session,
        beijing,
        "烤鸭",
        RecordType.FOOD,
        date(2026, 9, 2),
        cost="50.00",
    )
    another_beijing = add_trip(
        db_session,
        user,
        "110100",
        "北京市",
        date(2025, 10, 1),
        date(2025, 10, 2),
    )
    add_record(
        db_session,
        another_beijing,
        "长城",
        RecordType.ATTRACTION,
        date(2025, 10, 1),
        rating="3.5",
        cost="20.00",
    )
    add_trip(
        db_session,
        user,
        "310100",
        "上海市",
        date(2026, 8, 1),
        date(2026, 8, 2),
    )
    db_session.commit()

    result = tool_layer(db_session, user.id).execute("get_travel_summary")

    assert result.status == "completed"
    assert result.data.trip_count == 3
    assert result.data.city_count == 2
    assert result.data.total_spending == Decimal("170.00")
    assert result.data.avg_rating == Decimal("4.00")


def test_search_trip_history_filters_city_and_overlapping_date_range(
    db_session: Session,
) -> None:
    user = add_user(db_session, "history-user")
    beijing = add_trip(
        db_session,
        user,
        "110100",
        "北京市",
        date(2026, 9, 1),
        date(2026, 9, 3),
    )
    add_trip(
        db_session,
        user,
        "310100",
        "上海市",
        date(2026, 9, 10),
        date(2026, 9, 12),
    )
    add_trip(
        db_session,
        user,
        "110100",
        "北京市",
        date(2025, 9, 1),
        date(2025, 9, 3),
    )
    db_session.commit()

    result = tool_layer(db_session, user.id).execute(
        "search_trip_history",
        city="北京",
        start_date="2026-09-02",
        end_date="2026-09-02",
    )

    assert result.status == "completed"
    assert isinstance(result.data[0], TripInfo)
    assert len(result.data) == 1
    assert result.data[0].trip_id == beijing.id
    assert result.data[0].record_count == 0
    assert result.data[0].records == []


def test_search_records_supports_filters_and_user_scope(db_session: Session) -> None:
    user = add_user(db_session, "record-user")
    other_user = add_user(db_session, "other-record-user")
    trip = add_trip(
        db_session,
        user,
        "320100",
        "南京市",
        date(2026, 10, 1),
        date(2026, 10, 3),
    )
    other_trip = add_trip(
        db_session,
        other_user,
        "320100",
        "南京市",
        date(2026, 10, 1),
        date(2026, 10, 3),
    )
    add_record(
        db_session,
        trip,
        "中山陵",
        RecordType.ATTRACTION,
        date(2026, 10, 1),
        rating="4.5",
        cost="100.00",
    )
    food = add_record(
        db_session,
        trip,
        "盐水鸭",
        RecordType.FOOD,
        date(2026, 10, 2),
        rating="3.0",
        cost="40.00",
    )
    add_record(
        db_session,
        other_trip,
        "不应返回的记录",
        RecordType.FOOD,
        date(2026, 10, 2),
        rating="3.0",
        cost="40.00",
    )
    db_session.commit()

    result = tool_layer(db_session, user.id).execute(
        "search_records",
        city="南京",
        category="FOOD",
        min_rating="3",
        max_rating="3",
        min_cost="30",
        max_cost="50",
    )

    assert result.status == "completed"
    assert len(result.data) == 1
    assert result.data[0].record_id == food.id
    assert result.data[0].city_name == "南京市"


def test_get_trip_detail_returns_structured_data_and_handles_missing_trip(
    db_session: Session,
) -> None:
    user = add_user(db_session, "detail-user")
    trip = add_trip(
        db_session,
        user,
        "330100",
        "杭州市",
        date(2026, 11, 1),
        date(2026, 11, 2),
    )
    record = add_record(
        db_session,
        trip,
        "西湖",
        RecordType.ATTRACTION,
        date(2026, 11, 1),
        cost="0.00",
    )
    db_session.commit()

    layer = tool_layer(db_session, user.id)
    result = layer.execute("get_trip_detail", trip_id=trip.id)
    missing = layer.execute("get_trip_detail", trip_id=99999)

    assert result.status == "completed"
    assert isinstance(result.data, TripInfo)
    assert result.data.trip_id == trip.id
    assert result.data.city_name == "杭州市"
    assert result.data.record_count == 1
    assert result.data.records[0].record_id == record.id
    assert result.data.records[0].cost == Decimal("0.00")
    assert missing.status == "unavailable"
    assert missing.error_code == "trip_not_found"


def test_internal_db_tool_rejects_invalid_query_boundaries(db_session: Session) -> None:
    user = add_user(db_session, "boundary-user")
    db_session.commit()

    layer = tool_layer(db_session, user.id)
    invalid_date_range = layer.execute(
        "search_trip_history",
        start_date="2026-09-03",
        end_date="2026-09-01",
    )
    invalid_trip_id = layer.execute("get_trip_detail", trip_id=0)

    assert invalid_date_range.status == "failed"
    assert invalid_date_range.error_code == "tool_execution_failed"
    assert invalid_trip_id.status == "failed"
    assert invalid_trip_id.error_code == "tool_execution_failed"
