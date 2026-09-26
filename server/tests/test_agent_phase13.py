from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.agent.analyzer import RequirementAnalyzer
from app.agent.collector import ReActCollector, ReActDecision, ToolCall
from app.agent.generator import StructuredItineraryGenerator
from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.models import (
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    TravelRequirement,
)
from app.agent.reviser import LocalItineraryReviser
from app.agent.response import FinalResponseGenerator
from app.agent.tools.budget import EstimateBudgetTool
from app.agent.tools.layer import ToolLayer, ToolRegistry, ToolResult
from agent_tool_test_utils import AgentTestInput, TEST_INFORMATION_NEEDS
from app.agent.validator import ItineraryValidator


class OneOutputClient:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[tuple[str, str, type[Any]]] = []

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Any],
    ) -> Any:
        self.calls.append((system_prompt, user_prompt, output_model))
        return self.output


class ScenarioTool:
    def __init__(self, name: str, data: Any) -> None:
        self.name = name
        self.description = f"Phase 13 test tool: {name}"
        self.input_model = AgentTestInput
        self.information_need = TEST_INFORMATION_NEEDS[name]
        self._data = data

    def run(self, **_arguments: Any) -> ToolResult[Any]:
        return ToolResult.completed(self._data)


class ScenarioDecisionClient:
    def __init__(self, calls: Mapping[str, tuple[str, dict[str, Any]]]) -> None:
        self._calls = calls
        self.contexts = []

    def decide(self, context):
        self.contexts.append(context)
        for need, (tool_name, arguments) in self._calls.items():
            requirement = getattr(context.information_status, need)
            if requirement is None or requirement.status == "pending":
                return ReActDecision(
                    tool_call=ToolCall(
                        name=tool_name,
                        arguments=arguments,
                    )
                )
        return ReActDecision(reason="All scenario information is collected")


def _run_graph(
    query: str,
    requirement: TravelRequirement,
    *,
    calls: Mapping[str, tuple[str, dict[str, Any]]],
    tools: Iterable[Any],
    itinerary: Itinerary | None = None,
    revised_itinerary: Itinerary | None = None,
):
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)

    decision_client = ScenarioDecisionClient(calls)
    collector = ReActCollector(
        ToolLayer(registry),
        decision_client,
    )
    analyzer = RequirementAnalyzer(OneOutputClient(requirement))
    generator = StructuredItineraryGenerator(
        OneOutputClient(itinerary or _placeholder_itinerary())
    )
    reviser = LocalItineraryReviser(
        OneOutputClient(revised_itinerary or itinerary or _placeholder_itinerary())
    )
    graph = build_agent_graph(
        analyzer=analyzer,
        collector=collector,
        itinerary_generator=generator,
        validator=ItineraryValidator(),
        reviser=reviser,
        response_generator=FinalResponseGenerator(),
    )
    return graph.invoke(make_initial_state(query))


def _placeholder_itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[],
            )
        ]
    )


def _poi(
    poi_id: str,
    name: str,
    *,
    opening_hours: str | None = "08:00-18:00",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": poi_id,
        "name": name,
        "location": "118.800000,32.060000",
        "type": "历史建筑",
    }
    if opening_hours is not None:
        payload["biz_ext"] = {"open_time": opening_hours}
    return payload


def _poi_tool(*pois: dict[str, Any]) -> ScenarioTool:
    return ScenarioTool("keyword_search", {"pois": list(pois)})


def _history_tool(*trips: dict[str, Any]) -> ScenarioTool:
    return ScenarioTool("search_trip_history", list(trips))


def _route_tool(
    *,
    distance: int = 9000,
    duration_seconds: int = 1800,
) -> ScenarioTool:
    return ScenarioTool(
        "driving_route",
        {
            "route": {
                "paths": [
                    {
                        "distance": str(distance),
                        "duration": str(duration_seconds),
                    }
                ]
            }
        },
    )


def _three_day_itinerary(*items: ItineraryItem) -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(date="2026-10-01", items=[items[0]]),
            ItineraryDay(date="2026-10-02", items=[items[1]]),
            ItineraryDay(date="2026-10-03", items=[items[2]]),
        ]
    )


def test_phase13_case_1_weather_query() -> None:
    result = _run_graph(
        "南京明天天气怎么样？",
        TravelRequirement(intent="weather_query", city="南京"),
        calls={
            "weather": (
                "weather",
                {"city": "南京", "forecast": True},
            )
        },
        tools=[
            ScenarioTool(
                "weather",
                {
                    "city": "南京市",
                    "casts": [
                        {
                            "date": "2026-10-01",
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "30",
                            "nighttemp": "20",
                        }
                    ],
                },
            )
        ],
    )

    assert result["information_status"].weather.status == "completed"
    assert result["collected_info"].weather.description == "晴 / 多云"
    assert "南京市" in result["final_response"]
    assert "晴 / 多云" in result["final_response"]


def test_phase13_case_2_history_query() -> None:
    result = _run_graph(
        "我之前去过杭州吗？",
        TravelRequirement(intent="history_query", city="杭州"),
        calls={"history": ("search_trip_history", {})},
        tools=[
            _history_tool(
                {
                    "trip_id": "trip-hz",
                    "city_name": "杭州",
                    "records": [{"name": "西湖", "poi_id": "H1"}],
                }
            )
        ],
    )

    assert result["information_status"].history.status == "completed"
    assert result["collected_info"].history.visited_cities == ["杭州"]
    assert "西湖" in result["final_response"]


def test_phase13_case_3_poi_recommendation() -> None:
    result = _run_graph(
        "推荐几个南京适合看历史建筑的地方。",
        TravelRequirement(
            intent="poi_recommendation",
            city="南京",
            preferences=["历史建筑"],
        ),
        calls={
            "pois": (
                "keyword_search",
                {"keywords": "历史建筑", "city": "南京"},
            )
        },
        tools=[
            _poi_tool(
                _poi("P1", "中山陵"),
                _poi("P2", "总统府"),
            )
        ],
    )

    assert result["information_status"].pois.status == "completed"
    assert [poi.name for poi in result["collected_info"].pois] == ["中山陵", "总统府"]
    assert "中山陵" in result["final_response"]
    assert "总统府" in result["final_response"]


def test_phase13_case_4_budget_query() -> None:
    result = _run_graph(
        "两个人去南京玩三天大概需要多少钱？",
        TravelRequirement(
            intent="budget_query",
            city="南京",
            duration_days=3,
            travelers=2,
        ),
        calls={
            "budget": (
                "estimate_budget",
                {
                    "city": "南京",
                    "duration_days": 3,
                    "travelers": 2,
                },
            )
        },
        tools=[EstimateBudgetTool()],
    )

    budget = result["collected_info"].budget
    assert result["information_status"].budget.status == "completed"
    assert budget.estimated_min == 1568
    assert budget.estimated_max == 2352
    assert "人民币" in result["final_response"]


def test_phase13_case_5_route_query_is_not_dispatched() -> None:
    result = _run_graph(
        "从中山陵去夫子庙怎么走？",
        TravelRequirement(intent="route_query", origin="中山陵", destination="夫子庙"),
        calls={
            "routes": (
                "driving_route",
                {"origin": "中山陵", "destination": "夫子庙"},
            )
        },
        tools=[_route_tool()],
    )

    assert result["collected_info"].routes == []
    assert result["information_status"].routes is None
    assert "路线导航" in result["final_response"]


def test_phase13_case_6_simple_three_day_itinerary() -> None:
    pois = [
        _poi("P1", "中山陵"),
        _poi("P2", "总统府"),
        _poi("P3", "夫子庙", opening_hours="08:00-22:00"),
    ]
    itinerary = _three_day_itinerary(
        ItineraryItem(
            poi_id="P1",
            poi_name="中山陵",
            start_time="09:00",
            end_time="11:00",
            activity_type="游览",
        ),
        ItineraryItem(
            poi_id="P2",
            poi_name="总统府",
            start_time="09:00",
            end_time="11:00",
            activity_type="游览",
        ),
        ItineraryItem(
            poi_id="P3",
            poi_name="夫子庙",
            start_time="18:00",
            end_time="20:00",
            activity_type="美食",
        ),
    )
    result = _run_graph(
        "帮我规划南京三日游。",
        TravelRequirement(
            intent="trip_planning",
            city="南京",
            start_date="2026-10-01",
            end_date="2026-10-03",
            duration_days=3,
        ),
        calls={"pois": ("keyword_search", {"keywords": "南京景点"})},
        tools=[_poi_tool(*pois)],
        itinerary=itinerary,
    )

    assert result["itinerary"] == itinerary
    assert result["validation"].valid is True
    assert "第1天（2026-10-01）" in result["final_response"]
    assert "夫子庙" in result["final_response"]


def test_phase13_case_7_itinerary_respects_history_constraint() -> None:
    pois = [_poi("P1", "中山陵"), _poi("P2", "总统府")]
    itinerary = _three_day_itinerary(
        ItineraryItem(
            poi_id="P2",
            poi_name="总统府",
            start_time="09:00",
            end_time="11:00",
            activity_type="游览",
        ),
        ItineraryItem(
            poi_id="P2",
            poi_name="总统府",
            start_time="09:00",
            end_time="11:00",
            activity_type="游览",
        ),
        ItineraryItem(
            poi_id="P2",
            poi_name="总统府",
            start_time="09:00",
            end_time="11:00",
            activity_type="游览",
        ),
    )
    requirement = TravelRequirement(
        intent="trip_planning",
        city="南京",
        start_date="2026-10-01",
        duration_days=3,
        constraints=["不要安排以前去过的景点"],
    )
    result = _run_graph(
        "帮我规划南京三日游，不要安排我以前去过的景点。",
        requirement,
        calls={
            "history": ("search_trip_history", {}),
            "pois": ("keyword_search", {"keywords": "南京景点"}),
        },
        tools=[
            _history_tool(
                {
                    "trip_id": "trip-nj",
                    "city_name": "南京",
                    "records": [{"name": "中山陵", "poi_id": "P1"}],
                }
            ),
            _poi_tool(*pois),
        ],
        itinerary=itinerary,
    )

    planned_ids = [
        item.poi_id
        for day in result["itinerary"].days
        for item in day.items
    ]
    assert result["collected_info"].history.visited_poi_ids == ["P1"]
    assert "P1" not in planned_ids
    assert result["validation"].valid is True


def test_phase13_case_8_complex_requirement_collects_budget_and_history() -> None:
    pois = [
        _poi("P1", "中山陵"),
        _poi("P2", "总统府"),
        _poi("P3", "夫子庙", opening_hours="08:00-22:00"),
        _poi("P4", "南京博物院"),
    ]
    itinerary = _three_day_itinerary(
        ItineraryItem(
            poi_id="P2",
            poi_name="总统府",
            start_time="09:00",
            end_time="11:00",
            activity_type="历史文化",
        ),
        ItineraryItem(
            poi_id="P3",
            poi_name="夫子庙",
            start_time="18:00",
            end_time="20:00",
            activity_type="当地美食",
        ),
        ItineraryItem(
            poi_id="P4",
            poi_name="南京博物院",
            start_time="09:00",
            end_time="12:00",
            activity_type="历史文化",
        ),
    )
    requirement = TravelRequirement(
        intent="trip_planning",
        origin="上海",
        city="南京",
        start_date="2026-10-01",
        end_date="2026-10-03",
        duration_days=3,
        travelers=2,
        budget=3000,
        preferences=["历史文化", "当地美食"],
        constraints=["不想去以前去过的景点"],
    )
    result = _run_graph(
        "十一从上海去南京玩三天，两个人预算3000，喜欢历史文化和当地美食，不想去以前去过的景点。",
        requirement,
        calls={
            "history": ("search_trip_history", {}),
            "pois": ("keyword_search", {"keywords": "历史文化 当地美食"}),
            "budget": (
                "estimate_budget",
                {
                    "city": "南京",
                    "duration_days": 3,
                    "travelers": 2,
                    "pois": ["总统府", "夫子庙", "南京博物院"],
                },
            ),
        },
        tools=[
            _history_tool(
                {
                    "trip_id": "trip-nj-old",
                    "city_name": "南京",
                    "records": [{"name": "中山陵", "poi_id": "P1"}],
                }
            ),
            _poi_tool(*pois),
            EstimateBudgetTool(),
        ],
        itinerary=itinerary,
    )

    assert result["requirement"].origin == "上海"
    assert result["requirement"].preferences == ["历史文化", "当地美食"]
    assert result["collected_info"].budget.estimated_max <= 3000
    assert result["validation"].valid is True
    assert "预算参考（人民币）" in result["final_response"]


def test_phase13_case_9_missing_opening_hours_is_unknown_in_final_response() -> None:
    itinerary = Itinerary(
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
    result = _run_graph(
        "帮我规划南京一日游，开放时间未知也不要猜。",
        TravelRequirement(
            intent="trip_planning",
            city="南京",
            start_date="2026-10-01",
            duration_days=1,
        ),
        calls={"pois": ("keyword_search", {"keywords": "南京景点"})},
        tools=[_poi_tool(_poi("P1", "中山陵", opening_hours=None))],
        itinerary=itinerary,
    )

    opening_issue = next(
        issue
        for issue in result["validation"].issues
        if issue.type == "opening_hours"
    )
    assert opening_issue.status == "unknown"
    assert result["validation"].valid is True
    assert "未完成验证" in result["final_response"]
    assert "可靠的开放时间" in result["final_response"]


def test_phase13_case_10_planning_does_not_discover_navigation_after_pois_complete() -> None:
    initial_itinerary = Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="P1",
                        poi_name="中山陵",
                        start_time="10:00",
                        end_time="11:30",
                        activity_type="游览",
                    ),
                    ItineraryItem(
                        poi_id="P2",
                        poi_name="夫子庙",
                        start_time="12:00",
                        end_time="13:00",
                        activity_type="游览",
                    ),
                ],
            )
        ]
    )
    revised_itinerary = Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    initial_itinerary.days[0].items[0],
                    ItineraryItem(
                        poi_id="P2",
                        poi_name="夫子庙",
                        start_time="13:00",
                        end_time="14:00",
                        activity_type="游览",
                    ),
                ],
            )
        ]
    )
    result = _run_graph(
        "帮我规划南京一日游。",
        TravelRequirement(
            intent="trip_planning",
            city="南京",
            start_date="2026-10-01",
            duration_days=1,
        ),
        calls={
            "pois": ("keyword_search", {"keywords": "南京景点"}),
            "routes": (
                "driving_route",
                {"origin": "P1", "destination": "P2"},
            ),
        },
        tools=[
            _poi_tool(_poi("P1", "中山陵"), _poi("P2", "夫子庙")),
            _route_tool(duration_seconds=3600),
        ],
        itinerary=initial_itinerary,
        revised_itinerary=revised_itinerary,
    )

    assert result["validation_round"] == 0
    assert result["itinerary"] == initial_itinerary
    assert result["collected_info"].routes == []
    assert result["validation"].valid is True
    assert "可靠路线时间" in result["final_response"]
