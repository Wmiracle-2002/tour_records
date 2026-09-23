"""Provider-agnostic ReAct information collection loop."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from collections.abc import Callable, Mapping, Sequence
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agent.budget import AgentBudget
from app.agent.information import (
    MAX_INFO_ATTEMPTS,
    InformationNeedName,
    all_information_terminal,
    ensure_information_need,
    update_information_status,
)
from app.agent.models import (
    BudgetInfo,
    CollectedInfo,
    DistanceInfo,
    POIInfo,
    RouteInfo,
    TravelHistoryInfo,
    TravelRequirement,
    WeatherInfo,
    InformationStatus,
)
from app.agent.observability import (
    AgentObserver,
    emit_event,
    information_status_snapshot,
)
from app.agent.normalizer import (
    is_empty_result,
    normalize_budget,
    normalize_distance,
    normalize_history,
    normalize_poi,
    normalize_records,
    normalize_route,
    normalize_tool_result,
    normalize_weather,
)
from app.agent.state import TravelAgentState
from app.agent.tools.layer import ToolLayer, ToolResult


# Keep the synchronous collector within the mobile request budget.  A planning
# request can still add more information needs during these rounds, but it
# must stop before spending an unbounded number of LLM calls.
MAX_REACT_ROUNDS = 4


class ToolDescriptor(BaseModel):
    """提供给决策客户端的工具名称和简短说明。"""

    name: str
    description: str


class ToolCall(BaseModel):
    """一次结构化工具调用。"""

    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    information_need: InformationNeedName | None = None
    critical: bool = False


class ReActDecision(BaseModel):
    """决策客户端的单轮结果；没有 Tool Call 表示暂时停止调用。"""

    tool_call: ToolCall | None = None
    reason: str | None = None


class ReActContext(BaseModel):
    """每一轮传给决策客户端的最小结构化上下文。"""

    requirement: TravelRequirement
    information_status: InformationStatus
    collected_info: CollectedInfo
    available_tools: list[ToolDescriptor]
    react_round: int = Field(ge=0)


class ReActDecisionClient(Protocol):
    """具体 LLM 或规则客户端需要实现的决策接口。"""

    def decide(self, context: ReActContext) -> ReActDecision | None:
        ...


Normalizer = Callable[[Any], Any]

TOOL_INFORMATION_NEEDS: dict[str, InformationNeedName] = {
    "get_travel_summary": "history",
    "search_trip_history": "history",
    "search_records": "history",
    "get_trip_detail": "history",
    "estimate_budget": "budget",
    "keyword_search": "pois",
    "around_search": "pois",
    "poi_detail": "pois",
    "weather": "weather",
    "distance": "distances",
    "driving_route": "routes",
    "transit_route": "routes",
    "walking_route": "routes",
    "cycling_route": "routes",
}

_TOOL_ARGUMENT_ALIASES: dict[str, dict[str, str]] = {
    "keyword_search": {"keyword": "keywords", "query": "keywords"},
    "around_search": {"keyword": "keywords", "query": "keywords"},
}


def _normalize_tool_arguments(
    call: ToolCall,
    requirement: TravelRequirement,
) -> dict[str, Any]:
    """Normalize common LLM argument aliases before calling a concrete Tool."""
    arguments = dict(call.arguments)
    for alias, canonical in _TOOL_ARGUMENT_ALIASES.get(call.name, {}).items():
        if canonical not in arguments and alias in arguments:
            arguments[canonical] = arguments.pop(alias)

    if call.name in {"search_trip_history", "search_records"}:
        if "city" not in arguments and requirement.destination:
            arguments["city"] = requirement.destination
        if "category" not in arguments and requirement.history_category:
            arguments["category"] = requirement.history_category

    if call.name == "weather":
        if "city" not in arguments and requirement.destination:
            arguments["city"] = requirement.destination
        if requirement.start_date or requirement.end_date or requirement.date_expression:
            arguments["forecast"] = True

    if call.name in {
        "driving_route",
        "transit_route",
        "walking_route",
        "cycling_route",
    }:
        if "origin" not in arguments and requirement.origin:
            arguments["origin"] = requirement.origin
        if "destination" not in arguments and requirement.destination:
            arguments["destination"] = requirement.destination

    if call.name == "distance":
        if "origins" not in arguments and requirement.origin:
            arguments["origins"] = [requirement.origin]
        if "destination" not in arguments and requirement.destination:
            arguments["destination"] = requirement.destination

    return arguments


class ReActCollector:
    """执行有限轮次的 Tool Calling，并把结果写入结构化 State。"""

    def __init__(
        self,
        tool_layer: ToolLayer,
        decision_client: ReActDecisionClient,
        *,
        max_rounds: int = MAX_REACT_ROUNDS,
        normalizers: Mapping[str, Normalizer] | None = None,
        observer: AgentObserver | None = None,
        budget: AgentBudget | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        self._tool_layer = tool_layer
        self._decision_client = decision_client
        self._max_rounds = max_rounds
        self._normalizers = dict(normalizers or {})
        self._observer = observer
        self._budget = budget

    @property
    def max_rounds(self) -> int:
        """Return the maximum number of ReAct rounds for Graph routing."""
        return self._max_rounds

    def collect(self, state: TravelAgentState) -> TravelAgentState:
        """从当前 State 开始收集信息，达到终止条件或轮次上限后返回。"""
        working = deepcopy(state)
        while working["react_round"] < self._max_rounds:
            previous_round = working["react_round"]
            working = self.collect_round(working)
            if working["react_round"] == previous_round:
                break
            if all_information_terminal(working["information_status"]):
                break
        return working

    def collect_round(self, state: TravelAgentState) -> TravelAgentState:
        """Execute exactly one ReAct decision and optional Tool call."""
        working = deepcopy(state)
        if (
            working["react_round"] >= self._max_rounds
            or (
                all_information_terminal(working["information_status"])
                and not _can_discover_more_information(working)
            )
        ):
            return working

        context = self._build_context(working)
        decision_started_at = monotonic()
        decision_round = working["react_round"] + 1
        self._emit(
            "stage_started",
            working,
            stage_name="react_decision",
            react_round=decision_round,
        )
        try:
            with (
                self._budget.stage("react_decision")
                if self._budget
                else nullcontext()
            ):
                decision = self._decision_client.decide(context)
        except Exception:
            self._emit(
                "stage_completed",
                working,
                stage_name="react_decision",
                stage_duration_ms=(monotonic() - decision_started_at) * 1000,
                stage_status="failed",
                react_round=decision_round,
            )
            raise
        self._emit(
            "stage_completed",
            working,
            stage_name="react_decision",
            stage_duration_ms=(monotonic() - decision_started_at) * 1000,
            stage_status="success",
            react_round=decision_round,
        )
        working["react_round"] += 1
        working["react_action"] = "no_tool"

        if decision is None or decision.tool_call is None:
            return working

        call = decision.tool_call
        need = call.information_need or TOOL_INFORMATION_NEEDS.get(call.name)
        if need is None:
            return working

        working["information_status"] = ensure_information_need(
            working["information_status"],
            need,
            critical=call.critical,
        )
        current_requirement = getattr(working["information_status"], need)
        if current_requirement.status != "pending":
            return working
        if current_requirement.attempts >= MAX_INFO_ATTEMPTS:
            return working

        working["react_action"] = "tool"
        tool_started_at = monotonic()
        self._emit(
            "tool_started",
            working,
            tool_name=call.name,
            react_round=working["react_round"],
        )
        with (
            self._budget.stage("react_tool")
            if self._budget
            else nullcontext()
        ):
            raw_result = self._tool_layer.execute(
                call.name,
                **_normalize_tool_arguments(call, working["requirement"]),
            )
            normalized_result = self._normalize(call, raw_result)
        self._emit(
            "tool_completed",
            working,
            tool_name=call.name,
            tool_duration_ms=(monotonic() - tool_started_at) * 1000,
            tool_success=normalized_result.status == "completed",
            react_round=working["react_round"],
            error_code=normalized_result.error_code,
            error_message=(
                normalized_result.message
                if normalized_result.status != "completed"
                else None
            ),
        )
        normalized_empty = normalized_result.status == "completed" and is_empty_result(
            normalized_result.data
        )

        if normalized_empty:
            working["information_status"] = update_information_status(
                working["information_status"],
                need,
                outcome="empty",
                reason="Tool returned no data",
            )
        elif normalized_result.status == "completed":
            collected_data = normalized_result.data
            weather_reason = None
            if need == "weather":
                collected_data, weather_reason = _weather_for_requirement(
                    collected_data,
                    working["requirement"],
                )
            if weather_reason is not None:
                working["information_status"] = update_information_status(
                    working["information_status"],
                    need,
                    outcome="unavailable",
                    reason=weather_reason,
                )
            else:
                try:
                    working["collected_info"] = self._apply_collected_info(
                        working["collected_info"], need, collected_data
                    )
                except Exception:
                    normalized_result = ToolResult.failed(
                        "Normalized tool data has an invalid shape",
                        error_code="invalid_normalized_data",
                    )
                    working["information_status"] = update_information_status(
                        working["information_status"],
                        need,
                        outcome="error",
                        reason=normalized_result.message,
                    )
                else:
                    working["information_status"] = update_information_status(
                        working["information_status"], need, outcome="completed"
                    )
        elif normalized_result.status == "unavailable":
            working["information_status"] = update_information_status(
                working["information_status"],
                need,
                outcome="unavailable",
                reason=normalized_result.message,
            )
        else:
            working["information_status"] = update_information_status(
                working["information_status"],
                need,
                outcome="error",
                reason=normalized_result.message,
            )
        self._emit(
            "information_updated",
            working,
            tool_name=call.name,
            information_status=information_status_snapshot(
                working["information_status"]
            ),
            react_round=working["react_round"],
        )
        return working

    def _emit(
        self,
        event,
        state: TravelAgentState,
        **fields: Any,
    ) -> None:
        emit_event(
            self._observer,
            event=event,
            request_id=state.get("request_id", "unknown"),
            user_id=state.get("user_id"),
            intent=state["requirement"].intent,
            node_name="react_collector",
            **fields,
        )

    def _build_context(self, state: TravelAgentState) -> ReActContext:
        return ReActContext(
            requirement=state["requirement"],
            information_status=state["information_status"],
            collected_info=state["collected_info"],
            available_tools=[
                ToolDescriptor(name=name, description=description)
                for name, description in self._tool_layer.descriptions()
                if _tool_can_be_requested(name, state["information_status"])
            ],
            react_round=state["react_round"],
        )

    def _normalize(self, call: ToolCall, result: ToolResult[Any]) -> ToolResult[Any]:
        normalizer = self._normalizers.get(call.name) or self._default_normalizer(call)
        if normalizer is None:
            return ToolResult.failed(
                "No normalizer configured for tool", error_code="normalizer_not_configured"
            )
        return normalize_tool_result(result, normalizer)

    def _default_normalizer(self, call: ToolCall) -> Normalizer | None:
        if call.name in {"keyword_search", "around_search", "poi_detail"}:
            return normalize_poi
        if call.name == "weather":
            return normalize_weather
        if call.name in {
            "get_travel_summary",
            "search_trip_history",
            "get_trip_detail",
        }:
            return normalize_history
        if call.name == "search_records":
            return normalize_records
        if call.name == "estimate_budget":
            return normalize_budget
        if call.name == "distance":
            origins = call.arguments.get("origins") or []
            origin_id = origins[0] if isinstance(origins, Sequence) and not isinstance(origins, str) else origins
            return lambda raw: normalize_distance(
                raw,
                origin_id=str(origin_id or ""),
                destination_id=str(call.arguments.get("destination") or ""),
            )
        route_modes = {
            "driving_route": "driving",
            "transit_route": "transit",
            "walking_route": "walking",
            "cycling_route": "cycling",
        }
        if call.name in route_modes:
            return lambda raw: normalize_route(
                raw,
                mode=route_modes[call.name],
                origin_id=str(call.arguments.get("origin") or ""),
                destination_id=str(call.arguments.get("destination") or ""),
            )
        return None

    def _apply_collected_info(
        self,
        collected: CollectedInfo,
        need: InformationNeedName,
        data: Any,
    ) -> CollectedInfo:
        updated = collected.model_copy(deep=True)
        if need == "history":
            if not isinstance(data, TravelHistoryInfo):
                raise TypeError("history normalizer must return TravelHistoryInfo")
            updated.history = data
        elif need == "pois":
            if not isinstance(data, list) or not all(isinstance(item, POIInfo) for item in data):
                raise TypeError("POI normalizer must return POIInfo list")
            known = {item.poi_id for item in updated.pois}
            updated.pois.extend(item for item in data if item.poi_id not in known)
        elif need == "weather":
            if not isinstance(data, list) or not all(isinstance(item, WeatherInfo) for item in data):
                raise TypeError("weather normalizer must return WeatherInfo list")
            updated.weather = data[0] if data else None
        elif need == "routes":
            if not isinstance(data, RouteInfo):
                raise TypeError("route normalizer must return RouteInfo")
            if data not in updated.routes:
                updated.routes.append(data)
        elif need == "distances":
            if not isinstance(data, DistanceInfo):
                raise TypeError("distance normalizer must return DistanceInfo")
            if data not in updated.distances:
                updated.distances.append(data)
        elif need == "budget":
            if not isinstance(data, BudgetInfo):
                raise TypeError("budget normalizer must return BudgetInfo")
            updated.budget = data
        return updated


def _can_discover_more_information(state: TravelAgentState) -> bool:
    """行程规划允许在当前信息完成后继续发现路线、预算等需求。"""
    return state["requirement"].intent == "trip_planning"


def _weather_for_requirement(
    data: Any,
    requirement: TravelRequirement,
) -> tuple[Any, str | None]:
    if not isinstance(data, list) or not all(
        isinstance(item, WeatherInfo) for item in data
    ):
        return data, None
    if requirement.start_date:
        matches = [item for item in data if item.date == requirement.start_date]
        if matches:
            return matches, None
        return [], f"天气预报范围不包含请求日期 {requirement.start_date}"
    if requirement.date_expression:
        return [], f"无法将日期“{requirement.date_expression}”解析为具体公历日期"
    return data, None


def _tool_can_be_requested(name: str, status: InformationStatus) -> bool:
    """Do not advertise Tools whose information need has already terminated."""
    need = TOOL_INFORMATION_NEEDS.get(name)
    if need is None:
        return True
    requirement = getattr(status, need)
    return requirement is None or requirement.status == "pending"
