from app.agent.models import BudgetInfo
from app.agent.tools.budget import create_budget_tools
from app.agent.tools.layer import ToolLayer, ToolRegistry


def budget_tool_layer() -> ToolLayer:
    registry = ToolRegistry()
    for tool in create_budget_tools():
        registry.register(tool)
    return ToolLayer(registry)


def test_estimate_budget_returns_breakdown_and_range() -> None:
    result = budget_tool_layer().execute(
        "estimate_budget",
        destination="南京",
        duration_days=3,
        travelers=2,
        accommodation_level="standard",
        food_level="standard",
        transport_mode="transit",
        pois=["中山陵", "夫子庙"],
    )

    assert result.status == "completed"
    assert isinstance(result.data, BudgetInfo)
    assert result.data.estimated_min == 1632.0
    assert result.data.estimated_max == 2448.0
    assert result.data.breakdown == {
        "accommodation": 700.0,
        "food": 900.0,
        "transport": 240.0,
        "poi_tickets": 200.0,
    }
    assert any("人民币" in assumption for assumption in result.data.assumptions)
    assert any("不是实时精确价格" in assumption for assumption in result.data.assumptions)


def test_estimate_budget_uses_explicit_defaults() -> None:
    result = budget_tool_layer().execute(
        "estimate_budget",
        destination="杭州",
        duration_days=1,
        travelers=1,
    )

    assert result.status == "completed"
    assert result.data.breakdown["accommodation"] == 0.0
    assert result.data.breakdown["food"] == 150.0
    assert result.data.breakdown["transport"] == 60.0
    assert result.data.breakdown["poi_tickets"] == 0.0
    assert any("standard" in assumption for assumption in result.data.assumptions)
    assert any("mixed" in assumption for assumption in result.data.assumptions)


def test_estimate_budget_rejects_invalid_boundaries() -> None:
    invalid_duration = budget_tool_layer().execute(
        "estimate_budget",
        destination="南京",
        duration_days=0,
        travelers=1,
    )
    invalid_travelers = budget_tool_layer().execute(
        "estimate_budget",
        destination="南京",
        duration_days=1,
        travelers=0,
    )
    invalid_level = budget_tool_layer().execute(
        "estimate_budget",
        destination="南京",
        duration_days=1,
        travelers=1,
        food_level="unknown",
    )

    assert invalid_duration.status == "failed"
    assert invalid_travelers.status == "failed"
    assert invalid_level.status == "failed"
    assert invalid_duration.error_code == "tool_execution_failed"


def test_estimate_budget_keeps_missing_destination_explicit() -> None:
    result = budget_tool_layer().execute(
        "estimate_budget",
        duration_days=2,
        travelers=1,
        pois=[],
    )

    assert result.status == "completed"
    assert any("未指定目的地" in assumption for assumption in result.data.assumptions)
