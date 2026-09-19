import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import BaseModel

from app.agent.llm import (
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
    OpenAICompatibleTransport,
    StructuredLLMClient,
)
from app.core.config import Settings


class Answer(BaseModel):
    answer: str


def settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
        "llm_timeout_seconds": 5.0,
        "llm_max_retries": 1,
    }
    values.update(overrides)
    return Settings(**values)


def response_with_content(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": content}}]},
    )


def run_client(
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: object,
) -> tuple[Answer, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = OpenAICompatibleTransport(
        settings(**overrides),
        http_transport=httpx.MockTransport(recording_handler),
    )
    result = StructuredLLMClient(transport).complete_structured(
        system_prompt="Return JSON",
        user_prompt="Say hello",
        output_model=Answer,
    )
    return result, requests


def test_structured_client_sends_json_schema_and_validates_result() -> None:
    result, requests = run_client(
        lambda request: response_with_content('{"answer":"hello"}')
    )

    payload = json.loads(requests[0].content)
    assert requests[0].url == "https://llm.example/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["schema"]["title"] == "Answer"
    assert result == Answer(answer="hello")


def test_missing_configuration_is_rejected_before_network_call() -> None:
    transport = OpenAICompatibleTransport(
        Settings(_env_file=None),
        http_transport=httpx.MockTransport(
            lambda _request: pytest.fail("network must not be called")
        ),
    )

    with pytest.raises(LLMNotConfiguredError):
        StructuredLLMClient(transport).complete_structured(
            system_prompt="Return JSON",
            user_prompt="Say hello",
            output_model=Answer,
        )


def test_timeout_is_converted_to_llm_timeout_error() -> None:
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timed out")

    with pytest.raises(LLMTimeoutError):
        run_client(timeout_handler)


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_429_and_5xx_are_retried_once(status_code: int) -> None:
    calls = 0

    def retry_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, json={"error": {"message": "retry"}})
        return response_with_content('{"answer":"recovered"}')

    result, requests = run_client(retry_handler)

    assert result.answer == "recovered"
    assert len(requests) == 2


def test_invalid_json_and_schema_violation_are_rejected() -> None:
    with pytest.raises(LLMInvalidResponseError):
        run_client(lambda _request: response_with_content("not-json"))

    with pytest.raises(LLMInvalidResponseError):
        run_client(lambda _request: response_with_content('{"wrong":"field"}'))


def test_schema_violation_is_retried_once() -> None:
    calls = 0

    def retry_schema_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return response_with_content('{"wrong":"field"}')
        return response_with_content('{"answer":"recovered"}')

    result, requests = run_client(retry_schema_handler)

    assert result.answer == "recovered"
    assert len(requests) == 2
    second_payload = json.loads(requests[1].content)
    assert "上一响应没有通过结构化校验" in second_payload["messages"][1]["content"]


def test_upstream_error_does_not_expose_api_key() -> None:
    def unauthorized_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    transport = OpenAICompatibleTransport(
        settings(),
        http_transport=httpx.MockTransport(unauthorized_handler),
    )

    with pytest.raises(LLMUpstreamError) as captured:
        StructuredLLMClient(transport).complete_structured(
            system_prompt="Return JSON",
            user_prompt="Say hello",
            output_model=Answer,
        )

    assert "test-key" not in str(captured.value)
