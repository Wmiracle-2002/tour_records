from typing import Any

import httpx
import pytest

from app.agent.collector import ReActCollector, ReActDecision, ReActContext, ToolCall
from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.llm import LLMTimeoutError, LLMUpstreamError, OpenAICompatibleTransport
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
from app.agent.tools.amap import WeatherInput
from agent_tool_test_utils import AgentTestInput
from app.core.config import Settings


class EmptyHistoryTool:
    name = "search_trip_history"
    description = "查询历史旅行记录"
    input_model = AgentTestInput
    information_need = "history"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, **arguments: Any) -> ToolResult[Any]:
        self.calls += 1
        return ToolResult.completed([])


class FailingWeatherTool:
    name = "weather"
    description = "查询天气"
    input_model = WeatherInput
    information_need = "weather"

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
        return TravelRequirement(intent="weather_query", city="南京")


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


def test_llm_429_is_retried_within_configured_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            request=request,
            json={"error": {"message": "too many requests"}},
        )

    settings = Settings(
        token_secret="test-only-secret",
        llm_base_url="https://llm.example.test/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
        llm_max_retries=2,
    )
    transport = OpenAICompatibleTransport(
        settings,
        http_transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMUpstreamError):
        transport.complete_json(
            system_prompt="secret system prompt",
            user_prompt="secret user prompt",
            output_model=TravelRequirement,
        )

    transport.close()
    assert calls == settings.llm_max_retries + 1


class TimeoutDecisionClient:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, _context: ReActContext) -> ReActDecision:
        self.calls += 1
        raise LLMTimeoutError("LLM timed out")


def test_llm_timeout_does_not_enter_infinite_react_loop() -> None:
    decision_client = TimeoutDecisionClient()
    collector = ReActCollector(
        ToolLayer(ToolRegistry()),
        decision_client,
    )

    with pytest.raises(LLMTimeoutError):
        collector.collect(_history_state())

    assert decision_client.calls == 1
