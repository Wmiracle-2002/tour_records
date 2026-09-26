from __future__ import annotations

import logging
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import (
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.runtime import AgentRunResult
from app.agent.runtime import AgentRuntime
from app.agent.collector import ReActDecision
from app.agent.models import TravelRequirement
from app.core.config import Settings


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


def test_agent_chat_start_and_completion_logs_share_request_id(
    client: TestClient,
    caplog,
) -> None:
    use_runtime(client, FakeRuntime())

    with caplog.at_level(logging.INFO, logger="app.api.agent"):
        response = client.post("/api/v1/agent/chat", json={"message": "测试请求"})

    assert response.status_code == 200
    start = next(
        record.message
        for record in caplog.records
        if "Agent request started" in record.message
    )
    completed = next(
        record.message
        for record in caplog.records
        if "Agent request completed" in record.message
    )
    start_id = re.search(r"request_id=([^ ]+)", start)
    completed_id = re.search(r"request_id=([^ ]+)", completed)
    assert start_id is not None
    assert completed_id is not None
    assert start_id.group(1) == completed_id.group(1)


def test_agent_chat_reuses_proxy_request_id_and_returns_header(
    client: TestClient,
    caplog,
) -> None:
    use_runtime(client, FakeRuntime())
    proxy_request_id = "proxy-request-123"

    with caplog.at_level(logging.INFO, logger="app.api.agent"):
        response = client.post(
            "/api/v1/agent/chat",
            json={"message": "测试请求"},
            headers={"X-Request-ID": proxy_request_id},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == proxy_request_id
    assert any(
        f"request_id={proxy_request_id}" in record.message
        for record in caplog.records
    )


def test_agent_chat_uses_authenticated_user_id(client: TestClient) -> None:
    runtime = FakeRuntime()
    use_runtime(client, runtime)

    response = client.post("/api/v1/agent/chat", json={"message": "查看我的旅行记录"})

    assert response.status_code == 200
    assert runtime.calls[0][0] == "查看我的旅行记录"
    assert runtime.calls[0][1] == 1


def test_chat_message_reaches_llm_pipeline_without_android_client(
    client: TestClient,
) -> None:
    user_message = "南京明天天气怎么样？"

    class RecordingLLM:
        def __init__(self) -> None:
            self.analyzer_message: str | None = None
            self.react_context: str | None = None

        def complete_structured(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            output_model,
        ):
            if output_model is TravelRequirement:
                self.analyzer_message = user_prompt
                return {"intent": "weather_query", "city": "南京"}
            if output_model is ReActDecision:
                self.react_context = user_prompt
                return output_model.model_validate(
                    {
                        "tool_call": {
                            "name": "weather",
                            "arguments": {"city": "南京"},
                        }
                    }
                )
            raise AssertionError(f"Unexpected LLM output model: {output_model}")

    llm = RecordingLLM()
    runtime = AgentRuntime(
        Settings(
            database_url="sqlite:///:memory:",
            token_secret="test-only-secret-for-message-pipeline",
        ),
        llm_client=llm,
    )
    use_runtime(client, runtime)

    response = client.post("/api/v1/agent/chat", json={"message": user_message})

    assert response.status_code == 200
    assert llm.analyzer_message == user_message
    assert llm.react_context is None
    assert "天气" in response.json()["answer"]


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
