"""Structured Agent events for debugging without exposing hidden reasoning."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Literal, Protocol

from pydantic import BaseModel, Field

from app.agent.models import InformationStatus
from app.core.request_context import current_request_id, request_context


AgentEventName = Literal[
    "stage_started",
    "stage_completed",
    "requirement_ready",
    "tool_started",
    "tool_argument_retry_started",
    "tool_argument_retry_completed",
    "tool_completed",
    "information_updated",
    "itinerary_generated",
    "validation_started",
    "validation_failed",
    "itinerary_revised",
    "validation_completed",
    "final_response_ready",
]


class AgentEvent(BaseModel):
    """允许记录的运行事件；包含 Tool 参数，不包含 prompt 或原始响应。"""

    event: AgentEventName
    request_id: str = Field(min_length=1)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    user_id: str | int | None = None
    intent: str | None = None
    node_name: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    executed_tool_arguments: dict[str, Any] | None = None
    tool_duration_ms: float | None = Field(default=None, ge=0)
    tool_success: bool | None = None
    information_status: dict[str, str] | None = None
    react_round: int | None = Field(default=None, ge=0)
    validation_round: int | None = Field(default=None, ge=0)
    validation_issue_type: str | None = None
    stage_name: str | None = None
    stage_duration_ms: float | None = Field(default=None, ge=0)
    stage_status: str | None = None
    total_duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    argument_retry_attempt: int | None = Field(default=None, ge=1)
    invalid_argument_fields: list[str] | None = None
    missing_argument_fields: list[str] | None = None


class AgentObserver(Protocol):
    """Agent 运行事件接收器。"""

    def record(self, event: AgentEvent) -> None:
        ...


class NullAgentObserver:
    """默认空观察器，避免业务代码必须判断日志是否启用。"""

    def record(self, _event: AgentEvent) -> None:
        return None


class RecordingAgentObserver:
    """测试用观察器，按产生顺序保留结构化事件。"""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def record(self, event: AgentEvent) -> None:
        self.events.append(event)


class StructuredLoggingObserver:
    """将事件序列化为 JSON 日志，不写入业务原始数据。"""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("footmarks.agent")

    def record(self, event: AgentEvent) -> None:
        self._logger.info(event.model_dump_json(exclude_none=True))


_STREAM_EVENT_SINK: ContextVar[Callable[[AgentEvent], None] | None] = ContextVar(
    "agent_stream_event_sink", default=None
)
_PREVIEW_SINK: ContextVar[Callable[[str], None] | None] = ContextVar(
    "agent_preview_sink", default=None
)


@contextmanager
def stream_event_sink(sink: Callable[[AgentEvent], None]) -> Iterator[None]:
    token = _STREAM_EVENT_SINK.set(sink)
    try:
        yield
    finally:
        _STREAM_EVENT_SINK.reset(token)


@contextmanager
def preview_sink(sink: Callable[[str], None]) -> Iterator[None]:
    token = _PREVIEW_SINK.set(sink)
    try:
        yield
    finally:
        _PREVIEW_SINK.reset(token)


def current_preview_sink() -> Callable[[str], None] | None:
    return _PREVIEW_SINK.get()


class StreamingAgentObserver:
    """Preserve structured logs while forwarding only the current request's events."""

    def __init__(self, observer: AgentObserver) -> None:
        self._observer = observer
        self._sink = _STREAM_EVENT_SINK.get()

    def record(self, event: AgentEvent) -> None:
        self._observer.record(event)
        if self._sink is not None:
            self._sink(event)


def current_stream_event_sink() -> Callable[[AgentEvent], None] | None:
    return _STREAM_EVENT_SINK.get()


def information_status_snapshot(status: InformationStatus) -> dict[str, str]:
    """只保留信息需求的公开状态，不记录原因或外部响应内容。"""
    return {
        name: requirement.status
        for name in InformationStatus.model_fields
        if (requirement := getattr(status, name)) is not None
    }


def emit_event(
    observer: AgentObserver | None,
    *,
    event: AgentEventName,
    request_id: str,
    user_id: str | int | None = None,
    intent: str | None = None,
    node_name: str | None = None,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    executed_tool_arguments: dict[str, Any] | None = None,
    tool_duration_ms: float | None = None,
    tool_success: bool | None = None,
    information_status: dict[str, str] | None = None,
    react_round: int | None = None,
    validation_round: int | None = None,
    validation_issue_type: str | None = None,
    stage_name: str | None = None,
    stage_duration_ms: float | None = None,
    stage_status: str | None = None,
    total_duration_ms: float | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    argument_retry_attempt: int | None = None,
    invalid_argument_fields: list[str] | None = None,
    missing_argument_fields: list[str] | None = None,
) -> None:
    """发送事件；观察器故障不能影响 Agent 业务流程。"""
    if observer is None:
        return
    record = AgentEvent(
        event=event,
        request_id=request_id or "unknown",
        user_id=user_id,
        intent=intent,
        node_name=node_name,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        executed_tool_arguments=executed_tool_arguments,
        tool_duration_ms=tool_duration_ms,
        tool_success=tool_success,
        information_status=information_status,
        react_round=react_round,
        validation_round=validation_round,
        validation_issue_type=validation_issue_type,
        stage_name=stage_name,
        stage_duration_ms=stage_duration_ms,
        stage_status=stage_status,
        total_duration_ms=total_duration_ms,
        error_code=error_code,
        error_message=error_message,
        argument_retry_attempt=argument_retry_attempt,
        invalid_argument_fields=invalid_argument_fields,
        missing_argument_fields=missing_argument_fields,
    )
    try:
        observer.record(record)
    except Exception:
        logging.getLogger(__name__).exception("Agent observer failed")
