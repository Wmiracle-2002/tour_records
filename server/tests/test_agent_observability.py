from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any

from app.agent.collector import ReActCollector, ReActDecision, ToolCall
from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.information import initialize_information_status
from app.agent.models import (
    CollectedInfo,
    InfoRequirement,
    InformationStatus,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    TravelRequirement,
    ValidationResult,
)
from app.agent.observability import (
    AgentEvent,
    RecordingAgentObserver,
    StructuredLoggingObserver,
    current_request_id,
    request_context,
)
from app.agent.response import FinalResponseGenerator
from app.agent.tools.layer import ToolLayer, ToolRegistry, ToolResult


class WeatherTool:
    name = "weather"
    description = "查询天气"

    def run(self, **_arguments: Any) -> ToolResult[dict[str, Any]]:
        return ToolResult.completed(
            {
                "status": "1",
                "lives": [
                    {
                        "city": "南京市",
                        "weather": "晴",
                        "reporttime": "2026-09-19 10:00:00",
                    }
                ],
            }
        )


class OneDecisionClient:
    def decide(self, _context):
        return ReActDecision(
            tool_call=ToolCall(
                name="weather",
                arguments={"city": "南京", "prompt": "不要记录这个参数"},
            )
        )


class FakeAnalyzer:
    def __init__(self, requirement: TravelRequirement) -> None:
        self.requirement = requirement

    def analyze(self, _user_query: str) -> TravelRequirement:
        return self.requirement


class FakeCollector:
    max_rounds = 1

    def __init__(self, collected_info: CollectedInfo) -> None:
        self.collected_info = collected_info

    def collect_round(self, state):
        updated = dict(state)
        updated["information_status"] = InformationStatus(
            pois=InfoRequirement(status="completed")
        )
        updated["collected_info"] = self.collected_info
        updated["react_round"] += 1
        updated["react_action"] = "no_tool"
        return updated


class FakeGenerator:
    def __init__(self, itinerary: Itinerary) -> None:
        self.itinerary = itinerary

    def generate(self, _requirement, _collected_info) -> Itinerary:
        return self.itinerary


class FakeValidator:
    def validate(self, _requirement, _itinerary, _collected_info) -> ValidationResult:
        return ValidationResult(valid=True)


class FakeReviser:
    def revise(self, itinerary, _issues, _requirement, _collected_info) -> Itinerary:
        return itinerary


def _simple_itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="P1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="11:00",
                        activity_type="游览",
                    )
                ],
            )
        ]
    )


def test_initial_state_contains_request_identity_and_start_time() -> None:
    first = make_initial_state("天气怎么样？")
    second = make_initial_state("天气怎么样？")

    assert first["request_id"]
    assert first["request_id"] != second["request_id"]
    assert first["run_started_at"] > 0


def test_request_context_exposes_and_restores_request_id() -> None:
    assert current_request_id() is None

    with request_context("req-context-1"):
        assert current_request_id() == "req-context-1"

    assert current_request_id() is None


def test_collector_records_tool_lifecycle_without_raw_payload() -> None:
    observer = RecordingAgentObserver()
    requirement = TravelRequirement(intent="weather_query", destination="南京")
    registry = ToolRegistry()
    registry.register(WeatherTool())
    state = {
        "messages": ["南京天气怎么样？"],
        "requirement": requirement,
        "information_status": initialize_information_status(requirement),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "request_id": "req-tool-1",
        "run_started_at": monotonic(),
        "validation_round": 0,
        "final_response": None,
    }

    ReActCollector(
        ToolLayer(registry),
        OneDecisionClient(),
        observer=observer,
    ).collect_round(state)

    assert [event.event for event in observer.events] == [
        "stage_started",
        "stage_completed",
        "tool_started",
        "tool_completed",
        "information_updated",
    ]
    assert observer.events[0].stage_name == "react_decision"
    assert observer.events[1].stage_duration_ms is not None
    assert observer.events[1].stage_status == "success"
    completed = observer.events[3]
    assert completed.request_id == "req-tool-1"
    assert completed.tool_name == "weather"
    assert completed.tool_success is True
    assert completed.tool_duration_ms is not None
    assert observer.events[4].information_status == {"weather": "completed"}
    serialized = " ".join(event.model_dump_json() for event in observer.events)
    assert "晴" not in serialized
    assert "不要记录这个参数" not in serialized


def test_graph_records_node_events_and_validation_status() -> None:
    observer = RecordingAgentObserver()
    collected = CollectedInfo(
        pois=[POIInfo(poi_id="P1", name="中山陵", location="118.8,32.0")]
    )
    graph = build_agent_graph(
        analyzer=FakeAnalyzer(
            TravelRequirement(
                intent="trip_planning",
                destination="南京",
                duration_days=1,
            )
        ),
        collector=FakeCollector(collected),
        itinerary_generator=FakeGenerator(_simple_itinerary()),
        validator=FakeValidator(),
        reviser=FakeReviser(),
        response_generator=FinalResponseGenerator(),
        observer=observer,
    )

    result = graph.invoke(
        make_initial_state("帮我规划南京一日游。", request_id="req-graph-1")
    )

    assert result["final_response"]
    assert [event.event for event in observer.events] == [
        "stage_started",
        "stage_completed",
        "requirement_ready",
        "stage_started",
        "stage_completed",
        "itinerary_generated",
        "stage_started",
        "validation_started",
        "stage_completed",
        "validation_completed",
        "stage_started",
        "stage_completed",
        "final_response_ready",
    ]
    stage_completed = [
        event for event in observer.events if event.event == "stage_completed"
    ]
    assert [event.stage_name for event in stage_completed] == [
        "requirement_analyzer",
        "itinerary_generator",
        "validator",
        "final_response",
    ]
    assert all(event.stage_duration_ms is not None for event in stage_completed)
    assert observer.events[-1].total_duration_ms is not None
    assert all(event.request_id == "req-graph-1" for event in observer.events)


def test_structured_logging_observer_emits_json_without_prompt_or_raw_response(
    caplog,
) -> None:
    logger = logging.getLogger("footmarks.agent.test")
    observer = StructuredLoggingObserver(logger)
    api_key = "secret-api-key"
    prompt = "secret prompt content"
    tool_arguments = "secret tool arguments"
    raw_response = "secret raw response"
    event = AgentEvent(
        event="final_response_ready",
        request_id="req-log-1",
        node_name="final_response",
        intent="weather_query",
    )

    with caplog.at_level(logging.INFO, logger="footmarks.agent.test"):
        observer.record(event)

    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "final_response_ready"
    assert payload["request_id"] == "req-log-1"
    assert "user_prompt" not in payload
    assert "tool_arguments" not in payload
    assert "raw_response" not in payload
    assert all(
        value not in caplog.text
        for value in (api_key, prompt, tool_arguments, raw_response)
    )
