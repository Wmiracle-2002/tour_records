"""Internal database tools for the Travel Agent."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agent.tools.layer import ToolResult
from app.models import Record, RecordType, Trip


def decimal_value(value: Any, default: str = "0.00") -> Decimal:
    """将数据库聚合值转换为稳定的两位小数。"""
    if value is None:
        return Decimal(default)
    return Decimal(str(value)).quantize(Decimal("0.01"))


class TravelSummary(BaseModel):
    """用户旅行数据的汇总结果。"""

    trip_count: int = Field(ge=0)
    city_count: int = Field(ge=0)
    total_spending: Decimal = Field(ge=0)
    avg_rating: Decimal | None = Field(default=None, ge=1, le=5)


class RecordSearchItem(BaseModel):
    """记录查询返回的一条景点或美食记录。"""

    record_id: int = Field(ge=1)
    trip_id: int = Field(ge=1)
    city_name: str
    category: RecordType
    name: str
    date: date
    rating: Decimal | None = Field(default=None, ge=1, le=5)
    cost: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class TripInfo(BaseModel):
    """一条旅行信息，可表示历史摘要或带记录的完整详情。"""

    trip_id: int = Field(ge=1)
    city_code: str
    city_name: str
    start_date: date
    end_date: date
    record_count: int = Field(default=0, ge=0)
    records: list[RecordSearchItem] = Field(default_factory=list)


class SearchTripHistoryInput(BaseModel):
    """历史旅行查询的筛选条件。"""

    city: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("city", mode="before")
    @classmethod
    def normalize_city(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def valid_date_range(self) -> "SearchTripHistoryInput":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must not precede start date")
        return self


class SearchRecordsInput(BaseModel):
    """旅行记录查询的筛选条件。"""

    trip_id: int | None = Field(default=None, ge=1)
    city: str | None = None
    category: RecordType | None = None
    min_rating: Decimal | None = Field(default=None, ge=1, le=5)
    max_rating: Decimal | None = Field(default=None, ge=1, le=5)
    min_cost: Decimal | None = Field(default=None, ge=0)
    max_cost: Decimal | None = Field(default=None, ge=0)

    @field_validator("city", mode="before")
    @classmethod
    def normalize_city(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def valid_ranges(self) -> "SearchRecordsInput":
        if self.min_rating is not None and self.max_rating is not None:
            if self.max_rating < self.min_rating:
                raise ValueError("Max rating must not be less than min rating")
        if self.min_cost is not None and self.max_cost is not None:
            if self.max_cost < self.min_cost:
                raise ValueError("Max cost must not be less than min cost")
        return self


class GetTripDetailInput(BaseModel):
    """旅行详情查询的输入。"""

    trip_id: int = Field(ge=1)


class _UserScopedTool:
    """限制在单个用户数据范围内执行的数据库工具基类。"""

    def __init__(self, db: Session, user_id: int) -> None:
        self._db = db
        self._user_id = user_id


def record_search_item(record: Record, city_name: str) -> RecordSearchItem:
    """将 ORM Record 转换为不依赖 ORM 的结果模型。"""
    return RecordSearchItem(
        record_id=record.id,
        trip_id=record.trip_id,
        city_name=city_name,
        category=record.type,
        name=record.name,
        date=record.date,
        rating=record.rating,
        cost=record.cost,
        notes=record.notes,
    )


class GetTravelSummaryTool(_UserScopedTool):
    """获取当前用户的旅行统计。"""

    name = "get_travel_summary"
    description = "只能获取旅行次数、城市数、总花费和平均评分，不返回去过的城市或景点列表"

    def run(self, **arguments: Any) -> ToolResult[TravelSummary]:
        if arguments:
            raise ValueError("get_travel_summary does not accept arguments")

        trip_count = self._db.scalar(
            select(func.count(Trip.id)).where(Trip.user_id == self._user_id)
        )
        city_count = self._db.scalar(
            select(func.count(func.distinct(Trip.city_code))).where(
                Trip.user_id == self._user_id
            )
        )
        total_spending = self._db.scalar(
            select(func.sum(Record.cost))
            .join(Trip)
            .where(Trip.user_id == self._user_id)
        )
        avg_rating = self._db.scalar(
            select(func.avg(Record.rating))
            .join(Trip)
            .where(Trip.user_id == self._user_id, Record.rating.is_not(None))
        )

        return ToolResult.completed(
            TravelSummary(
                trip_count=trip_count or 0,
                city_count=city_count or 0,
                total_spending=decimal_value(total_spending),
                avg_rating=(decimal_value(avg_rating) if avg_rating is not None else None),
            )
        )


class SearchTripHistoryTool(_UserScopedTool):
    """按城市和日期区间查询当前用户的历史旅行。"""

    name = "search_trip_history"
    description = "查询去过哪些城市及每次旅行时间段，支持城市和日期筛选"

    def run(self, **arguments: Any) -> ToolResult[list[TripInfo]]:
        query = SearchTripHistoryInput.model_validate(arguments)
        statement = (
            select(
                Trip.id,
                Trip.city_code,
                Trip.city_name,
                Trip.start_date,
                Trip.end_date,
                func.count(Record.id),
            )
            .outerjoin(Record)
            .where(Trip.user_id == self._user_id)
            .group_by(
                Trip.id,
                Trip.city_code,
                Trip.city_name,
                Trip.start_date,
                Trip.end_date,
            )
            .order_by(Trip.start_date.desc(), Trip.id.desc())
        )
        if query.city:
            statement = statement.where(Trip.city_name.ilike(f"%{query.city}%"))
        if query.start_date:
            statement = statement.where(Trip.end_date >= query.start_date)
        if query.end_date:
            statement = statement.where(Trip.start_date <= query.end_date)

        rows = self._db.execute(statement).all()
        return ToolResult.completed(
            [
                    TripInfo(
                        trip_id=trip_id,
                        city_code=city_code,
                        city_name=city_name,
                        start_date=start_date,
                        end_date=end_date,
                        record_count=record_count,
                )
                for trip_id, city_code, city_name, start_date, end_date, record_count in rows
            ]
        )


class SearchRecordsTool(_UserScopedTool):
    """按旅行、城市、类型、评分和花费查询当前用户的记录。"""

    name = "search_records"
    description = "查询去过的具体景点和美食记录，支持城市、类型、评分和花费筛选"

    def run(self, **arguments: Any) -> ToolResult[list[RecordSearchItem]]:
        query = SearchRecordsInput.model_validate(arguments)
        statement = (
            select(Record, Trip.city_name)
            .join(Trip)
            .where(Trip.user_id == self._user_id)
            .order_by(Record.date.desc(), Record.id.desc())
        )
        if query.trip_id is not None:
            statement = statement.where(Record.trip_id == query.trip_id)
        if query.city:
            statement = statement.where(Trip.city_name.ilike(f"%{query.city}%"))
        if query.category is not None:
            statement = statement.where(Record.type == query.category)
        if query.min_rating is not None:
            statement = statement.where(Record.rating >= query.min_rating)
        if query.max_rating is not None:
            statement = statement.where(Record.rating <= query.max_rating)
        if query.min_cost is not None:
            statement = statement.where(Record.cost >= query.min_cost)
        if query.max_cost is not None:
            statement = statement.where(Record.cost <= query.max_cost)

        rows = self._db.execute(statement).all()
        return ToolResult.completed(
            [record_search_item(record, city_name) for record, city_name in rows]
        )


class GetTripDetailTool(_UserScopedTool):
    """获取当前用户某次旅行及其全部记录。"""

    name = "get_trip_detail"
    description = "按旅行 ID 获取完整旅行详情"

    def run(self, **arguments: Any) -> ToolResult[TripInfo]:
        query = GetTripDetailInput.model_validate(arguments)
        trip = self._db.scalar(
            select(Trip)
            .where(Trip.id == query.trip_id, Trip.user_id == self._user_id)
            .options(selectinload(Trip.records))
        )
        if trip is None:
            return ToolResult.unavailable("Trip not found", error_code="trip_not_found")

        records = sorted(trip.records, key=lambda item: (item.date, item.id), reverse=True)
        return ToolResult.completed(
            TripInfo(
                trip_id=trip.id,
                city_code=trip.city_code,
                city_name=trip.city_name,
                start_date=trip.start_date,
                end_date=trip.end_date,
                record_count=len(records),
                records=[record_search_item(record, trip.city_name) for record in records],
            )
        )


def create_internal_db_tools(db: Session, user_id: int) -> tuple[_UserScopedTool, ...]:
    """创建绑定当前数据库会话和用户范围的内部工具。"""
    return (
        GetTravelSummaryTool(db, user_id),
        SearchTripHistoryTool(db, user_id),
        SearchRecordsTool(db, user_id),
        GetTripDetailTool(db, user_id),
    )
