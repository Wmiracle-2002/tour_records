"""Structured LLM client for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.collector import ReActContext, ReActDecision
from app.core.config import Settings, get_settings


class LLMError(RuntimeError):
    """Base error for LLM configuration, transport, and output failures."""


class LLMNotConfiguredError(LLMError):
    """The server does not have enough LLM configuration to make a request."""


class LLMTimeoutError(LLMError):
    """The LLM provider did not respond within the configured timeout."""


class LLMUpstreamError(LLMError):
    """The LLM provider returned an HTTP or transport failure."""


class LLMInvalidResponseError(LLMError):
    """The LLM provider returned a response outside the structured contract."""


T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleTransport:
    """Send one structured request to an OpenAI-compatible API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        current_settings = settings or get_settings()
        self._base_url = (current_settings.llm_base_url or "").rstrip("/")
        self._api_key = current_settings.llm_api_key
        self._model = current_settings.llm_model
        self._timeout_seconds = current_settings.llm_timeout_seconds
        self._max_retries = current_settings.llm_max_retries
        self._client = httpx.Client(
            timeout=self._timeout_seconds,
            transport=http_transport,
        )

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> dict[str, Any]:
        self._ensure_configured()
        request_payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": output_model.model_json_schema(),
                },
            },
        }

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
            except httpx.TimeoutException as error:
                if attempt < self._max_retries:
                    continue
                raise LLMTimeoutError("LLM provider request timed out") from error
            except httpx.RequestError as error:
                if attempt < self._max_retries:
                    continue
                raise LLMUpstreamError("LLM provider request failed") from error

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt < self._max_retries:
                    continue
                raise LLMUpstreamError(
                    f"LLM provider returned HTTP {response.status_code}"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise LLMUpstreamError(
                    f"LLM provider returned HTTP {response.status_code}"
                )
            return self._decode_response(response)

        raise LLMUpstreamError("LLM provider request failed")

    def close(self) -> None:
        self._client.close()

    @property
    def max_retries(self) -> int:
        """Return the configured retry count for transient or invalid output."""
        return self._max_retries

    def _ensure_configured(self) -> None:
        if not self._base_url or not self._api_key or not self._model:
            raise LLMNotConfiguredError("LLM service is not configured")

    @staticmethod
    def _decode_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response_payload = response.json()
            content = response_payload["choices"][0]["message"]["content"]
            decoded = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMInvalidResponseError(
                "LLM provider returned an invalid structured response"
            ) from error
        if not isinstance(decoded, dict):
            raise LLMInvalidResponseError(
                "LLM structured response must be a JSON object"
            )
        return decoded


class StructuredLLMClient:
    """Validate provider JSON against the requested Pydantic model."""

    def __init__(self, transport: OpenAICompatibleTransport) -> None:
        self._transport = transport

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        for attempt in range(self._transport.max_retries + 1):
            current_user_prompt = user_prompt
            if attempt > 0:
                current_user_prompt += (
                    "\n\n上一响应没有通过结构化校验。请重新输出，严格遵守 system prompt，"
                    "只返回符合目标 Schema 的 JSON 对象，不要输出解释或额外包装字段。"
                )
            try:
                payload = self._transport.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=current_user_prompt,
                    output_model=output_model,
                )
                return output_model.model_validate(payload)
            except LLMInvalidResponseError:
                if attempt >= self._transport.max_retries:
                    raise
            except ValidationError as error:
                if attempt >= self._transport.max_retries:
                    raise LLMInvalidResponseError(
                        "LLM structured response failed schema validation"
                    ) from error
        raise LLMInvalidResponseError("LLM structured response failed")


REACT_DECISION_SYSTEM_PROMPT = """
你是旅行 Agent 的 ReAct 信息收集决策器。

输入包含用户需求、当前信息状态、已经收集的结构化信息和可用 Tool。
每轮最多返回一个 Tool Call；如果信息已经足够，返回 null Tool Call。
只能选择 available_tools 中存在的 Tool，并使用它的参数格式。
根对象只能包含 tool_call 和 reason；tool_call 可以是 null，或包含 name、arguments、information_need、critical；arguments 必须是对象。不要使用 decision 字段包裹，不要增加其他外层字段。
不要输出思维链或隐藏推理；reason 只允许是一句简短的操作说明。
只返回符合 ReActDecision 的结构化 JSON。
""".strip()


class LLMReActDecisionClient:
    """Use structured LLM output to make one bounded ReAct decision."""

    def __init__(self, client: StructuredLLMClient) -> None:
        self._client = client

    def decide(self, context: ReActContext) -> ReActDecision:
        decision = self._client.complete_structured(
            system_prompt=REACT_DECISION_SYSTEM_PROMPT,
            user_prompt=context.model_dump_json(indent=2),
            output_model=ReActDecision,
        )
        if decision.tool_call is not None:
            allowed = {tool.name for tool in context.available_tools}
            if decision.tool_call.name not in allowed:
                raise LLMInvalidResponseError("LLM selected an unavailable tool")
        return decision
