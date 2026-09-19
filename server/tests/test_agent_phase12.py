from typing import Any

from app.agent.collector import ReActCollector, ReActDecision, ReActContext, ToolCall
from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
    TravelRequirement,
    ValidationResult,
)
from app.agent.response import FinalResponseGenerator
from app.agent.state import TravelAgentState
from app.agent.tools.layer import ToolLayer, ToolRegistry, ToolResult


class EmptyHistoryTool:
    name = "search_trip_history"
    description = "查询历史旅行记录"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, **arguments: Any) -> ToolResult[Any]:
        self.calls += 1
        return ToolResult.completed([])


class FailingWeatherTool:
    name = "weather"
    description = "查询天气"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, **arguments: Any) -> ToolResult[Any]:
        self.calls += 1
        return ToolResult.failed("天气服务连接超时", error_code="provider_timeout")


class FixedDecisionClient:
    def __init__(self, tool_call: ToolCall) -> None:
        self.tool_call = tool_call
        self.contexts: list[ReActContext] = []

    def decide(self, context: ReActContext) -> ReActDecision:
        self.contexts.append(context)
        return ReActDecision(tool_call=self.tool_call)


class WeatherAnalyzer:
    def analyze(self, user_query: str) -> TravelRequirement:
        return TravelRequirement(intent="weather_query", destination="南京")


class UnusedGenerator:
    def generate(self, requirement, collected_info) -> Itinerary:
        raise AssertionError("weather failure must not generate an itinerary")


class UnusedValidator:
    def validate(self, requirement, itinerary, collected_info) -> ValidationResult:
        raise AssertionError("weather failure must not validate an itinerary")


class UnusedReviser:
    def revise(self, itinerary, issues, requirement, collected_info) -> Itinerary:
        raise AssertionError("weather failure must not revise an itinerary")


def _history_state() -> TravelAgentState:
    return {
        "messages": [],
        "requirement": TravelRequirement(intent="history_query"),
        "information_status": InformationStatus(
            history={"status": "pending", "critical": True}
        ),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "validation_round": 0,
        "final_response": None,
    }


def test_empty_history_is_a_successful_terminal_result_without_retries() -> None:
    tool = EmptyHistoryTool()
    registry = ToolRegistry()
    registry.register(tool)
    collector = ReActCollector(
        ToolLayer(registry),
        FixedDecisionClient(
            ToolCall(name="search_trip_history", arguments={"city": "南京"})
        ),
    )

    result = collector.collect(_history_state())

    assert result["information_status"].history.status == "completed"
    assert result["information_status"].history.attempts == 0
    assert result["collected_info"].history.trip_count == 0
    assert result["react_round"] == 1
    assert tool.calls == 1


def test_core_weather_failure_reaches_final_response_after_bounded_retries() -> None:
    tool = FailingWeatherTool()
    registry = ToolRegistry()
    registry.register(tool)
    collector = ReActCollector(
        ToolLayer(registry),
        FixedDecisionClient(
            ToolCall(name="weather", arguments={"city": "320100"})
        ),
    )
    graph = build_agent_graph(
        analyzer=WeatherAnalyzer(),
        collector=collector,
        itinerary_generator=UnusedGenerator(),
        validator=UnusedValidator(),
        reviser=UnusedReviser(),
        response_generator=FinalResponseGenerator(),
    )

    result = graph.invoke(make_initial_state("南京明天天气怎么样？"))

    assert result["information_status"].weather.status == "failed"
    assert result["information_status"].weather.attempts == 3
    assert result["react_round"] == 3
    assert tool.calls == 3
    assert "天气信息查询失败" in result["final_response"]
    assert "天气服务连接超时" in result["final_response"]
