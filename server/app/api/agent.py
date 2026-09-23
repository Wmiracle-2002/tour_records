"""Authenticated HTTP entry point for the Travel Agent."""

import asyncio
import logging
from contextlib import suppress
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.budget import (
    AgentClientDisconnected,
    AgentCancellation,
    AgentTimeoutError,
    cancellation_context,
)
from app.agent.llm import (
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.observability import request_context
from app.agent.runtime import AgentRunResult
from app.api.auth import current_user
from app.database import get_db
from app.models import User


router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


class AgentChatRequest(BaseModel):
    """一次 Agent 对话请求。"""

    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class AgentChatResponse(BaseModel):
    """一次 Agent 对话响应。"""

    request_id: str
    answer: str


def _llm_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, LLMNotConfiguredError):
        return HTTPException(status_code=503, detail="LLM service is not configured")
    if isinstance(error, LLMTimeoutError):
        return HTTPException(status_code=504, detail="LLM service timed out")
    if isinstance(error, AgentTimeoutError):
        return HTTPException(status_code=504, detail="Agent request timed out")
    if isinstance(error, (LLMUpstreamError, LLMInvalidResponseError)):
        return HTTPException(status_code=502, detail="LLM service request failed")
    raise TypeError(f"Unsupported LLM error: {type(error).__name__}")


async def _watch_client_disconnect(
    request: Request,
    cancellation: AgentCancellation,
    request_id: str,
) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.1)
    cancellation.cancel()
    logger.info("Agent client disconnected request_id=%s", request_id)


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    payload: AgentChatRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AgentChatResponse:
    """Run one authenticated, synchronous Agent request."""
    started_at = monotonic()
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response.headers["X-Request-ID"] = request_id
    logger.info("Agent request started request_id=%s user_id=%s", request_id, user.id)
    cancellation = AgentCancellation()
    disconnect_watcher = asyncio.create_task(
        _watch_client_disconnect(request, cancellation, request_id)
    )
    try:
        with request_context(request_id), cancellation_context(cancellation):
            result = await run_in_threadpool(
                request.app.state.agent_runtime.run,
                payload.message,
                user.id,
                db,
            )
    except (
        LLMNotConfiguredError,
        LLMTimeoutError,
        AgentTimeoutError,
        LLMUpstreamError,
        LLMInvalidResponseError,
    ) as error:
        logger.warning(
            "Agent LLM failure request_id=%s type=%s detail=%s duration_ms=%.0f",
            request_id,
            type(error).__name__,
            str(error),
            (monotonic() - started_at) * 1000,
        )
        raise _llm_http_exception(error) from error
    except AgentClientDisconnected as error:
        logger.info(
            "Agent request cancelled request_id=%s duration_ms=%.0f",
            request_id,
            (monotonic() - started_at) * 1000,
        )
        raise HTTPException(status_code=499, detail="Client disconnected") from error
    except ValueError as error:
        logger.warning(
            "Agent generated an invalid response request_id=%s detail=%s duration_ms=%.0f",
            request_id,
            error,
            (monotonic() - started_at) * 1000,
        )
        raise HTTPException(
            status_code=502,
            detail="Agent generated an invalid response",
        ) from error
    finally:
        disconnect_watcher.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_watcher
    if not isinstance(result, AgentRunResult):
        logger.warning("Agent returned an invalid response request_id=%s", request_id)
        raise HTTPException(status_code=502, detail="Agent returned an invalid response")
    logger.info(
        "Agent request completed request_id=%s duration_ms=%.0f",
        request_id,
        (monotonic() - started_at) * 1000,
    )
    return AgentChatResponse(**result.model_dump())
