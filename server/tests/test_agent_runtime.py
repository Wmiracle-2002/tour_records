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
from app.agent.observability import RecordingAgentObserver, request_context
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
    ).run("规划南京一日游，包含景点和美食", 1, db_session)
    assert "上午：中山陵" in result.answer
    assert "午餐：鸭血粉丝汤" in result.answer
    assert keywords == ["景点", "美食"]


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
    ).run("推荐南京景点", 1, db_session)
    assert "中山陵" in result.answer
    assert client.react_contexts == []
    assert len(requests) == 1
    assert requests[0][0].endswith("/v3/place/text")
    assert requests[0][1]["keywords"] == "景点"


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
    ).run("南京中山陵到夫子庙多远？", 1, db_session)
    assert "直线距离约 5.2 公里" in result.answer
    assert [path.rsplit("/", 1)[-1] for path in paths] == ["text", "text", "distance"]
    assert client.react_contexts == []


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
