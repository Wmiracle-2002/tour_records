from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent.utils import time_to_minutes


TravelIntent = Literal[
    "trip_planning",
    "poi_recommendation",
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

    intent: TravelIntent
    origin: str | None = None
    destination: str | None = None
    history_category: HistoryRecordCategory | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration_days: int | None = Field(default=None, ge=1)
    travelers: int | None = Field(default=None, ge=1)
    budget: float | None = Field(default=None, ge=0)
    preferences: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

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

    poi_id: str
    poi_name: str
    start_time: str
    end_time: str
    activity_type: str
    estimated_cost: float | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        time_to_minutes(value)
        return value


class ItineraryDay(BaseModel):
    """某一天的日期和当天安排的行程项。"""

    date: str
    items: list[ItineraryItem]

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date must use YYYY-MM-DD")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("date must use a valid YYYY-MM-DD value") from error
        return value


class Itinerary(BaseModel):
    """Agent 生成的完整旅行计划。"""

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
