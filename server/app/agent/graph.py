"""LangGraph wiring for the Travel Agent V1 workflow."""

from __future__ import annotations

from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.collector import ReActCollector
from app.agent.generator import StructuredItineraryGenerator
from app.agent.information import (
    all_information_terminal,
    initialize_information_status,
)
from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
    TravelRequirement,
    ValidationResult,
)
from app.agent.observability import AgentObserver, emit_event
from app.agent.reviser import ItineraryReviser, MAX_VALIDATION_ROUNDS
from app.agent.response import FinalResponseGenerator
from app.agent.state import TravelAgentState
from app.agent.validator import ItineraryValidator
from app.agent.analyzer import RequirementAnalyzer


CollectionRoute = Literal[
    "information_complete",
    "information_incomplete",
    "information_exhausted",
]
IntentRoute = Literal["trip_planning", "other"]
ValidationRoute = Literal["validation_fail", "validation_finish"]


def make_initial_state(
    user_query: str,
    *,
    request_id: str | None = None,
    user_id: str | int | None = None,
) -> TravelAgentState:
    """Create the complete state accepted by the compiled graph."""
    return {
        "messages": [{"role": "user", "content": user_query}],
        "request_id": request_id or str(uuid4()),
        "user_id": user_id,
        "run_started_at": monotonic(),
        "requirement": TravelRequirement(intent="general_query"),
        "information_status": InformationStatus(),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "react_action": "none",
        "validation_round": 0,
        "final_response": None,
    }


def build_agent_graph(
    *,
    analyzer: RequirementAnalyzer,
    collector: ReActCollector,
    itinerary_generator: StructuredItineraryGenerator,
    validator: ItineraryValidator,
    reviser: ItineraryReviser,
    response_generator: FinalResponseGenerator,
    max_validation_rounds: int = MAX_VALIDATION_ROUNDS,
    observer: AgentObserver | None = None,
):
    """Build and compile the V1 graph from already-tested node dependencies."""
    if max_validation_rounds < 0:
        raise ValueError("max_validation_rounds must not be negative")

    builder = StateGraph(TravelAgentState)
    builder.add_node("requirement_analyzer", _analyzer_node(analyzer, observer))
    builder.add_node("initialize_information", _initialize_information_node)
    builder.add_node("react_collector", _collector_node(collector))
    builder.add_node("intent_router", _empty_node)
    builder.add_node(
        "itinerary_generator",
        _itinerary_generator_node(itinerary_generator, observer),
    )
    builder.add_node("validator", _validator_node(validator, observer))
    builder.add_node(
        "reviser",
        _reviser_node(reviser, observer),
    )
    builder.add_node(
        "final_response",
        _final_response_node(response_generator, observer),
    )

    builder.add_edge(START, "requirement_analyzer")
    builder.add_edge("requirement_analyzer", "initialize_information")
    builder.add_edge("initialize_information", "react_collector")
    builder.add_conditional_edges(
        "react_collector",
        lambda state: _collection_route(state, collector.max_rounds),
        {
            "information_complete": "intent_router",
            "information_incomplete": "react_collector",
            "information_exhausted": "final_response",
        },
    )
    builder.add_conditional_edges(
        "intent_router",
        _intent_route,
        {
            "trip_planning": "itinerary_generator",
            "other": "final_response",
        },
    )
    builder.add_edge("itinerary_generator", "validator")
    builder.add_conditional_edges(
        "validator",
        lambda state: _validation_route(state, max_validation_rounds),
        {
            "validation_fail": "reviser",
            "validation_finish": "final_response",
        },
    )
    builder.add_edge("reviser", "validator")
    builder.add_edge("final_response", END)
    return builder.compile()


def _analyzer_node(
    analyzer: RequirementAnalyzer,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, TravelRequirement]:
        stage_started_at = monotonic()
        _emit_graph_event(
            observer,
            "stage_started",
            state,
            node_name="requirement_analyzer",
            stage_name="requirement_analyzer",
        )
        try:
            requirement = analyzer.analyze(_user_query(state["messages"]))
        except Exception:
            _emit_graph_event(
                observer,
                "stage_completed",
                state,
                node_name="requirement_analyzer",
                stage_name="requirement_analyzer",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="failed",
            )
            raise
        stage_duration_ms = (monotonic() - stage_started_at) * 1000
        _emit_graph_event(
            observer,
            "stage_completed",
            state,
            node_name="requirement_analyzer",
            stage_name="requirement_analyzer",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        _emit_graph_event(
            observer,
            "requirement_ready",
            state,
            node_name="requirement_analyzer",
            intent=requirement.intent,
            stage_name="requirement_analyzer",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        return {"requirement": requirement}

    return run


def _initialize_information_node(
    state: TravelAgentState,
) -> dict[str, Any]:
    return {
        "information_status": initialize_information_status(state["requirement"]),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "react_action": "none",
        "validation_round": 0,
        "final_response": None,
    }


def _collector_node(collector: ReActCollector):
    def run(state: TravelAgentState) -> dict[str, Any]:
        updated = collector.collect_round(state)
        return {
            "information_status": updated["information_status"],
            "collected_info": updated["collected_info"],
            "react_round": updated["react_round"],
            "react_action": updated.get("react_action", "none"),
        }

    return run


def _itinerary_generator_node(
    generator: StructuredItineraryGenerator,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, Itinerary | None]:
        stage_started_at = monotonic()
        _emit_graph_event(
            observer,
            "stage_started",
            state,
            node_name="itinerary_generator",
            stage_name="itinerary_generator",
        )
        try:
            itinerary = generator.generate(
                state["requirement"],
                state["collected_info"],
            )
        except Exception:
            _emit_graph_event(
                observer,
                "stage_completed",
                state,
                node_name="itinerary_generator",
                stage_name="itinerary_generator",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="failed",
            )
            raise
        stage_duration_ms = (monotonic() - stage_started_at) * 1000
        _emit_graph_event(
            observer,
            "stage_completed",
            state,
            node_name="itinerary_generator",
            stage_name="itinerary_generator",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        _emit_graph_event(
            observer,
            "itinerary_generated",
            state,
            node_name="itinerary_generator",
            stage_name="itinerary_generator",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        return {"itinerary": itinerary, "validation": None}

    return run


def _validator_node(
    validator: ItineraryValidator,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, ValidationResult]:
        itinerary = state["itinerary"]
        if itinerary is None:
            raise ValueError("Validator requires an itinerary")
        stage_started_at = monotonic()
        _emit_graph_event(
            observer,
            "stage_started",
            state,
            node_name="validator",
            stage_name="validator",
        )
        _emit_graph_event(
            observer,
            "validation_started",
            state,
            node_name="validator",
            validation_round=state["validation_round"],
        )
        try:
            validation = validator.validate(
                state["requirement"],
                itinerary,
                state["collected_info"],
            )
        except Exception:
            _emit_graph_event(
                observer,
                "stage_completed",
                state,
                node_name="validator",
                stage_name="validator",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="failed",
            )
            raise
        failures = [issue for issue in validation.issues if issue.status == "fail"]
        stage_duration_ms = (monotonic() - stage_started_at) * 1000
        _emit_graph_event(
            observer,
            "stage_completed",
            state,
            node_name="validator",
            stage_name="validator",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        _emit_graph_event(
            observer,
            "validation_failed" if failures else "validation_completed",
            state,
            node_name="validator",
            validation_round=state["validation_round"],
            validation_issue_type=failures[0].type if failures else None,
            stage_name="validator",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        return {"validation": validation}

    return run


def _reviser_node(
    reviser: ItineraryReviser,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, Any]:
        itinerary = state["itinerary"]
        validation = state["validation"]
        if itinerary is None or validation is None:
            raise ValueError("Reviser requires an itinerary and validation result")
        stage_started_at = monotonic()
        _emit_graph_event(
            observer,
            "stage_started",
            state,
            node_name="reviser",
            stage_name="reviser",
            validation_round=state["validation_round"],
        )
        try:
            revised = reviser.revise(
                itinerary,
                validation.issues,
                state["requirement"],
                state["collected_info"],
            )
        except Exception:
            _emit_graph_event(
                observer,
                "stage_completed",
                state,
                node_name="reviser",
                stage_name="reviser",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="failed",
                validation_round=state["validation_round"],
            )
            raise
        stage_duration_ms = (monotonic() - stage_started_at) * 1000
        next_round = state["validation_round"] + 1
        _emit_graph_event(
            observer,
            "stage_completed",
            state,
            node_name="reviser",
            stage_name="reviser",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
            validation_round=next_round,
        )
        _emit_graph_event(
            observer,
            "itinerary_revised",
            state,
            node_name="reviser",
            validation_round=next_round,
            stage_name="reviser",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        return {"itinerary": revised, "validation_round": next_round}

    return run


def _final_response_node(
    response_generator: FinalResponseGenerator,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, str]:
        stage_started_at = monotonic()
        _emit_graph_event(
            observer,
            "stage_started",
            state,
            node_name="final_response",
            stage_name="final_response",
        )
        try:
            response = response_generator.generate(
                state["requirement"],
                state["collected_info"],
                state["information_status"],
                state["itinerary"],
                state["validation"],
            )
        except Exception:
            _emit_graph_event(
                observer,
                "stage_completed",
                state,
                node_name="final_response",
                stage_name="final_response",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="failed",
            )
            raise
        stage_duration_ms = (monotonic() - stage_started_at) * 1000
        _emit_graph_event(
            observer,
            "stage_completed",
            state,
            node_name="final_response",
            stage_name="final_response",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
        )
        started_at = state.get("run_started_at")
        total_duration_ms = (
            (monotonic() - started_at) * 1000
            if isinstance(started_at, (int, float))
            else None
        )
        _emit_graph_event(
            observer,
            "final_response_ready",
            state,
            node_name="final_response",
            stage_name="final_response",
            stage_duration_ms=stage_duration_ms,
            stage_status="success",
            total_duration_ms=total_duration_ms,
        )
        return {"final_response": response}

    return run


def _collection_route(
    state: TravelAgentState,
    max_react_rounds: int,
) -> CollectionRoute:
    if (
        state.get("react_action") == "tool"
        and state["requirement"].intent == "trip_planning"
        and state["react_round"] < max_react_rounds
    ):
        return "information_incomplete"
    if all_information_terminal(state["information_status"]):
        return "information_complete"
    if state["react_round"] >= max_react_rounds:
        if (
            state["requirement"].intent == "trip_planning"
            and _critical_information_completed(state["information_status"])
        ):
            return "information_complete"
        return "information_exhausted"
    return "information_incomplete"


def _critical_information_completed(status: InformationStatus) -> bool:
    critical = [
        requirement
        for name in InformationStatus.model_fields
        for requirement in (getattr(status, name),)
        if requirement is not None and requirement.critical
    ]
    return bool(critical) and all(
        requirement.status == "completed" for requirement in critical
    )


def _intent_route(state: TravelAgentState) -> IntentRoute:
    if state["requirement"].intent == "trip_planning":
        return "trip_planning"
    return "other"


def _validation_route(
    state: TravelAgentState,
    max_validation_rounds: int,
) -> ValidationRoute:
    validation = state["validation"]
    if validation is None:
        raise ValueError("Validation route requires a validation result")
    has_failures = any(issue.status == "fail" for issue in validation.issues)
    if has_failures and state["validation_round"] < max_validation_rounds:
        return "validation_fail"
    return "validation_finish"


def _empty_node(state: TravelAgentState) -> dict[str, Any]:
    return {}


def _emit_graph_event(
    observer: AgentObserver | None,
    event,
    state: TravelAgentState,
    **fields: Any,
) -> None:
    emit_event(
        observer,
        event=event,
        request_id=state.get("request_id", "unknown"),
        user_id=state.get("user_id"),
        intent=fields.pop("intent", state["requirement"].intent),
        **fields,
    )


def _user_query(messages: list[Any]) -> str:
    if not messages:
        raise ValueError("Graph requires a user message")
    message = messages[-1]
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    raise ValueError("Graph user message must contain text content")
