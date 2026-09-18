from __future__ import annotations

from typing import Any, TypedDict

from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
    TravelRequirement,
    ValidationResult,
)


class TravelAgentState(TypedDict):
    """Agent 工作流在各节点之间传递的完整状态。"""

    # LangGraph's add_messages reducer will be applied when Graph wiring is added.
    messages: list[Any]
    requirement: TravelRequirement
    information_status: InformationStatus
    collected_info: CollectedInfo
    itinerary: Itinerary | None
    validation: ValidationResult | None
    react_round: int
    validation_round: int
    final_response: str | None
