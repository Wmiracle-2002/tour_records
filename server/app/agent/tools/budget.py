"""Deterministic demo budget estimation tool."""

from __future__ import annotations

from math import ceil
from typing import Any, Literal

from pydantic import Field, field_validator

from app.agent.models import BudgetInfo
from app.agent.tools.layer import ToolInputModel, ToolResult


AccommodationLevel = Literal["budget", "standard", "premium"]
FoodLevel = Literal["budget", "standard", "premium"]
BudgetTransportMode = Literal["walking", "transit", "driving", "cycling", "mixed"]

ACCOMMODATION_PER_ROOM_NIGHT = {
    "budget": 180.0,
    "standard": 350.0,
    "premium": 700.0,
}
FOOD_PER_PERSON_DAY = {
    "budget": 80.0,
    "standard": 150.0,
    "premium": 300.0,
}
TRANSPORT_PER_PERSON_DAY = {
    "walking": 15.0,
    "transit": 40.0,
    "driving": 100.0,
    "cycling": 20.0,
    "mixed": 60.0,
}
POI_TICKET_PER_PERSON = 50.0


class EstimateBudgetInput(ToolInputModel):
    """预算估算的输入参数。"""

    city: str | None = Field(default=None, description="旅行目的城市")
    duration_days: int = Field(ge=1, description="旅行天数")
    travelers: int = Field(ge=1, description="出行人数")
    accommodation_level: AccommodationLevel = Field(
        default="standard", description="住宿档次：budget、standard、premium"
    )
    food_level: FoodLevel = Field(
        default="standard", description="餐饮档次：budget、standard、premium"
    )
    transport_mode: BudgetTransportMode = Field(
        default="mixed", description="交通方式"
    )
    pois: list[str] = Field(default_factory=list, description="计划游览的景点名称")

    @field_validator("city")
    @classmethod
    def normalize_city(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("pois")
    @classmethod
    def validate_pois(cls, value: list[str]) -> list[str]:
        cleaned = [poi.strip() for poi in value]
        if any(not poi for poi in cleaned):
            raise ValueError("POI names must not be blank")
        return cleaned


class EstimateBudgetTool:
    """按固定 Demo 参数估算人民币预算范围。"""

    name = "estimate_budget"
    description = "按旅行天数、人数和消费档次估算人民币预算"
    input_model = EstimateBudgetInput
    information_need = "budget"
    examples = (
        {"city": "南京", "duration_days": 3, "travelers": 2},
    )

    def run(self, **arguments: Any) -> ToolResult[BudgetInfo]:
        query = EstimateBudgetInput.model_validate(arguments)
        nights = max(query.duration_days - 1, 0)
        rooms = ceil(query.travelers / 2)

        accommodation = (
            rooms * nights * ACCOMMODATION_PER_ROOM_NIGHT[query.accommodation_level]
        )
        food = query.travelers * query.duration_days * FOOD_PER_PERSON_DAY[query.food_level]
        transport = (
            query.travelers
            * query.duration_days
            * TRANSPORT_PER_PERSON_DAY[query.transport_mode]
        )
        poi_tickets = len(query.pois) * query.travelers * POI_TICKET_PER_PERSON
        breakdown = {
            "accommodation": round(accommodation, 2),
            "food": round(food, 2),
            "transport": round(transport, 2),
            "poi_tickets": round(poi_tickets, 2),
        }
        base_amount = sum(breakdown.values())

        assumptions = [
            "金额单位为人民币元",
            "这是通用预算估算范围，不是实时精确价格",
            f"住宿按 {query.accommodation_level} 档、每间房最多两人、{nights} 晚估算",
            f"餐饮按 {query.food_level} 档、{query.travelers} 人、{query.duration_days} 天估算",
            f"交通按 {query.transport_mode} 方式估算",
        ]
        if query.city:
            assumptions.append(
                f"未接入 {query.city} 的实时价格，使用通用估算参数"
            )
        else:
            assumptions.append("未指定目的地，使用通用估算参数")
        if query.pois:
            assumptions.append("景点门票按每人每个景点 50 元估算")
        else:
            assumptions.append("未提供景点列表，未计入门票费用")

        return ToolResult.completed(
            BudgetInfo(
                estimated_min=round(base_amount * 0.8, 2),
                estimated_max=round(base_amount * 1.2, 2),
                breakdown=breakdown,
                assumptions=assumptions,
            )
        )


def create_budget_tools() -> tuple[EstimateBudgetTool, ...]:
    """创建预算工具。"""
    return (EstimateBudgetTool(),)
