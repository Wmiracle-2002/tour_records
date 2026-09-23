from collections.abc import Iterable
from typing import Any

from app.agent.collector import (
    MAX_REACT_ROUNDS,
    ReActCollector,
    ReActDecision,
    ReActContext,
    ToolCall,
)
from app.agent.information import initialize_information_status
from app.agent.models import CollectedInfo, TravelRequirement
from app.agent.state import TravelAgentState
from app.agent.tools.layer import ToolLayer, ToolRegistry, ToolResult


class FakeTool:
    description = "测试工具"

    def __init__(self, name: str, results: Iterable[ToolResult[Any]]) -> None:
        self.name = name
        self._results = iter(results)
        self.calls: list[dict[str, Any]] = []

    def run(self, **arguments: Any) -> ToolResult[Any]:
        self.calls.append(arguments)
        return next(self._results)


class FakeDecisionClient:
    def __init__(self, decisions: Iterable[ReActDecision | None]) -> None:
        self._decisions = iter(decisions)
        self.contexts: list[ReActContext] = []

    def decide(self, context: ReActContext) -> ReActDecision | None:
        self.contexts.append(context)
        return next(self._decisions, ReActDecision())


def build_state(requirement: TravelRequirement) -> TravelAgentState:
    return {
        "messages": [],
        "requirement": requirement,
        "information_status": initialize_information_status(requirement),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "validation_round": 0,
        "final_response": None,
    }


def build_layer(tool: FakeTool) -> ToolLayer:
    registry = ToolRegistry()
    registry.register(tool)
    return ToolLayer(registry)


def build_layer_for_tools(*tools: FakeTool) -> ToolLayer:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolLayer(registry)


def test_collector_executes_weather_tool_normalizes_and_stops() -> None:
    tool = FakeTool(
        "weather",
        [
            ToolResult.completed(
                {
                    "status": "1",
                    "lives": [
                        {
                            "city": "南京市",
                            "weather": "晴",
                            "reporttime": "2026-09-18 10:00:00",
                        }
                    ],
                }
            )
        ],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(name="weather", arguments={"city": "320100"})
            ),
            ReActDecision(),
        ]
    )
    state = build_state(TravelRequirement(intent="weather_query"))

    result = ReActCollector(build_layer(tool), client).collect(state)

    assert result["information_status"].weather.status == "completed"
    assert result["collected_info"].weather.description == "晴"
    assert result["react_round"] == 1
    assert tool.calls == [{"city": "320100"}]
    assert len(client.contexts) == 1
    assert client.contexts[0].available_tools[0].name == "weather"
    assert client.contexts[0].collected_info == CollectedInfo()


def test_collector_normalizes_internal_history_result() -> None:
    tool = FakeTool(
        "search_trip_history",
        [
            ToolResult.completed(
                [
                    {
                        "trip_id": 1,
                        "city_name": "南京市",
                        "records": [{"poi_id": "B1", "name": "中山陵"}],
                    }
                ]
            )
        ],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(
                    name="search_trip_history",
                    arguments={"city": "南京"},
                )
            )
        ]
    )
    state = build_state(TravelRequirement(intent="history_query"))

    result = ReActCollector(build_layer(tool), client).collect(state)

    assert result["information_status"].history.status == "completed"
    assert result["collected_info"].history.visited_names == ["中山陵"]


def test_collector_defaults_history_city_from_requirement_destination() -> None:
    tool = FakeTool(
        "search_trip_history",
        [ToolResult.completed([{"trip_id": 1, "city_name": "南京市", "records": []}])],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(name="search_trip_history", arguments={})
            )
        ]
    )
    state = build_state(
        TravelRequirement(
            intent="history_query",
            destination="南京",
            history_category="ATTRACTION",
        )
    )

    ReActCollector(build_layer(tool), client).collect(state)

    assert tool.calls == [{"city": "南京", "category": "ATTRACTION"}]


def test_collector_defaults_route_endpoints_from_requirement() -> None:
    tool = FakeTool(
        "walking_route",
        [
            ToolResult.completed(
                {
                    "route": {
                        "paths": [{"distance": "1000", "duration": "600"}]
                    }
                }
            )
        ],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(name="walking_route", arguments={})
            )
        ]
    )
    state = build_state(
        TravelRequirement(
            intent="route_query",
            origin="南京站",
            destination="中山陵",
        )
    )

    ReActCollector(build_layer(tool), client).collect(state)

    assert tool.calls == [{"origin": "南京站", "destination": "中山陵"}]


def test_trip_planning_decisions_can_collect_multiple_needs_in_any_order() -> None:
    history_tool = FakeTool(
        "search_trip_history",
        [ToolResult.completed([{"trip_id": 1, "city_name": "南京市", "records": []}])],
    )
    poi_tool = FakeTool(
        "keyword_search",
        [
            ToolResult.completed(
                {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B1",
                            "name": "中山陵",
                            "location": "118.858,32.058",
                        }
                    ],
                }
            )
        ],
    )
    budget_tool = FakeTool(
        "estimate_budget",
        [ToolResult.completed({"estimated_min": 800, "estimated_max": 1200})],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(
                    name="estimate_budget",
                    arguments={"duration_days": 3, "travelers": 2},
                )
            ),
            ReActDecision(
                tool_call=ToolCall(
                    name="search_trip_history", arguments={"city": "南京"}
                )
            ),
            ReActDecision(
                tool_call=ToolCall(
                    name="keyword_search", arguments={"keywords": "历史建筑"}
                )
            ),
        ]
    )
    state = build_state(
        TravelRequirement(
            intent="trip_planning",
            budget=3000,
            constraints=["不要安排以前去过的景点"],
        )
    )

    result = ReActCollector(
        build_layer_for_tools(history_tool, poi_tool, budget_tool), client
    ).collect(state)

    assert result["react_round"] == 3
    assert result["information_status"].history.status == "completed"
    assert result["information_status"].pois.status == "completed"
    assert result["information_status"].budget.status == "completed"
    assert result["collected_info"].pois[0].poi_id == "B1"
    assert result["collected_info"].budget.estimated_max == 1200


def test_collector_normalizes_common_keyword_search_argument_alias() -> None:
    tool = FakeTool(
        "keyword_search",
        [
            ToolResult.completed(
                {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B1",
                            "name": "中山陵",
                            "location": "118.858,32.058",
                        }
                    ],
                }
            )
        ],
    )
    client = FakeDecisionClient(
        [
            ReActDecision(
                tool_call=ToolCall(
                    name="keyword_search", arguments={"keyword": "历史建筑"}
                )
            )
        ]
    )

    result = ReActCollector(
        build_layer(tool), client
    ).collect(build_state(TravelRequirement(intent="poi_recommendation")))

    assert result["information_status"].pois.status == "completed"
    assert tool.calls == [{"keywords": "历史建筑"}]


def test_empty_result_retries_three_times_then_stops() -> None:
    tool = FakeTool(
        "weather",
        [
            ToolResult.completed({"status": "1", "lives": []})
            for _ in range(3)
        ],
    )
    decision = ReActDecision(
        tool_call=ToolCall(name="weather", arguments={"city": "320100"})
    )
    client = FakeDecisionClient([decision, decision, decision, decision])

    result = ReActCollector(
        build_layer(tool), client
    ).collect(build_state(TravelRequirement(intent="weather_query")))

    assert result["information_status"].weather.status == "unavailable"
    assert result["information_status"].weather.attempts == 3
    assert result["react_round"] == 3
    assert len(tool.calls) == 3


def test_error_result_retries_three_times_then_becomes_failed() -> None:
    tool = FakeTool(
        "weather",
        [ToolResult.failed("provider error", error_code="provider_error") for _ in range(3)],
    )
    decision = ReActDecision(
        tool_call=ToolCall(name="weather", arguments={"city": "320100"})
    )
    client = FakeDecisionClient([decision, decision, decision])

    result = ReActCollector(
        build_layer(tool), client
    ).collect(build_state(TravelRequirement(intent="weather_query")))

    assert result["information_status"].weather.status == "failed"
    assert result["information_status"].weather.attempts == 3
    assert result["information_status"].weather.reason == "provider error"


def test_no_tool_call_waits_for_pending_information_until_round_limit() -> None:
    client = FakeDecisionClient([ReActDecision() for _ in range(MAX_REACT_ROUNDS)])
    state = build_state(TravelRequirement(intent="weather_query"))

    result = ReActCollector(ToolLayer(ToolRegistry()), client).collect(state)

    assert result["information_status"].weather.status == "pending"
    assert result["react_round"] == MAX_REACT_ROUNDS
    assert len(client.contexts) == MAX_REACT_ROUNDS


def test_completed_information_skips_react_without_calling_client() -> None:
    client = FakeDecisionClient([])
    state = build_state(TravelRequirement(intent="weather_query"))
    state["information_status"].weather.status = "completed"

    result = ReActCollector(ToolLayer(ToolRegistry()), client).collect(state)

    assert result["react_round"] == 0
    assert client.contexts == []


def test_collector_does_not_mutate_input_state() -> None:
    tool = FakeTool(
        "weather",
        [
            ToolResult.completed(
                {
                    "status": "1",
                    "lives": [{"city": "南京市", "weather": "晴", "reporttime": "2026-09-18"}],
                }
            )
        ],
    )
    client = FakeDecisionClient(
        [ReActDecision(tool_call=ToolCall(name="weather", arguments={"city": "320100"}))]
    )
    state = build_state(TravelRequirement(intent="weather_query"))

    ReActCollector(build_layer(tool), client).collect(state)

    assert state["react_round"] == 0
    assert state["information_status"].weather.status == "pending"
    assert state["collected_info"] == CollectedInfo()
