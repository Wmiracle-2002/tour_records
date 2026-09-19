from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agent.collector import ReActDecision, ToolCall
from app.agent.llm import (
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.models import TravelRequirement
from app.agent.observability import RecordingAgentObserver
from app.agent.runtime import AgentRuntime
from app.agent.tools.amap import AmapTransport
from app.models import Record, RecordType, Trip, User
from app.security import hash_password
from app.core.config import Settings


class FakeStructuredClient:
    """按运行阶段返回结构化结果，并记录 ReAct 上下文。"""

    def __init__(self, requirement: TravelRequirement) -> None:
        self.requirement = requirement
        self.react_contexts: list[dict[str, Any]] = []
        self._react_calls = 0

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Any],
    ) -> Any:
        if output_model is TravelRequirement:
            return self.requirement
        if output_model is ReActDecision:
            context = json.loads(user_prompt)
            self.react_contexts.append(context)
            self._react_calls += 1
            if self._react_calls == 1 and self.requirement.intent == "history_query":
                return ReActDecision(
                    tool_call=ToolCall(
                        name="search_records",
                        arguments={"city": "南京"},
                    )
                )
            return ReActDecision()
        raise AssertionError(f"Unexpected structured output: {output_model}")


class FailingStructuredClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def complete_structured(self, **_kwargs: Any) -> Any:
        raise self.error


def add_user(db: Session, username: str) -> User:
    user = User(username=username, password_hash=hash_password("test-password"))
    db.add(user)
    db.flush()
    return user


def add_trip(db: Session, user: User, city_name: str) -> Trip:
    trip = Trip(
        user_id=user.id,
        province_code="320000",
        city_code="320100",
        city_name=city_name,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
    )
    db.add(trip)
    db.flush()
    return trip


def add_record(db: Session, trip: Trip, name: str) -> None:
    db.add(
        Record(
            trip_id=trip.id,
            type=RecordType.ATTRACTION,
            name=name,
            date=date(2026, 9, 1),
        )
    )
    db.flush()


def test_runtime_builds_user_scoped_tools_and_returns_final_response(
    db_session: Session,
) -> None:
    first_user = add_user(db_session, "runtime-first")
    second_user = add_user(db_session, "runtime-second")
    first_trip = add_trip(db_session, first_user, "南京市")
    second_trip = add_trip(db_session, second_user, "上海市")
    add_record(db_session, first_trip, "中山陵")
    add_record(db_session, second_trip, "外滩")
    db_session.commit()

    client = FakeStructuredClient(TravelRequirement(intent="history_query"))
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"),
        llm_client=client,
    ).run("我去过哪些地方？", first_user.id, db_session)

    assert result.request_id
    assert "中山陵" in result.answer
    assert "外滩" not in result.answer
    assert client.react_contexts[0]["collected_info"]["history"] is None


def test_runtime_does_not_expose_unsupported_amap_tools(db_session: Session) -> None:
    client = FakeStructuredClient(TravelRequirement(intent="weather_query"))
    settings = Settings(token_secret="test-only-secret", amap_web_key="fake-key")
    amap_transport: AmapTransport = lambda _url, _params, _timeout: {"status": "1"}

    AgentRuntime(
        settings=settings,
        llm_client=client,
        amap_transport=amap_transport,
    ).run("南京天气怎么样？", 1, db_session)

    names = {item["name"] for item in client.react_contexts[0]["available_tools"]}
    assert "geocode" not in names
    assert "reverse_geocode" not in names
    assert "weather" in names


def test_runtime_passes_user_id_and_request_id_to_observer(
    db_session: Session,
) -> None:
    observer = RecordingAgentObserver()
    client = FakeStructuredClient(TravelRequirement(intent="general_query"))

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"),
        llm_client=client,
        observer=observer,
    ).run("你能做什么？", 42, db_session)

    assert observer.events
    assert all(event.request_id == result.request_id for event in observer.events)
    assert all(event.user_id == 42 for event in observer.events)


@pytest.mark.parametrize(
    "error",
    [
        LLMNotConfiguredError("not configured"),
        LLMTimeoutError("timeout"),
        LLMUpstreamError("upstream"),
        LLMInvalidResponseError("invalid response"),
    ],
)
def test_runtime_propagates_typed_llm_errors(
    db_session: Session,
    error: Exception,
) -> None:
    runtime = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"),
        llm_client=FailingStructuredClient(error),
    )

    with pytest.raises(type(error)) as raised:
        runtime.run("测试请求", 1, db_session)

    assert raised.value is error
