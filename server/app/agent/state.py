from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph.message import add_messages

from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
    TravelRequirement,
    ValidationResult,
)


class TravelAgentState(TypedDict):
    """Agent 工作流在各节点之间传递的完整状态。"""

    messages: Annotated[list[Any], add_messages]
    request_id: NotRequired[str]
    user_id: NotRequired[str | int | None]
    run_started_at: NotRequired[float]
    conversation_context: NotRequired[str]
    session_memory_state: NotRequired[dict[str, Any]]
    long_term_preferences: NotRequired[list[dict[str, str]]]
    requirement: TravelRequirement
    information_status: InformationStatus
    collected_info: CollectedInfo
    itinerary: Itinerary | None
    validation: ValidationResult | None
    react_round: int
    react_action: NotRequired[Literal["none", "tool", "no_tool"]]
    validation_round: int
    final_response: str | None
