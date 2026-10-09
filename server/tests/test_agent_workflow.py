from collections.abc import Iterable
from typing import Any

from app.agent.analyzer import RequirementAnalyzer
from app.agent.collector import ReActCollector, ReActDecision, ToolCall
from app.agent.response import FinalResponseGenerator
from app.agent.tools.layer import ToolLayer, ToolRegistry, ToolResult
from app.agent.workflow import TravelAgentWorkflow
from app.agent.tools.amap import WeatherInput


class FakeStructuredOutputClient:
    def __init__(self, response) -> None:
        self.response = response

    def complete_structured(self, *, system_prompt, user_prompt, output_model):
        return self.response


class FakeDecisionClient:
    def __init__(self, decisions: Iterable[ReActDecision]) -> None:
        self.decisions = iter(decisions)

    def decide(self, context):
        return next(self.decisions, ReActDecision())


class FakeTool:
    name = "weather"
    description = "查询天气"
    input_model = WeatherInput
    information_need = "weather"

    def __init__(self, results: Iterable[ToolResult[Any]]) -> None:
        self.results = iter(results)

    def run(self, **arguments: Any) -> ToolResult[Any]:
        return next(self.results)


def test_workflow_runs_analyzer_collector_and_final_response_for_weather() -> None:
    analyzer = RequirementAnalyzer(
        FakeStructuredOutputClient(
            {"intent": "weather_query", "city": "南京"}
        )
    )
    tool = FakeTool(
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
        ]
    )
    registry = ToolRegistry()
    registry.register(tool)
    collector = ReActCollector(
        ToolLayer(registry),
        FakeDecisionClient(
            [ReActDecision(tool_call=ToolCall(name="weather", arguments={"city": "320100"}))]
        ),
    )
    workflow = TravelAgentWorkflow(analyzer, collector, FinalResponseGenerator())

    result = workflow.run("南京天气怎么样")

    assert result["requirement"].intent == "weather_query"
    assert result["information_status"].weather.status == "completed"
    assert result["collected_info"].weather.description == "晴"
    assert result["final_response"] is not None
    assert "南京市" in result["final_response"]
    assert "晴" in result["final_response"]


def test_workflow_finishes_general_query_without_tool_call() -> None:
    analyzer = RequirementAnalyzer(
        FakeStructuredOutputClient({"intent": "general_query"})
    )
    registry = ToolRegistry()
    collector = ReActCollector(
        ToolLayer(registry),
        FakeDecisionClient([]),
    )
    workflow = TravelAgentWorkflow(analyzer, collector, FinalResponseGenerator())

    result = workflow.run("你能做什么？")

    assert result["react_round"] == 0
    assert "通用旅行问答" in result["final_response"]
