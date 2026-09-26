"""LangGraph wiring for the Travel Agent V1 workflow."""

from __future__ import annotations

from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.budget import AgentTimeoutError
from app.agent.collector import ReActCollector
from app.agent.factual import FactualAnswerer
from app.agent.generator import StructuredItineraryGenerator, fallback_itinerary
from app.agent.llm import LLMError
from app.agent.normalizer import NormalizerError, normalize_poi
from app.agent.information import (
    all_information_terminal,
    initialize_information_status,
)
from app.agent.models import (
    CollectedInfo,
    InfoRequirement,
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
from app.agent.tools.budget import EstimateBudgetTool
from app.agent.tools.amap import AmapApiError, AmapWebClient
from app.agent.tools.layer import ToolUnavailableError


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
    factual_answerer: FactualAnswerer | None = None,
    planning_poi_client: AmapWebClient | None = None,
):
    """Build and compile the V1 graph from already-tested node dependencies."""
    if max_validation_rounds < 0:
        raise ValueError("max_validation_rounds must not be negative")

    builder = StateGraph(TravelAgentState)
    builder.add_node("requirement_analyzer", _analyzer_node(analyzer, observer))
    builder.add_node(
        "initialize_information",
        lambda state: _initialize_information_node(state, planning_poi_client),
    )
    builder.add_node("react_collector", _collector_node(collector))
    if factual_answerer is not None:
        builder.add_node("factual_answer", _factual_answer_node(factual_answerer, observer))
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
    if factual_answerer is None and planning_poi_client is None:
        builder.add_edge("initialize_information", "react_collector")
    else:
        initial_routes = {"collect": "react_collector"}
        if factual_answerer is not None:
            initial_routes["direct"] = "factual_answer"
        if planning_poi_client is not None:
            initial_routes["planning_ready"] = "intent_router"
            initial_routes["planning_unavailable"] = "final_response"
        builder.add_conditional_edges(
            "initialize_information",
            lambda state: _initial_route(
                state,
                factual_enabled=factual_answerer is not None,
                planning_enabled=planning_poi_client is not None,
            ),
            initial_routes,
        )
        if factual_answerer is not None:
            builder.add_edge("factual_answer", END)
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


def _factual_answer_node(
    answerer: FactualAnswerer,
    observer: AgentObserver | None,
):
    def run(state: TravelAgentState) -> dict[str, str]:
        started_at = monotonic()
        _emit_graph_event(
            observer, "stage_started", state,
            node_name="factual_answer", stage_name="factual_answer",
        )
        answer = answerer.answer(state["requirement"])
        elapsed = (monotonic() - started_at) * 1000
        _emit_graph_event(
            observer, "stage_completed", state,
            node_name="factual_answer", stage_name="factual_answer",
            stage_duration_ms=elapsed, stage_status="success",
        )
        _emit_graph_event(
            observer, "final_response_ready", state,
            node_name="factual_answer", stage_name="factual_answer",
            stage_duration_ms=elapsed, stage_status="success",
        )
        return {"final_response": answer}

    return run


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
    planning_poi_client: AmapWebClient | None = None,
) -> dict[str, Any]:
    requirement = state["requirement"]
    status = initialize_information_status(requirement)
    collected = CollectedInfo()
    if requirement.intent == "trip_planning" and requirement.duration_days is not None:
        collected.budget = EstimateBudgetTool().run(
            city=requirement.city,
            duration_days=requirement.duration_days,
            travelers=requirement.travelers or 1,
        ).data
        status.budget = InfoRequirement(status="completed", critical=False)
    if requirement.intent == "trip_planning" and planning_poi_client is not None:
        if not requirement.city:
            status.pois = InfoRequirement(
                status="unavailable", critical=True, reason="请先说明旅行城市"
            )
        else:
            seen_ids: set[str] = set()
            errors: list[str] = []
            for kind in ("attraction", "food"):
                try:
                    pois = normalize_poi(planning_poi_client.search_verified_pois(
                        city=requirement.city, kind=kind,
                    ))
                except (AmapApiError, ToolUnavailableError, NormalizerError, ValueError) as error:
                    errors.append(str(error))
                    continue
                for poi in pois:
                    if poi.poi_id not in seen_ids:
                        collected.pois.append(poi)
                        seen_ids.add(poi.poi_id)
            status.pois = InfoRequirement(
                status="completed" if collected.pois else "unavailable",
                critical=True,
                reason="；".join(errors) if errors else None,
            )
    return {
        "information_status": status,
        "collected_info": collected,
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
        except (LLMError, AgentTimeoutError, ValueError):
            itinerary = fallback_itinerary(
                state["requirement"], state["collected_info"],
            )
            _emit_graph_event(
                observer, "stage_completed", state,
                node_name="itinerary_generator", stage_name="itinerary_generator",
                stage_duration_ms=(monotonic() - stage_started_at) * 1000,
                stage_status="degraded",
            )
            return {"itinerary": itinerary, "validation": None}
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
    if all_information_terminal(state["information_status"]):
        return "information_complete"
    if (
        state.get("react_action") == "tool"
        and state["requirement"].intent == "trip_planning"
        and state["react_round"] < max_react_rounds
    ):
        return "information_incomplete"
    if state["react_round"] >= max_react_rounds:
        if (
            state["requirement"].intent == "trip_planning"
            and _critical_information_completed(state["information_status"])
        ):
            return "information_complete"
        return "information_exhausted"
    return "information_incomplete"


def _initial_route(
    state: TravelAgentState,
    *,
    factual_enabled: bool,
    planning_enabled: bool,
) -> str:
    intent = state["requirement"].intent
    if factual_enabled and intent in {"distance_query", "weather_query", "budget_query"}:
        return "direct"
    if planning_enabled and intent == "trip_planning":
        pois = state["information_status"].pois
        if pois is None or pois.status != "completed":
            return "planning_unavailable"
        if state["information_status"].history is None:
            return "planning_ready"
    return "collect"


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
    has_failures = any(
        issue.status == "fail" and issue.type != "budget"
        for issue in validation.issues
    )
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
