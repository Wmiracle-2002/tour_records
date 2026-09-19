"""Structured LLM client for OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

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
        payload = self._transport.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
        )
        try:
            return output_model.model_validate(payload)
        except ValidationError as error:
            raise LLMInvalidResponseError(
                "LLM structured response failed schema validation"
            ) from error
