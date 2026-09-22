"""Structured LLM client for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.collector import ReActContext, ReActDecision
from app.core.config import Settings, get_settings


logger = logging.getLogger("footmarks.agent.llm")


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

        total_attempts = self._max_retries + 1
        output_name = output_model.__name__
        for attempt in range(total_attempts):
            started_at = monotonic()
            attempt_number = attempt + 1
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
                elapsed_ms = (monotonic() - started_at) * 1000
                logger.warning(
                    "LLM timeout stage=%s attempt=%d/%d elapsed_ms=%.0f timeout_seconds=%.1f",
                    output_name,
                    attempt_number,
                    total_attempts,
                    elapsed_ms,
                    self._timeout_seconds,
                )
                # A timeout already consumed the full request budget. Retrying it
                # here can make one Agent request exceed the mobile/API timeout.
                raise LLMTimeoutError(
                    f"LLM provider request timed out for {output_name}"
                ) from error
            except httpx.RequestError as error:
                elapsed_ms = (monotonic() - started_at) * 1000
                if attempt < self._max_retries:
                    logger.warning(
                        "LLM network failure stage=%s attempt=%d/%d elapsed_ms=%.0f retrying=true",
                        output_name,
                        attempt_number,
                        total_attempts,
                        elapsed_ms,
                    )
                    continue
                logger.warning(
                    "LLM network failure stage=%s attempt=%d/%d elapsed_ms=%.0f retrying=false",
                    output_name,
                    attempt_number,
                    total_attempts,
                    elapsed_ms,
                )
                raise LLMUpstreamError("LLM provider request failed") from error

            if response.status_code in {429, 500, 502, 503, 504}:
                elapsed_ms = (monotonic() - started_at) * 1000
                if attempt < self._max_retries:
                    logger.warning(
                        "LLM upstream retryable status stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f retrying=true",
                        output_name,
                        attempt_number,
                        total_attempts,
                        response.status_code,
                        elapsed_ms,
                    )
                    continue
                logger.warning(
                    "LLM upstream retryable status stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f retrying=false",
                    output_name,
                    attempt_number,
                    total_attempts,
                    response.status_code,
                    elapsed_ms,
                )
                raise LLMUpstreamError(
                    f"LLM provider returned HTTP {response.status_code}"
                )
            if response.status_code < 200 or response.status_code >= 300:
                logger.warning(
                    "LLM upstream status stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                    output_name,
                    attempt_number,
                    total_attempts,
                    response.status_code,
                    (monotonic() - started_at) * 1000,
                )
                raise LLMUpstreamError(
                    f"LLM provider returned HTTP {response.status_code}"
                )
            try:
                decoded = self._decode_response(response)
            except LLMInvalidResponseError:
                logger.warning(
                    "LLM invalid structured response stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                    output_name,
                    attempt_number,
                    total_attempts,
                    response.status_code,
                    (monotonic() - started_at) * 1000,
                )
                raise
            logger.info(
                "LLM completed stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                output_name,
                attempt_number,
                total_attempts,
                response.status_code,
                (monotonic() - started_at) * 1000,
            )
            return decoded

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
                logger.warning(
                    "LLM schema retry stage=%s attempt=%d/%d",
                    output_model.__name__,
                    attempt + 1,
                    self._transport.max_retries + 1,
                )
                if attempt >= self._transport.max_retries:
                    raise
            except ValidationError as error:
                logger.warning(
                    "LLM schema validation retry stage=%s attempt=%d/%d",
                    output_model.__name__,
                    attempt + 1,
                    self._transport.max_retries + 1,
                )
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
询问去过哪些城市、景点或美食时，优先使用 search_trip_history 或 search_records；只有询问旅行次数、城市数、总花费或平均评分时才使用 get_travel_summary。
根对象只能包含 tool_call 和 reason；tool_call 可以是 null，或包含 name、arguments、information_need、critical；arguments 必须是对象；information_need 只能是 history、pois、weather、routes、distances、budget 之一或 null；critical 必须是布尔值。不要使用 decision 字段包裹，不要增加其他外层字段。
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
