from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import (
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.runtime import AgentRunResult


class FakeRuntime:
    def __init__(self, result: AgentRunResult | None = None, error: Exception | None = None) -> None:
        self.result = result or AgentRunResult(request_id="req-api-1", answer="测试回答")
        self.error = error
        self.calls: list[tuple[str, int, Any]] = []

    def run(self, message: str, user_id: int, db: Any) -> AgentRunResult:
        self.calls.append((message, user_id, db))
        if self.error is not None:
            raise self.error
        return self.result


def use_runtime(client: TestClient, runtime: FakeRuntime) -> None:
    client.app.state.agent_runtime = runtime


def test_agent_chat_requires_access_token(client: TestClient) -> None:
    client.headers.pop("Authorization", None)

    response = client.post("/api/v1/agent/chat", json={"message": "南京天气怎么样？"})

    assert response.status_code == 401


def test_agent_chat_rejects_blank_and_oversized_message(client: TestClient) -> None:
    runtime = FakeRuntime()
    use_runtime(client, runtime)

    blank = client.post("/api/v1/agent/chat", json={"message": "  \n  "})
    oversized = client.post("/api/v1/agent/chat", json={"message": "a" * 2001})

    assert blank.status_code == 422
    assert oversized.status_code == 422
    assert runtime.calls == []


def test_agent_chat_returns_request_id_and_final_answer(client: TestClient) -> None:
    runtime = FakeRuntime()
    use_runtime(client, runtime)

    response = client.post("/api/v1/agent/chat", json={"message": "帮我规划南京一日游"})

    assert response.status_code == 200
    assert set(response.json()) == {"request_id", "answer"}
    assert response.json() == {"request_id": "req-api-1", "answer": "测试回答"}


def test_agent_chat_uses_authenticated_user_id(client: TestClient) -> None:
    runtime = FakeRuntime()
    use_runtime(client, runtime)

    response = client.post("/api/v1/agent/chat", json={"message": "查看我的旅行记录"})

    assert response.status_code == 200
    assert runtime.calls[0][0] == "查看我的旅行记录"
    assert runtime.calls[0][1] == 1


def test_agent_chat_returns_503_when_llm_is_not_configured(client: TestClient) -> None:
    use_runtime(client, FakeRuntime(error=LLMNotConfiguredError("not configured")))

    response = client.post("/api/v1/agent/chat", json={"message": "测试请求"})

    assert response.status_code == 503


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (LLMTimeoutError("timeout"), 504),
        (LLMUpstreamError("upstream"), 502),
    ],
)
def test_agent_chat_maps_timeout_to_504_and_upstream_failure_to_502(
    client: TestClient,
    error: Exception,
    status_code: int,
) -> None:
    use_runtime(client, FakeRuntime(error=error))

    response = client.post("/api/v1/agent/chat", json={"message": "测试请求"})

    assert response.status_code == status_code
