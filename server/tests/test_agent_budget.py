import pytest

from app.agent.analyzer import RequirementAnalyzer
from app.agent.budget import (
    AgentBudget,
    AgentClientDisconnected,
    AgentCancellation,
    AgentTimeoutError,
    current_llm_timeout_seconds,
)
from app.agent.models import TravelRequirement


class SlowRequirementClient:
    def __init__(self, now: list[float]) -> None:
        self._now = now

    def complete_structured(self, **_kwargs):
        self._now[0] += 6.0
        return TravelRequirement(intent="general_query")


def test_budget_exposes_remaining_timeout_to_one_llm_stage() -> None:
    now = [100.0]
    budget = AgentBudget(
        total_timeout_seconds=30.0,
        stage_timeout_seconds=12.0,
        clock=lambda: now[0],
    )

    with budget.stage("requirement_analyzer"):
        assert current_llm_timeout_seconds() == 12.0
        now[0] += 3.0
        assert current_llm_timeout_seconds() == 9.0

    now[0] += 5.0
    with budget.stage("react_decision"):
        assert current_llm_timeout_seconds() == 12.0


def test_budget_rejects_next_stage_after_total_timeout() -> None:
    now = [100.0]
    budget = AgentBudget(
        total_timeout_seconds=10.0,
        stage_timeout_seconds=12.0,
        clock=lambda: now[0],
    )

    with budget.stage("requirement_analyzer"):
        now[0] += 8.0

    now[0] += 3.0
    with pytest.raises(AgentTimeoutError, match="Agent total timeout exceeded"):
        with budget.stage("react_decision"):
            pass


def test_budget_rejects_stage_after_stage_budget_is_consumed() -> None:
    now = [100.0]
    budget = AgentBudget(
        total_timeout_seconds=30.0,
        stage_timeout_seconds=5.0,
        clock=lambda: now[0],
    )

    with pytest.raises(AgentTimeoutError, match="react_decision stage timeout exceeded"):
        with budget.stage("react_decision"):
            now[0] += 5.0


def test_requirement_analyzer_cannot_exceed_its_stage_budget() -> None:
    now = [100.0]
    budget = AgentBudget(
        total_timeout_seconds=30.0,
        stage_timeout_seconds=5.0,
        clock=lambda: now[0],
    )

    with pytest.raises(AgentTimeoutError, match="requirement_analyzer stage timeout exceeded"):
        RequirementAnalyzer(SlowRequirementClient(now), budget=budget).analyze("测试")


def test_client_disconnect_stops_the_next_agent_stage() -> None:
    cancellation = AgentCancellation()
    budget = AgentBudget(
        total_timeout_seconds=30.0,
        stage_timeout_seconds=5.0,
        cancellation=cancellation,
    )
    cancellation.cancel()

    with pytest.raises(AgentClientDisconnected, match="client disconnected"):
        with budget.stage("react_decision"):
            pass
