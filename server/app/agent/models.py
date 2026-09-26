from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.utils import time_to_minutes


TravelIntent = Literal[
    "trip_planning",
    "poi_recommendation",
    "distance_query",
    "route_query",
    "weather_query",
    "budget_query",
    "history_query",
    "general_query",
]
# 用户当前想让 Agent 完成的任务类型。

HistoryRecordCategory = Literal["ATTRACTION", "FOOD"]
# 历史记录查询的类型筛选：景点或美食。

InformationStatusValue = Literal[
    "pending",
    "completed",
    "unavailable",
    "failed",
]
# 某类信息的收集状态：待收集、已完成、不可用或失败。

RouteMode = Literal["walking", "driving", "transit", "cycling"]
# 路线查询支持的出行方式。

DistanceMode = Literal["straight", "driving", "walking"]
# 距离问答的测量方式；未指定时由服务端使用直线距离。

WeatherTimeKind = Literal["realtime", "forecast_date", "forecast_range", "ambiguous"]
# 天气问题按时间语义分类，避免依赖“现在”等字面关键词。

ItineraryPeriod = Literal[
    "morning",
    "afternoon",
    "evening",
    "breakfast",
    "lunch",
    "dinner",
]
# 粗粒度行程时段：三个游览时段和三餐。

ValidationIssueType = Literal[
    "opening_hours",
    "travel_time",
    "time_conflict",
    "daily_load",
    "constraint",
    "budget",
]
# 行程校验可能发现的问题类型。

ValidationIssueStatus = Literal["fail", "unknown"]
# 校验问题的确定性状态：明确失败或信息不足。


class TravelRequirement(BaseModel):
    """从用户请求中提取出的旅行需求，作为后续规划的输入。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: TravelIntent
    city: str | None = Field(default=None, description="旅行或查询涉及的城市")
    origin: str | None = Field(default=None, description="路线或旅行的出发地")
    destination: str | None = Field(default=None, description="路线或距离查询的终点")
    distance_mode: DistanceMode | None = None
    weather_time_kind: WeatherTimeKind | None = None
    history_category: HistoryRecordCategory | None = None
    date_expression: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_days: int | None = Field(default=None, ge=1)
    travelers: int | None = Field(default=None, ge=1)
    budget: float | None = Field(default=None, ge=0)
    preferences: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    @field_validator("city", "origin", "destination")
    @classmethod
    def normalize_place(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_requirement_date(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date must use YYYY-MM-DD")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("date must use a valid YYYY-MM-DD value") from error
        return value

    @model_validator(mode="after")
    def validate_requirement_semantics(self) -> "TravelRequirement":
        if self.intent not in {"route_query", "distance_query"} and self.destination is not None:
            raise ValueError("destination is only valid for route/distance queries; use city for a city")
        if self.intent != "distance_query" and self.distance_mode is not None:
            raise ValueError("distance_mode is only valid for distance_query")
        if self.intent != "weather_query" and self.weather_time_kind is not None:
            raise ValueError("weather_time_kind is only valid for weather_query")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class InfoRequirement(BaseModel):
    """记录一种信息需求的收集状态和尝试次数。"""

    status: InformationStatusValue = "pending"
    critical: bool = False
    attempts: int = Field(default=0, ge=0)
    reason: str | None = None


class InformationStatus(BaseModel):
    """跟踪历史、景点、天气、路线和预算等信息是否已经收集。"""

    history: InfoRequirement | None = None
    pois: InfoRequirement | None = None
    weather: InfoRequirement | None = None
    routes: InfoRequirement | None = None
    distances: InfoRequirement | None = None
    budget: InfoRequirement | None = None


class TravelHistoryInfo(BaseModel):
    """从用户历史记录中汇总出的旅行事实。"""

    trip_count: int = Field(default=0, ge=0)
    visited_cities: list[str] = Field(default_factory=list)
    visited_names: list[str] = Field(default_factory=list)
    visited_poi_ids: list[str] = Field(default_factory=list)


class POIInfo(BaseModel):
    """一个景点或其他可安排行程的地点信息。"""

    poi_id: str
    name: str
    address: str | None = None
    location: str
    category: str | None = None
    opening_hours: str | None = None


class WeatherInfo(BaseModel):
    """某个地点在指定日期的天气信息。"""

    location: str
    date: str
    description: str | None = None
    temperature_min: float | None = None
    temperature_max: float | None = None


class RouteInfo(BaseModel):
    """两个地点之间、按指定出行方式查询到的路线信息。"""

    origin_id: str
    destination_id: str
    mode: RouteMode
    distance_meters: int = Field(ge=0)
    duration_minutes: int = Field(ge=0)


class DistanceInfo(BaseModel):
    """两个地点之间的距离信息。"""

    origin_id: str
    destination_id: str
    distance_meters: int = Field(ge=0)


class BudgetInfo(BaseModel):
    """一次旅行的预算估算结果及其组成和假设。"""

    estimated_min: float = Field(ge=0)
    estimated_max: float = Field(ge=0)
    breakdown: dict[str, float] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class CollectedInfo(BaseModel):
    """Agent 已经收集到的结构化业务信息。"""

    history: TravelHistoryInfo | None = None
    pois: list[POIInfo] = Field(default_factory=list)
    weather: WeatherInfo | None = None
    routes: list[RouteInfo] = Field(default_factory=list)
    distances: list[DistanceInfo] = Field(default_factory=list)
    budget: BudgetInfo | None = None


class ItineraryItem(BaseModel):
    """一天行程中的一个景点或活动安排。"""

    model_config = ConfigDict(extra="forbid")

    poi_id: str
    poi_name: str
    period: ItineraryPeriod | None = None
    start_time: str | None = None
    end_time: str | None = None
    activity_type: str
    estimated_cost: float | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is not None:
            time_to_minutes(value)
        return value

    @model_validator(mode="after")
    def validate_schedule(self) -> "ItineraryItem":
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("start_time and end_time must be provided together")
        if self.period is not None and self.start_time is not None:
            raise ValueError("period and clock time cannot be combined")
        if self.period is not None and self.estimated_cost is not None:
            raise ValueError("estimated_cost is not supported for period items")
        if self.period is None and self.start_time is None:
            raise ValueError("period or clock times are required")
        return self


class ItineraryDay(BaseModel):
    """某一天的日期和当天安排的行程项。"""

    model_config = ConfigDict(extra="forbid")

    date: str | None = None
    day_number: int | None = Field(default=None, ge=1)
    items: list[ItineraryItem]

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date must use YYYY-MM-DD")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("date must use a valid YYYY-MM-DD value") from error
        return value

    @model_validator(mode="after")
    def validate_day_identity(self) -> "ItineraryDay":
        if self.date is None and self.day_number is None:
            raise ValueError("date or day_number is required")
        return self


class Itinerary(BaseModel):
    """Agent 生成的完整旅行计划。"""

    model_config = ConfigDict(extra="forbid")

    days: list[ItineraryDay]


class ValidationIssue(BaseModel):
    """行程校验发现的一条问题及其处理建议。"""

    type: ValidationIssueType
    status: ValidationIssueStatus
    day: int | None = None
    related_poi_ids: list[str] = Field(default_factory=list)
    message: str
    suggested_action: str | None = None


class ValidationResult(BaseModel):
    """对完整行程进行确定性校验后的结果。"""

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
