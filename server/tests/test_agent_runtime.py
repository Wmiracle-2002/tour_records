from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.collector import ReActDecision, ToolCall
from app.agent.llm import (
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.models import TravelRequirement
from app.agent.observability import RecordingAgentObserver, request_context
from app.agent.runtime import AgentRuntime
from app.agent.tools.amap import AmapTransport
from app.models import (
    AgentConversationMemory,
    AgentConversationSummary,
    AgentToolResult,
    AgentToolRun,
    ChatConversation,
    ChatMessage,
    Record,
    RecordType,
    Trip,
    User,
    UserPreference,
)
from app.agent.memory import ConversationSummaryOutput
from app.security import hash_password
from app.core.config import Settings


class FakeStructuredClient:
    """按运行阶段返回结构化结果，并记录 ReAct 上下文。"""

    def __init__(self, requirement: TravelRequirement) -> None:
        self.requirement = requirement
        self.react_contexts: list[dict[str, Any]] = []
        self.requirement_prompts: list[str] = []
        self._react_calls = 0

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Any],
    ) -> Any:
        if output_model is TravelRequirement:
            self.requirement_prompts.append(user_prompt)
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
    conversation = ChatConversation(id="runtime-memory-thread", user_id=first_user.id)
    db_session.add(conversation)
    db_session.flush()
    user_message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="我去过哪些地方？",
        status="pending",
    )
    db_session.add(user_message)
    db_session.commit()

    client = FakeStructuredClient(TravelRequirement(intent="history_query"))
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"),
        llm_client=client,
    ).run(
        "我去过哪些地方？",
        first_user.id,
        db_session,
        conversation_id=conversation.id,
        user_message_id=user_message.id,
    )

    assert result.request_id
    assert "中山陵" in result.answer
    assert "外滩" not in result.answer
    assert client.react_contexts[0]["collected_info"]["history"] is None
    tool_run = db_session.scalar(select(AgentToolRun))
    assert tool_run is not None
    assert tool_run.conversation_id == conversation.id
    assert tool_run.source_message_id == user_message.id
    assert tool_run.tool_name == "search_records"
    assert tool_run.arguments_json == {"city": "南京"}
    assert tool_run.status == "completed"
    assert db_session.get(AgentToolResult, tool_run.id) is not None
    saved_state = db_session.get(AgentConversationMemory, conversation.id)
    assert saved_state is not None
    assert saved_state.state_json["last_intent"] == "history_query"


def test_runtime_inherits_city_for_follow_up_and_persists_session_state(
    db_session: Session,
) -> None:
    user = add_user(db_session, "runtime-follow-up")
    conversation = ChatConversation(id="runtime-follow-up-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    earlier_user = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="推荐南京景点",
        status="completed",
    )
    db_session.add(earlier_user)
    db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="可以看看中山陵。",
            status="completed",
            in_reply_to_message_id=earlier_user.id,
        )
    )
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="美食呢？",
        status="pending",
    )
    db_session.add(current)
    db_session.add(
        AgentConversationMemory(
            conversation_id=conversation.id,
            state_json={"city": "南京", "topic": "推荐南京景点"},
        )
    )
    db_session.commit()

    client = FakeStructuredClient(
        TravelRequirement(intent="poi_recommendation", poi_kind="food")
    )
    AgentRuntime(
        settings=Settings(token_secret="test-only-secret"),
        llm_client=client,
    ).run(
        current.content,
        user.id,
        db_session,
        conversation_id=conversation.id,
        user_message_id=current.id,
    )

    assert "推荐南京景点" in client.requirement_prompts[0]
    saved_state = db_session.get(AgentConversationMemory, conversation.id)
    assert saved_state is not None
    assert saved_state.state_json["city"] == "南京"
    assert saved_state.state_json["last_intent"] == "poi_recommendation"
    assert saved_state.state_json["topic"] == "推荐南京景点"
    assert saved_state.state_json["subtopic"] == "美食呢？"


def test_runtime_loads_account_preferences_in_a_different_conversation(
    db_session: Session,
) -> None:
    user = add_user(db_session, "runtime-long-term-preference")
    db_session.add(UserPreference(
        user_id=user.id, category="food_restriction", content="不吃辣"
    ))
    conversation = ChatConversation(id="runtime-preference-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="推荐南京美食",
        status="pending",
    )
    db_session.add(message)
    db_session.commit()
    client = FakeStructuredClient(TravelRequirement(
        intent="poi_recommendation", city="南京", poi_kind="food"
    ))

    AgentRuntime(
        settings=Settings(token_secret="test-only-secret"), llm_client=client
    ).run(
        message.content, user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )

    assert "不吃辣" in client.requirement_prompts[0]


def test_runtime_summarizes_long_history_before_analyzing_current_message(
    db_session: Session,
) -> None:
    user = add_user(db_session, "runtime-summary")
    conversation = ChatConversation(id="runtime-summary-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    for index in range(20):
        user_message = ChatMessage(
            conversation_id=conversation.id,
            role="user",
            content=f"南京旅行条件 {index} " + ("保留预算与慢节奏；" * 55),
            status="completed",
        )
        db_session.add(user_message)
        db_session.flush()
        db_session.add(
            ChatMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=f"当时推荐内容 {index} " + ("南京的历史地点与美食；" * 45),
                status="completed",
                in_reply_to_message_id=user_message.id,
            )
        )
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="回到之前的南京旅行安排",
        status="pending",
    )
    db_session.add(current)
    db_session.add(
        AgentConversationMemory(
            conversation_id=conversation.id,
            state_json={"city": "南京", "topic": "南京旅行"},
        )
    )
    db_session.commit()

    class SummaryClient(FakeStructuredClient):
        summary_inputs: list[str]

        def __init__(self, requirement):
            super().__init__(requirement)
            self.summary_inputs = []

        def complete_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model is ConversationSummaryOutput:
                self.summary_inputs.append(user_prompt)
                return ConversationSummaryOutput(summary="南京旅行预算和慢节奏偏好。")
            return super().complete_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=output_model,
            )

    client = SummaryClient(
        TravelRequirement(intent="budget_query", city="南京", duration_days=3)
    )
    AgentRuntime(
        settings=Settings(token_secret="test-only-secret"), llm_client=client
    ).run(
        current.content,
        user.id,
        db_session,
        conversation_id=conversation.id,
        user_message_id=current.id,
    )

    summaries = list(
        db_session.scalars(
            select(AgentConversationSummary).where(
                AgentConversationSummary.conversation_id == conversation.id
            )
        ).all()
    )
    assert client.summary_inputs
    assert summaries
    assert "南京旅行预算和慢节奏偏好" in client.requirement_prompts[0]
    assert all("message_id=" in source for source in client.summary_inputs)


def test_runtime_weather_skips_llm_tool_decision(db_session: Session) -> None:
    client = FakeStructuredClient(TravelRequirement(intent="weather_query", city="南京"))
    settings = Settings(token_secret="test-only-secret", amap_web_key="fake-key")
    amap_transport: AmapTransport = lambda _url, _params, _timeout: {"status": "1"}

    result = AgentRuntime(
        settings=settings,
        llm_client=client,
        amap_transport=amap_transport,
    ).run("南京天气怎么样？", 1, db_session)

    assert client.react_contexts == []
    assert "天气信息查询失败" in result.answer


def test_runtime_records_district_and_weather_calls(db_session: Session) -> None:
    user = add_user(db_session, "runtime-direct-weather")
    conversation = ChatConversation(id="runtime-direct-weather-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="南京现在天气怎么样？",
        status="pending",
    )
    db_session.add(message)
    db_session.commit()
    client = FakeStructuredClient(TravelRequirement(
        intent="weather_query", city="南京", weather_time_kind="realtime"
    ))

    def transport(url, _params, _timeout):
        if url.endswith("/v3/config/district"):
            return {"status": "1", "districts": [{
                "name": "南京市", "level": "city", "adcode": "320100"
            }]}
        if url.endswith("/v3/weather/weatherInfo"):
            return {"status": "1", "lives": [{
                "adcode": "320100", "city": "南京市", "weather": "晴",
                "temperature": "24", "reporttime": "2026-09-27 10:00:00",
            }]}
        raise AssertionError(url)

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client, amap_transport=transport,
    ).run(
        message.content, user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )

    assert "晴" in result.answer
    runs = list(db_session.scalars(select(AgentToolRun)).all())
    assert [run.tool_name for run in runs] == [
        "administrative_division_lookup", "weather"
    ]
    weather_result = db_session.get(AgentToolResult, runs[1].id)
    assert weather_result.result_json["lives"][0]["weather"] == "晴"


def test_runtime_budget_question_uses_local_estimate_without_react(db_session: Session) -> None:
    client = FakeStructuredClient(TravelRequirement(
        intent="budget_query", city="南京", duration_days=3, travelers=2,
    ))
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"), llm_client=client,
    ).run("两个人去南京三天要花多少钱？", 1, db_session)
    assert "人民币" in result.answer
    assert "估算" in result.answer
    assert "2 人" in result.answer and "3 天" in result.answer
    assert client.react_contexts == []


def test_runtime_budget_question_without_days_asks_for_duration(db_session: Session) -> None:
    client = FakeStructuredClient(TravelRequirement(intent="budget_query", city="南京"))
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret"), llm_client=client,
    ).run("去南京需要多少钱？", 1, db_session)
    assert "天数" in result.answer
    assert client.react_contexts == []


def test_runtime_planning_message_survives_itinerary_llm_timeout(db_session: Session) -> None:
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)

    class PlanningClient(FakeStructuredClient):
        def complete_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model is ReActDecision:
                self.react_contexts.append(json.loads(user_prompt))
                self._react_calls += 1
                if self._react_calls > 1:
                    return ReActDecision()
                return ReActDecision(tool_call=ToolCall(
                    name="keyword_search",
                    arguments={"city": "南京", "kind": "attraction"},
                ))
            if output_model.__name__ == "Itinerary":
                raise LLMTimeoutError("provider timeout")
            return super().complete_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=output_model,
            )

    def transport(url: str, _params: dict[str, str], _timeout: float) -> dict:
        assert url.endswith("/v3/place/text")
        return {"status": "1", "pois": [{
            "id": "A1", "name": "中山陵", "type": "风景名胜",
            "cityname": "南京市", "adcode": "320102",
            "location": "118.858000,32.058000",
        }]}

    client = PlanningClient(requirement)
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client, amap_transport=transport,
    ).run("帮我规划南京一日游", 1, db_session)
    assert "第1天" in result.answer
    assert "中山陵" in result.answer
    assert "暂无可靠推荐" in result.answer
    assert client.react_contexts == []


def test_runtime_planning_collects_both_attractions_and_food(db_session: Session) -> None:
    user = add_user(db_session, "runtime-direct-planning")
    conversation = ChatConversation(id="runtime-direct-planning-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id, role="user", content="规划南京一日游", status="pending"
    )
    db_session.add(message)
    db_session.commit()
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)

    class PlanningClient(FakeStructuredClient):
        def complete_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model is ReActDecision:
                return ReActDecision(tool_call=ToolCall(
                    name="keyword_search", arguments={"city": "南京", "kind": "attraction"},
                ))
            if output_model.__name__ == "Itinerary":
                return {"days": [{"day_number": 1, "items": [
                    {"poi_id": "A1", "poi_name": "中山陵", "period": "morning", "activity_type": "ATTRACTION"},
                    {"poi_id": "F1", "poi_name": "鸭血粉丝汤", "period": "lunch", "activity_type": "FOOD"},
                ]}]}
            return super().complete_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=output_model,
            )

    keywords: list[str] = []

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        assert url.endswith("/v3/place/text")
        keywords.append(params["keywords"])
        food = params["keywords"] == "美食"
        return {"status": "1", "pois": [{
            "id": "F1" if food else "A1",
            "name": "鸭血粉丝汤" if food else "中山陵",
            "type": "餐饮服务;中餐厅" if food else "风景名胜",
            "cityname": "南京市", "adcode": "320102",
            "location": "118.800000,32.050000" if food else "118.858000,32.058000",
        }]}

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=PlanningClient(requirement), amap_transport=transport,
    ).run(
        "规划南京一日游，包含景点和美食", user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )
    assert "上午：中山陵" in result.answer
    assert "午餐：鸭血粉丝汤" in result.answer
    assert keywords == ["景点", "美食"]
    recorded = list(db_session.scalars(select(AgentToolRun)).all())
    assert len(recorded) == 3
    searches = [run for run in recorded if run.tool_name == "keyword_search"]
    assert len(searches) == 2
    assert {run.arguments_json["kind"] for run in searches} == {"attraction", "food"}
    assert any(run.tool_name == "estimate_budget" for run in recorded)
    assert all(
        run.status == "completed" and db_session.get(AgentToolResult, run.id)
        for run in recorded
    )


def test_runtime_one_day_plan_recovers_meals_omitted_by_llm(db_session: Session) -> None:
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)

    class PlanningClient(FakeStructuredClient):
        def complete_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model.__name__ == "Itinerary":
                return {"days": [{"day_number": 1, "items": [
                    {"poi_id": "A1", "poi_name": "古鸡鸣寺", "period": "morning", "activity_type": "ATTRACTION"},
                ]}]}
            return super().complete_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=output_model,
            )

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        assert url.endswith("/v3/place/text")
        food = params["keywords"] == "美食"
        pois = [
            {"id": "F1", "name": "金陵宴", "type": "餐饮服务;中餐厅"},
            {"id": "F2", "name": "刘长兴", "type": "餐饮服务;中餐厅"},
        ] if food else [{"id": "A1", "name": "古鸡鸣寺", "type": "风景名胜"}]
        return {"status": "1", "pois": [
            {**poi, "cityname": "南京市", "adcode": "320102", "location": "118.800000,32.050000"}
            for poi in pois
        ]}

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=PlanningClient(requirement), amap_transport=transport,
    ).run("给我规划一个南京一日游", 1, db_session)

    assert "上午：古鸡鸣寺" in result.answer
    assert "午餐：金陵宴" in result.answer
    assert "晚餐：刘长兴" in result.answer
    assert "早餐：暂无可靠推荐" in result.answer
    assert "餐饮 150 元" in result.answer
    assert "景点门票未计入" in result.answer
    assert "accommodation" not in result.answer


def test_runtime_recommendation_uses_fixed_poi_endpoint_without_react(db_session: Session) -> None:
    user = add_user(db_session, "runtime-direct-poi")
    conversation = ChatConversation(id="runtime-direct-poi-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id, role="user", content="推荐南京景点？", status="pending"
    )
    db_session.add(message)
    db_session.commit()
    client = FakeStructuredClient(TravelRequirement(intent="poi_recommendation", city="南京"))
    requests: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        requests.append((url, params))
        return {"status": "1", "pois": [{
            "id": "A1", "name": "中山陵", "type": "风景名胜",
            "cityname": "南京市", "location": "118.858000,32.058000",
        }]}

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client, amap_transport=transport,
    ).run(
        "推荐南京景点", user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )
    assert "中山陵" in result.answer
    assert client.react_contexts == []
    assert len(requests) == 1
    assert requests[0][0].endswith("/v3/place/text")
    assert requests[0][1]["keywords"] == "景点"
    recorded = list(db_session.scalars(select(AgentToolRun)).all())
    assert len(recorded) == 1
    assert recorded[0].tool_name == "keyword_search"
    assert recorded[0].arguments_json == {"city": "南京", "kind": "attraction"}
    stored_result = db_session.get(AgentToolResult, recorded[0].id)
    assert stored_result.result_json["pois"][0]["name"] == "中山陵"


def test_runtime_records_failed_direct_amap_call(db_session: Session) -> None:
    user = add_user(db_session, "runtime-failed-direct-tool")
    conversation = ChatConversation(id="runtime-failed-direct-tool-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="推荐南京景点",
        status="pending",
    )
    db_session.add(message)
    db_session.commit()
    client = FakeStructuredClient(TravelRequirement(
        intent="poi_recommendation", city="南京", poi_kind="attraction"
    ))

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client,
        amap_transport=lambda _url, _params, _timeout: {
            "status": "0", "info": "INVALID_USER_KEY"
        },
    ).run(
        message.content, user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )

    run = db_session.scalar(select(AgentToolRun))
    assert "查询失败" in result.answer
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "AmapApiError"
    assert "INVALID_USER_KEY" in run.summary_text


def test_runtime_does_not_call_navigation_for_route_question(db_session: Session) -> None:
    client = FakeStructuredClient(
        TravelRequirement(
            intent="route_query",
            city="南京",
            origin="中山陵",
            destination="夫子庙",
        )
    )
    requests: list[str] = []
    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client,
        amap_transport=lambda url, _params, _timeout: requests.append(url) or {},
    ).run("中山陵到夫子庙怎么走？", 1, db_session)
    assert "路线导航" in result.answer
    assert requests == []
    assert client.react_contexts == []


def test_runtime_distance_question_uses_direct_poi_and_distance_chain(
    db_session: Session,
) -> None:
    user = add_user(db_session, "runtime-direct-distance")
    conversation = ChatConversation(id="runtime-direct-distance-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="南京中山陵到夫子庙多远？",
        status="pending",
    )
    db_session.add(message)
    db_session.commit()
    client = FakeStructuredClient(TravelRequirement(
        intent="distance_query", city="南京", origin="中山陵", destination="夫子庙"
    ))
    paths: list[str] = []

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        paths.append(url)
        if url.endswith("/v3/place/text"):
            return {"status": "1", "pois": [{
                "id": params["keywords"],
                "name": params["keywords"],
                "type": "风景名胜",
                "cityname": "南京市",
                "adcode": "320102",
                "location": "118.858000,32.058000"
                if params["keywords"] == "中山陵" else "118.805000,32.065000",
            }]}
        if url.endswith("/v3/distance"):
            assert params["type"] == "0"
            return {"status": "1", "results": [{"distance": "5200"}]}
        raise AssertionError(url)

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client,
        amap_transport=transport,
    ).run(
        message.content, user.id, db_session,
        conversation_id=conversation.id, user_message_id=message.id,
    )
    assert "直线距离约 5.2 公里" in result.answer
    assert [path.rsplit("/", 1)[-1] for path in paths] == ["text", "text", "distance"]
    assert client.react_contexts == []
    runs = list(db_session.scalars(select(AgentToolRun)).all())
    assert [run.tool_name for run in runs] == [
        "keyword_search", "keyword_search", "distance"
    ]
    stored_distance = db_session.get(AgentToolResult, runs[-1].id)
    assert stored_distance.result_json == {"meters": 5200}
    assert runs[-1].arguments_json == {
        "origin": "118.858000,32.058000",
        "destination": "118.805000,32.065000",
        "mode": 0,
    }


def test_runtime_future_weather_uses_district_adcode_and_matching_date(
    db_session: Session,
) -> None:
    from datetime import timedelta
    from app.agent.factual import china_today

    target = china_today() + timedelta(days=1)
    client = FakeStructuredClient(TravelRequirement(
        intent="weather_query", city="南京", date_expression="明天",
        start_date=target.isoformat(), weather_time_kind="forecast_date",
    ))
    paths: list[str] = []

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        paths.append(url)
        if url.endswith("/v3/config/district"):
            return {"status": "1", "districts": [
                {"name": "南京市", "level": "city", "adcode": "320100"}
            ]}
        if url.endswith("/v3/weather/weatherInfo"):
            assert params["city"] == "320100"
            assert params["extensions"] == "all"
            return {"status": "1", "forecasts": [{
                "adcode": "320100", "casts": [
                    {"date": china_today().isoformat(), "dayweather": "晴", "nightweather": "晴"},
                    {"date": target.isoformat(), "dayweather": "雨", "nightweather": "阴"},
                ],
            }]}
        raise AssertionError(url)

    result = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=client,
        amap_transport=transport,
    ).run("明天南京天气怎么样？", 1, db_session)
    assert target.isoformat() in result.answer
    assert "白天雨" in result.answer
    assert [path.rsplit("/", 1)[-1] for path in paths] == ["district", "weatherInfo"]
    assert client.react_contexts == []


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


def test_runtime_reuses_request_id_from_execution_context(
    db_session: Session,
) -> None:
    client = FakeStructuredClient(TravelRequirement(intent="general_query"))

    with request_context("req-runtime-context-1"):
        result = AgentRuntime(
            settings=Settings(token_secret="test-only-secret"),
            llm_client=client,
        ).run("你能做什么？", 42, db_session)

    assert result.request_id == "req-runtime-context-1"


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
