from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.budget import (
    AgentClientDisconnected,
    AgentCancellation,
    AgentTimeoutError,
)
from app.api.agent import _watch_client_disconnect
from app.agent.runtime import AgentRunResult


class InvalidItineraryRuntime:
    def run(self, _message: str, _user_id: int, _db: Any) -> AgentRunResult:
        raise ValueError("unknown poi_id: internal-poi-id")


class RichAgentRunResult(AgentRunResult):
    information_status: dict[str, str] = {"pois": "completed"}
    collected_info: dict[str, Any] = {"secret": "collected"}
    itinerary: dict[str, Any] = {"days": []}
    validation: dict[str, Any] = {"valid": True}
    reason: str = "internal reason"


class RichRuntime:
    def run(self, _message: str, _user_id: int, _db: Any) -> RichAgentRunResult:
        return RichAgentRunResult(
            request_id="req-boundary-1",
            answer="公开回答",
        )


class TimedOutRuntime:
    def run(self, _message: str, _user_id: int, _db: Any) -> AgentRunResult:
        raise AgentTimeoutError("Agent total timeout exceeded before itinerary_generator")


class DisconnectingRequest:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls >= 2


def test_invalid_itinerary_never_reaches_http_answer(client) -> None:
    client.app.state.agent_runtime = InvalidItineraryRuntime()

    response = client.post("/api/v1/agent/chat", json={"message": "规划行程"})

    assert response.status_code == 502
    assert "unknown poi_id" not in response.text
    assert "internal-poi-id" not in response.text


def test_agent_api_does_not_return_internal_state_or_validation_models(client) -> None:
    client.app.state.agent_runtime = RichRuntime()

    response = client.post("/api/v1/agent/chat", json={"message": "测试"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"request_id", "answer"}
    for field in (
        "information_status",
        "collected_info",
        "itinerary",
        "validation",
        "reason",
    ):
        assert field not in body


def test_agent_budget_timeout_maps_to_504(client) -> None:
    client.app.state.agent_runtime = TimedOutRuntime()

    response = client.post("/api/v1/agent/chat", json={"message": "规划行程"})

    assert response.status_code == 504
    assert response.json()["error"]["message"] == "Agent request timed out"


def test_disconnect_watcher_sets_agent_cancellation() -> None:
    cancellation = AgentCancellation()

    asyncio.run(
        _watch_client_disconnect(
            DisconnectingRequest(), cancellation, "request-disconnect-test"
        )
    )

    with pytest.raises(AgentClientDisconnected, match="client disconnected"):
        cancellation.raise_if_cancelled()
