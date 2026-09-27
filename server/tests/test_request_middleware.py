"""HTTP request tracing contracts at the FastAPI boundary."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

from app.agent.llm import LLMTimeoutError, LLMUpstreamError
from app.agent.observability import current_request_id
from app.core.config import Settings
from app.main import create_app


def test_existing_error_envelopes_remain_stable(client: TestClient) -> None:
    missing = client.get("/api/v1/does-not-exist")
    invalid = client.post("/api/v1/agent/chat", json={"message": "  "})
    client.headers.pop("Authorization", None)
    unauthorized = client.post("/api/v1/agent/chat", json={"message": "南京天气"})

    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "Resource not found"}}
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["details"][0]["field"] == "body.message"
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "http_error"


@pytest.mark.parametrize("status_code", [200, 401, 404, 422, 502, 504])
def test_each_http_response_has_current_request_id(client: TestClient, status_code: int) -> None:
    if status_code in {502, 504}:
        error = LLMUpstreamError("upstream") if status_code == 502 else LLMTimeoutError("timeout")

        class FailingRuntime:
            def run(self, *_args, **_kwargs):
                raise error

        client.app.state.agent_runtime = FailingRuntime()
    if status_code == 200:
        response = client.get("/api/v1/health")
    elif status_code == 404:
        response = client.get("/api/v1/does-not-exist")
    else:
        if status_code == 401:
            client.headers.pop("Authorization", None)
        message = " " if status_code == 422 else "南京天气"
        response = client.post("/api/v1/agent/chat", json={"message": message})

    assert response.status_code == status_code
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", response.headers["X-Request-ID"])


def test_valid_proxy_id_is_reused_and_oversized_id_is_replaced(client: TestClient) -> None:
    valid = client.get("/api/v1/health", headers={"X-Request-ID": "proxy-trace-123"})
    invalid = client.get("/api/v1/health", headers={"X-Request-ID": "x" * 65})
    malformed = client.get("/api/v1/health", headers={"X-Request-ID": "bad trace id"})

    assert valid.headers["X-Request-ID"] == "proxy-trace-123"
    assert invalid.headers["X-Request-ID"] != "x" * 65
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", invalid.headers["X-Request-ID"])
    assert malformed.headers["X-Request-ID"] != "bad trace id"


def test_http_logs_have_one_start_and_end_without_query_or_body(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="footmarks.http"):
        response = client.get("/api/v1/health?private=do-not-log", headers={"X-Request-ID": "log-1"})

    events = [json.loads(record.message) for record in caplog.records if record.name == "footmarks.http"]
    starts = [event for event in events if event.get("event") == "http_request_started"]
    ends = [event for event in events if event.get("event") == "http_request_completed"]
    assert response.status_code == 200
    assert len(starts) == len(ends) == 1
    assert starts[0]["request_id"] == ends[0]["request_id"] == "log-1"
    assert ends[0]["method"] == "GET"
    assert ends[0]["route"] == "/api/v1/health"
    assert ends[0]["status_code"] == 200
    assert ends[0]["duration_ms"] >= 0
    assert "do-not-log" not in str(events)


def test_validation_log_names_fields_without_logging_message_value(client: TestClient, caplog) -> None:
    private_text = "private-message-should-not-be-logged"
    with caplog.at_level(logging.INFO, logger="footmarks.http"):
        response = client.post("/api/v1/agent/chat", json={"message": private_text * 100})

    events = [json.loads(record.message) for record in caplog.records if record.name == "footmarks.http"]
    validation = next(event for event in events if event["event"] == "http_validation_failed")
    assert response.status_code == 422
    assert validation["request_id"] == response.headers["X-Request-ID"]
    assert validation["fields"] == ["body.message"]
    assert private_text not in str(events)


def test_request_id_reaches_threadpool_and_is_reset_after_request(client: TestClient) -> None:
    async def trace_thread() -> dict[str, str | None]:
        return {"request_id": await run_in_threadpool(current_request_id)}

    client.app.add_api_route("/trace-thread", trace_thread)
    first = client.get("/trace-thread", headers={"X-Request-ID": "thread-one"})
    second = client.get("/trace-thread", headers={"X-Request-ID": "thread-two"})

    assert first.json() == {"request_id": "thread-one"}
    assert second.json() == {"request_id": "thread-two"}
    assert current_request_id() is None


def test_concurrent_requests_keep_separate_ids() -> None:
    app = create_app(Settings(_env_file=None, token_secret="test-only-secret"))

    async def echo() -> dict[str, str | None]:
        await asyncio.sleep(0.01)
        return {"request_id": current_request_id()}

    app.add_api_route("/trace-concurrent", echo)

    async def send_both():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            return await asyncio.gather(
                client.get("/trace-concurrent", headers={"X-Request-ID": "first-id"}),
                client.get("/trace-concurrent", headers={"X-Request-ID": "second-id"}),
            )

    first, second = asyncio.run(send_both())
    assert first.json() == {"request_id": "first-id"}
    assert second.json() == {"request_id": "second-id"}
    assert current_request_id() is None


def test_unhandled_error_returns_safe_500_with_request_id(client: TestClient, caplog) -> None:
    def crash() -> None:
        raise RuntimeError("private failure detail")

    client.app.add_api_route("/crash", crash)
    with caplog.at_level(logging.INFO, logger="footmarks.http"):
        with TestClient(client.app, raise_server_exceptions=False) as error_client:
            response = error_client.get("/crash", headers={"X-Request-ID": "error-500"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "error-500"
    assert response.json() == {"error": {"code": "internal_error", "message": "Internal server error"}}
    ends = [
        json.loads(record.message) for record in caplog.records
        if record.name == "footmarks.http" and record.message.startswith("{")
        and json.loads(record.message).get("event") == "http_request_completed"
    ]
    assert len(ends) == 1
    assert ends[0]["status_code"] == 500
    assert ends[0]["exception_type"] == "RuntimeError"
