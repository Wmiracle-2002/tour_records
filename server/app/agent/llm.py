"""Structured LLM client for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
import logging
import socket
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from app.agent.budget import check_llm_budget, current_cancellation, current_llm_timeout_seconds
from app.agent.collector import ReActContext, ReActDecision
from app.agent.observability import current_request_id
from app.core.config import Settings, get_settings
from app.agent.quota import TokenQuota, current_quota_user
from app.database import create_database_engine
from sqlalchemy.orm import sessionmaker


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


class LLMOutputLimitError(LLMInvalidResponseError):
    """The provider exhausted its output limit; repeating the same call is costly."""


@contextmanager
def _stream_deadline(response: httpx.Response, deadline: float):
    """Interrupt real sockets even if a provider trickles an unfinished SSE line."""
    stopped = Event()
    cancellation = current_cancellation()
    aborted: list[Exception] = []

    def watch() -> None:
        while not stopped.wait(min(0.05, max(0.001, deadline - monotonic()))):
            try:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                if monotonic() < deadline:
                    continue
                raise LLMTimeoutError("LLM stream exceeded request deadline")
            except Exception as error:
                aborted.append(error)
                # HTTPX exposes its underlying stream through response extensions.
                # shutdown wakes a blocking SSL read; close alone may not wake it.
                try:
                    network = response.extensions.get("network_stream")
                    connection = network.get_extra_info("socket") if network is not None else None
                    if connection is not None:
                        connection.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass
                try:
                    response.close()
                except Exception:
                    pass
                return

    watcher = Thread(target=watch, daemon=True, name="agent-stream-deadline")
    watcher.start()
    try:
        yield
    except Exception:
        if aborted:
            raise aborted[0] from None
        raise
    else:
        if aborted:
            raise aborted[0]
    finally:
        stopped.set()
        watcher.join(timeout=0.2)


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
        self._thinking_mode = current_settings.llm_thinking_mode
        self._structured_output_mode = current_settings.llm_structured_output_mode
        self._timeout_seconds = current_settings.llm_timeout_seconds
        self._max_retries = current_settings.llm_max_retries
        self._max_output_tokens = current_settings.llm_max_output_tokens
        self._quota_engine = (
            create_database_engine(current_settings.database_url)
            if current_settings.token_quota_enabled else None
        )
        self._quota = (
            TokenQuota(sessionmaker(bind=self._quota_engine), current_settings.default_monthly_token_limit)
            if self._quota_engine is not None else None
        )
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
        system_prompt, response_format = self._structured_format(system_prompt, output_model)
        request_payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
        }

        self._apply_generation_options(request_payload)
        total_attempts = self._max_retries + 1
        output_name = output_model.__name__
        request_id = current_request_id() or "unknown"
        for attempt in range(total_attempts):
            check_llm_budget()
            started_at = monotonic()
            attempt_number = attempt + 1
            timeout_seconds = (
                current_llm_timeout_seconds() or self._timeout_seconds
            )
            try:
                response = self._post_with_quota(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                    timeout=timeout_seconds,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            except httpx.TimeoutException as error:
                elapsed_ms = (monotonic() - started_at) * 1000
                logger.warning(
                    "LLM timeout request_id=%s stage=%s attempt=%d retrying=false elapsed_ms=%.0f timeout_seconds=%.1f",
                    request_id,
                    output_name,
                    attempt_number,
                    elapsed_ms,
                    timeout_seconds,
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
                        "LLM network failure request_id=%s stage=%s attempt=%d/%d elapsed_ms=%.0f retrying=true",
                        request_id,
                        output_name,
                        attempt_number,
                        total_attempts,
                        elapsed_ms,
                    )
                    continue
                logger.warning(
                    "LLM network failure request_id=%s stage=%s attempt=%d/%d elapsed_ms=%.0f retrying=false",
                    request_id,
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
                        "LLM upstream retryable status request_id=%s stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f retrying=true",
                        request_id,
                        output_name,
                        attempt_number,
                        total_attempts,
                        response.status_code,
                        elapsed_ms,
                    )
                    continue
                logger.warning(
                    "LLM upstream retryable status request_id=%s stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f retrying=false",
                    request_id,
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
                    "LLM upstream status request_id=%s stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                    request_id,
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
                check_llm_budget()
                decoded = self._decode_response(response, output_name,
                                                (monotonic() - started_at) * 1000)
            except LLMInvalidResponseError:
                logger.warning(
                    "LLM invalid structured response request_id=%s stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                    request_id,
                    output_name,
                    attempt_number,
                    total_attempts,
                    response.status_code,
                    (monotonic() - started_at) * 1000,
                )
                raise
            logger.info(
                "LLM completed request_id=%s stage=%s attempt=%d/%d status=%d elapsed_ms=%.0f",
                request_id,
                output_name,
                attempt_number,
                total_attempts,
                response.status_code,
                (monotonic() - started_at) * 1000,
            )
            return decoded

        raise LLMUpstreamError("LLM provider request failed")

    def complete_json_stream(
        self, *, system_prompt: str, user_prompt: str,
        output_model: type[T], on_delta: Callable[[str], None],
    ) -> dict[str, Any]:
        self._ensure_configured()
        system_prompt, response_format = self._structured_format(system_prompt, output_model)
        request_payload = {
            "model": self._model,
            "temperature": 0,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
        }
        self._apply_generation_options(request_payload)
        request_payload["stream_options"] = {"include_usage": True}
        check_llm_budget()
        started_at = monotonic()
        timeout = current_llm_timeout_seconds() or self._timeout_seconds
        deadline = started_at + timeout
        quota_call = self._reserve(system_prompt, user_prompt)
        usage: tuple[int, int] | None = None
        usage_details: dict[str, Any] | None = None
        finish_reason = None
        parts: list[str] = []
        content_size = 0
        reasoning_size = 0
        first_content_ms = None
        completed = False
        try:
            with self._client.stream(
                "POST", f"{self._base_url}/chat/completions",
                headers={
                    "Accept": "text/event-stream",
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload, timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    raise LLMUpstreamError(
                        f"LLM provider returned HTTP {response.status_code}"
                    )
                with _stream_deadline(response, deadline):
                    for line in response.iter_lines():
                        check_llm_budget()
                        if monotonic() >= deadline:
                            raise LLMTimeoutError("LLM stream exceeded request deadline")
                        if not line.startswith("data: "):
                            continue
                        payload = line.removeprefix("data: ")
                        if payload == "[DONE]":
                            completed = True
                            break
                        try:
                            chunk = json.loads(payload)
                            if isinstance(chunk.get("usage"), dict):
                                usage_details = chunk["usage"]
                                usage = self._usage_values(usage_details) or usage
                            if chunk.get("choices") == []:
                                continue
                            choice = chunk["choices"][0]
                            finish_reason = choice.get("finish_reason") or finish_reason
                            fields = choice["delta"]
                            reasoning = fields.get("reasoning_content")
                            if isinstance(reasoning, str):
                                reasoning_size += len(reasoning)
                            delta = fields.get("content")
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
                            raise LLMInvalidResponseError("LLM stream chunk is invalid") from error
                        if delta is None:
                            continue
                        if not isinstance(delta, str):
                            raise LLMInvalidResponseError("LLM stream content is invalid")
                        if delta and first_content_ms is None:
                            first_content_ms = (monotonic() - started_at) * 1000
                        parts.append(delta)
                        content_size += len(delta)
                        if content_size > 2_000_000:
                            raise LLMInvalidResponseError("LLM stream is too large")
                        on_delta(delta)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            if quota_call is not None and self._quota is not None:
                self._quota.release(quota_call)
                quota_call = None
            raise LLMUpstreamError("LLM provider connection failed") from error
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(
                f"LLM provider request timed out for {output_model.__name__}"
            ) from error
        except httpx.RequestError as error:
            raise LLMUpstreamError("LLM provider request failed") from error
        finally:
            self._settle(quota_call, usage)
            self._log_response_metadata(output_model.__name__, usage_details, finish_reason,
                                        content_size, reasoning_size, first_content_ms,
                                        (monotonic() - started_at) * 1000)
        if finish_reason == "length":
            raise LLMOutputLimitError("LLM response reached output token limit")
        if not completed:
            raise LLMInvalidResponseError("LLM stream ended before completion")
        try:
            decoded = json.loads("".join(parts))
        except ValueError as error:
            raise LLMInvalidResponseError("LLM stream did not contain valid JSON") from error
        if not isinstance(decoded, dict):
            raise LLMInvalidResponseError("LLM structured response must be a JSON object")
        logger.info(
            "LLM completed request_id=%s stage=%s stream=true elapsed_ms=%.0f",
            current_request_id() or "unknown", output_model.__name__,
            (monotonic() - started_at) * 1000,
        )
        return decoded

    def _apply_generation_options(self, payload: dict[str, Any]) -> None:
        payload["max_tokens"] = self._max_output_tokens
        if self._thinking_mode != "auto":
            payload["enable_thinking"] = self._thinking_mode == "enabled"
            return
        host = urlparse(self._base_url).hostname or ""
        dashscope = host == "dashscope.aliyuncs.com" or host.endswith(".maas.aliyuncs.com")
        supported_deepseek = self._model in {
            "deepseek-v4-pro", "deepseek-v4-pro-0813", "deepseek-v4-flash-0731",
        }
        if self._model.startswith("qwen3.7-") or (dashscope and supported_deepseek):
            payload["enable_thinking"] = False

    @staticmethod
    def _log_response_metadata(stage, usage, finish_reason, content_chars, reasoning_chars=0,
                               first_content_ms=None, elapsed_ms=0) -> None:
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, dict) else {}
        reason = finish_reason if isinstance(finish_reason, str) and finish_reason in {
            "stop", "length", "tool_calls", "content_filter", "function_call",
        } else (None if finish_reason is None else "unknown")
        def count(value):
            return value if type(value) is int and value >= 0 else None
        logger.info(
            "LLM response metadata request_id=%s stage=%s finish_reason=%s prompt_tokens=%s "
            "completion_tokens=%s reasoning_tokens=%s content_chars=%s reasoning_chars=%s "
            "first_content_ms=%s elapsed_ms=%.0f",
            current_request_id() or "unknown", stage, reason, count(usage.get("prompt_tokens")),
            count(usage.get("completion_tokens")), count(details.get("reasoning_tokens")),
            content_chars, reasoning_chars, first_content_ms, elapsed_ms,
        )

    def close(self) -> None:
        self._client.close()
        if self._quota_engine is not None:
            self._quota_engine.dispose()

    def _reserve(self, system_prompt: str, user_prompt: str) -> str | None:
        user_id = current_quota_user()
        if self._quota is None or user_id is None:
            return None
        conservative_input = len(system_prompt.encode("utf-8")) + len(user_prompt.encode("utf-8"))
        return self._quota.reserve(user_id, conservative_input + self._max_output_tokens)

    def _settle(self, call_id: str | None, usage: tuple[int, int] | None) -> None:
        if call_id is not None and self._quota is not None:
            self._quota.settle(
                call_id,
                input_tokens=usage[0] if usage is not None else None,
                output_tokens=usage[1] if usage is not None else None,
            )

    @staticmethod
    def _usage_values(value: object) -> tuple[int, int] | None:
        if not isinstance(value, dict):
            return None
        prompt = value.get("prompt_tokens")
        completion = value.get("completion_tokens")
        if type(prompt) is int and type(completion) is int and prompt >= 0 and completion >= 0:
            return prompt, completion
        return None

    def _post_with_quota(self, url: str, *, system_prompt: str, user_prompt: str, **kwargs) -> httpx.Response:
        call_id = self._reserve(system_prompt, user_prompt)
        usage = None
        try:
            check_llm_budget()
            timeout = kwargs["timeout"]
            remaining = current_llm_timeout_seconds()
            deadline = monotonic() + min(timeout, remaining if remaining is not None else timeout)
            with self._client.stream("POST", url, **kwargs) as response:
                with _stream_deadline(response, deadline):
                    response.read()
            try:
                usage = self._usage_values(response.json().get("usage"))
            except (ValueError, AttributeError):
                pass
            check_llm_budget()
            return response
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if call_id is not None and self._quota is not None:
                self._quota.release(call_id)
                call_id = None
            raise
        finally:
            self._settle(call_id, usage)

    @property
    def max_retries(self) -> int:
        """Return the configured retry count for transient or invalid output."""
        return self._max_retries

    def _structured_format(self, system_prompt: str, output_model: type[T]) -> tuple[str, dict[str, Any]]:
        schema = output_model.model_json_schema()
        if self._structured_output_mode == "json_object":
            return (
                system_prompt + "\n\n只输出符合以下 JSON Schema 的 JSON 对象：\n"
                + json.dumps(schema, ensure_ascii=False),
                {"type": "json_object"},
            )
        return system_prompt, {"type": "json_schema", "json_schema": {
            "name": output_model.__name__, "strict": True, "schema": schema,
        }}

    def _ensure_configured(self) -> None:
        if not self._base_url or not self._api_key or not self._model:
            raise LLMNotConfiguredError("LLM service is not configured")

    def _decode_response(self, response: httpx.Response, stage: str, elapsed_ms: float) -> dict[str, Any]:
        try:
            response_payload = response.json()
            choice = response_payload["choices"][0]
            content = choice["message"]["content"]
            reasoning = choice["message"].get("reasoning_content")
            self._log_response_metadata(stage, response_payload.get("usage"), choice.get("finish_reason"),
                                        len(content) if isinstance(content, str) else 0,
                                        len(reasoning) if isinstance(reasoning, str) else 0,
                                        elapsed_ms=elapsed_ms)
            if choice.get("finish_reason") == "length":
                raise LLMOutputLimitError("LLM response reached output token limit")
            decoded = json.loads(content)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
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

    def complete_structured_stream(
        self, *, system_prompt: str, user_prompt: str,
        output_model: type[T], on_delta: Callable[[str], None],
    ) -> T:
        payload = self._transport.complete_json_stream(
            system_prompt=system_prompt, user_prompt=user_prompt,
            output_model=output_model, on_delta=on_delta,
        )
        try:
            return output_model.model_validate(payload)
        except ValidationError as error:
            raise LLMInvalidResponseError(
                "LLM structured response failed schema validation"
            ) from error

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
            except LLMOutputLimitError:
                raise
            except LLMInvalidResponseError:
                logger.warning(
                    "LLM schema retry request_id=%s stage=%s attempt=%d/%d",
                    current_request_id() or "unknown",
                    output_model.__name__,
                    attempt + 1,
                    self._transport.max_retries + 1,
                )
                if attempt >= self._transport.max_retries:
                    raise
            except ValidationError as error:
                logger.warning(
                    "LLM schema validation retry request_id=%s stage=%s attempt=%d/%d",
                    current_request_id() or "unknown",
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
只能选择 available_tools 中存在的 Tool。每个 Tool 的 parameters 是执行时的硬 Schema，arguments 必须严格符合它；示例只帮助理解，不能替代 Schema。
如果上下文包含 tool_argument_error，必须重试其中指定的同一个 Tool，只修正 invalid_fields 和 missing_fields，不能切换 Tool，也不能添加 Schema 外字段。
询问去过哪些城市、景点或美食时，优先使用 search_trip_history 或 search_records；只有询问旅行次数、城市数、总花费或平均评分时才使用 get_travel_summary。
根对象只能包含 tool_call 和 reason；tool_call 可以是 null，或只包含 name、arguments；arguments 必须是对象。信息归属和重要程度由系统确定，不要输出 information_need 或 critical。不要使用 decision 字段包裹，不要增加其他字段。
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
