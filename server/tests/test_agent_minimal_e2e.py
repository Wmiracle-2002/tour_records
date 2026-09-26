"""Send Android-shaped chat messages through the authenticated HTTP API."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.collector import ReActDecision, ToolCall
from app.agent.factual import china_today
from app.agent.models import Itinerary, TravelRequirement
from app.agent.observability import RecordingAgentObserver
from app.agent.runtime import AgentRuntime
from app.core.config import Settings
from app.models import Record, RecordType, Trip


class ScenarioLLM:
    def __init__(self, requirement: TravelRequirement) -> None:
        self.requirement = requirement
        self.calls: list[str] = []

    def complete_structured(self, *, system_prompt, user_prompt, output_model):
        self.calls.append(output_model.__name__)
        if output_model is TravelRequirement:
            return self.requirement
        if output_model is ReActDecision:
            if self.requirement.intent == "history_query":
                return ReActDecision(tool_call=ToolCall(
                    name="search_records",
                    arguments={"city": "南京", "category": "ATTRACTION"},
                ))
            if self.requirement.intent == "poi_recommendation":
                return ReActDecision(tool_call=ToolCall(
                    name="keyword_search", arguments={"city": "南京", "kind": "attraction"},
                ))
            raise AssertionError("direct questions must not enter ReAct")
        if output_model is Itinerary:
            return {"days": [{"day_number": 1, "items": [
                {"poi_id": "A1", "poi_name": "中山陵", "period": "morning", "activity_type": "ATTRACTION"},
                {"poi_id": "F1", "poi_name": "鸭血粉丝汤", "period": "lunch", "activity_type": "FOOD"},
            ]}]}
        raise AssertionError(output_model)


def provider(calls: list[tuple[str, dict[str, str]]]):
    def respond(url: str, params: dict[str, str], _timeout: float) -> dict:
        path = url.removeprefix("https://restapi.amap.com")
        calls.append((path, {key: value for key, value in params.items() if key != "key"}))
        if path == "/v3/place/text":
            name = params["keywords"]
            if name in {"景点", "中山陵"}:
                poi_id, poi_name, category, location = (
                    "A1", "中山陵", "风景名胜", "118.858000,32.058000"
                )
            elif name == "美食":
                poi_id, poi_name, category, location = (
                    "F1", "鸭血粉丝汤", "餐饮服务;中餐厅", "118.800000,32.050000"
                )
            elif name == "夫子庙":
                poi_id, poi_name, category, location = (
                    "A2", "夫子庙", "风景名胜", "118.805000,32.065000"
                )
            else:
                raise AssertionError(name)
            return {"status": "1", "infocode": "10000", "pois": [{
                "id": poi_id, "name": poi_name, "type": category,
                "cityname": "南京市", "adcode": "320102", "location": location,
            }]}
        if path == "/v3/distance":
            return {"status": "1", "infocode": "10000", "results": [{"distance": "5200"}]}
        if path == "/v3/config/district":
            return {"status": "1", "infocode": "10000", "districts": [
                {"name": "南京市", "level": "city", "adcode": "320100"},
            ]}
        if path == "/v3/weather/weatherInfo":
            if params["extensions"] == "base":
                return {"status": "1", "infocode": "10000", "lives": [{
                    "adcode": "320100", "weather": "多云", "temperature": "23",
                }]}
            target = china_today() + timedelta(days=1)
            return {"status": "1", "infocode": "10000", "forecasts": [{
                "adcode": "320100", "reporttime": "2026-09-26 08:00:00",
                "casts": [{
                    "date": target.isoformat(), "dayweather": "雨", "nightweather": "阴",
                }],
            }]}
        raise AssertionError(path)

    return respond


def add_history(db_session: Session) -> None:
    trip = Trip(
        user_id=1, province_code="320000", city_code="320100", city_name="南京市",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
    )
    db_session.add(trip)
    db_session.flush()
    db_session.add(Record(
        trip_id=trip.id, type=RecordType.ATTRACTION, name="中山陵",
        date=date(2026, 8, 1),
    ))
    db_session.commit()


@pytest.mark.parametrize(
    ("message", "requirement", "expected", "paths"),
    [
        (
            "我去过南京哪些景点？",
            TravelRequirement(intent="history_query", city="南京", history_category="ATTRACTION"),
            "中山陵", [],
        ),
        (
            "推荐南京景点",
            TravelRequirement(intent="poi_recommendation", city="南京"),
            "中山陵", ["/v3/place/text"],
        ),
        (
            "推荐南京美食",
            TravelRequirement(intent="poi_recommendation", city="南京", poi_kind="attraction"),
            "鸭血粉丝汤", ["/v3/place/text"],
        ),
        (
            "南京中山陵到夫子庙多远？",
            TravelRequirement(intent="route_query", city="南京", origin="中山陵", destination="夫子庙"),
            "直线距离约 5.2 公里", ["/v3/place/text", "/v3/place/text", "/v3/distance"],
        ),
        (
            "南京现在天气怎么样？",
            TravelRequirement(
                intent="weather_query", city="南京", date_expression="现在",
                weather_time_kind="forecast_date",
            ),
            "当前实况", ["/v3/config/district", "/v3/weather/weatherInfo"],
        ),
        (
            "南京明天天气怎么样？",
            TravelRequirement(
                intent="weather_query", city="南京", date_expression="明天",
                weather_time_kind="forecast_date",
            ),
            "雨", ["/v3/config/district", "/v3/weather/weatherInfo"],
        ),
        (
            "两个人去南京三天预算多少？",
            TravelRequirement(intent="budget_query", city="南京", duration_days=3, travelers=2),
            "人民币粗略估算", [],
        ),
        (
            "规划南京一日游，包含景点和美食",
            TravelRequirement(intent="trip_planning", city="南京", duration_days=1),
            "午餐：鸭血粉丝汤", ["/v3/place/text", "/v3/place/text"],
        ),
    ],
)
def test_authenticated_chat_scenarios_keep_request_trace_and_verified_facts(
    client: TestClient,
    db_session: Session,
    caplog,
    message: str,
    requirement: TravelRequirement,
    expected: str,
    paths: list[str],
) -> None:
    if requirement.intent == "history_query":
        add_history(db_session)
    llm = ScenarioLLM(requirement)
    observer = RecordingAgentObserver()
    calls: list[tuple[str, dict[str, str]]] = []
    client.app.state.agent_runtime = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=llm, observer=observer, amap_transport=provider(calls),
    )
    trace_id = f"e-step-{requirement.intent}"
    with caplog.at_level(logging.INFO):
        started = perf_counter()
        response = client.post(
            "/api/v1/agent/chat", json={"message": message},
            headers={"X-Request-ID": trace_id},
        )
        elapsed_ms = (perf_counter() - started) * 1000

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == trace_id
    assert response.json()["request_id"] == trace_id
    assert expected in response.json()["answer"]
    assert "上千公里" not in response.json()["answer"]
    assert "暂未开放" not in response.json()["answer"]
    assert [path for path, _ in calls] == paths
    if message == "南京现在天气怎么样？":
        assert calls[-1][1]["extensions"] == "base"
    assert all(path != "/v3/geocode/geo" for path, _ in calls)
    if message == "推荐南京美食":
        assert calls[0][1]["keywords"] == "美食"
        assert llm.calls == ["TravelRequirement"]
    if "多远" in message:
        assert llm.calls == ["TravelRequirement"]
    assert observer.events
    assert all(event.request_id == trace_id for event in observer.events)
    assert any(event.event == "final_response_ready" for event in observer.events)
    assert all(event.stage_duration_ms is None or event.stage_duration_ms >= 0 for event in observer.events)
    assert elapsed_ms < 10000
    api_logs = [record.message for record in caplog.records if record.name == "app.api.agent"]
    assert any(f"request_id={trace_id}" in line for line in api_logs)
    amap_logs = [json.loads(record.message) for record in caplog.records if record.name == "footmarks.agent.amap"]
    assert all(event["request_id"] == trace_id for event in amap_logs)
    assert all("fake-key" not in record.message for record in caplog.records)


@pytest.mark.parametrize(
    ("requirement", "message", "failure", "expected"),
    [
        (
            TravelRequirement(intent="history_query", city="南京", history_category="ATTRACTION"),
            "我去过南京哪些景点？", "none", "没有找到在南京的历史旅行记录",
        ),
        (
            TravelRequirement(intent="poi_recommendation", city="南京"),
            "推荐南京景点", "empty_pois", "暂无可靠的景点推荐",
        ),
        (
            TravelRequirement(intent="weather_query", city="南京", date_expression="明天", weather_time_kind="forecast_date"),
            "南京明天天气怎么样？", "empty_forecast", "高德返回的预报不包含所问日期",
        ),
        (
            TravelRequirement(intent="budget_query", city="南京"),
            "去南京要多少预算？", "none", "请说明旅行天数",
        ),
        (
            TravelRequirement(intent="trip_planning", city="南京", duration_days=1),
            "规划南京一日游", "empty_pois", "当前还没有可展示的完整行程",
        ),
    ],
)
def test_chat_degrades_without_inventing_provider_facts(
    client: TestClient,
    requirement: TravelRequirement,
    message: str,
    failure: str,
    expected: str,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    successful = provider(calls)

    def missing_data(url: str, params: dict[str, str], timeout: float) -> dict:
        path = url.removeprefix("https://restapi.amap.com")
        if failure == "empty_pois" and path == "/v3/place/text":
            calls.append((path, {key: value for key, value in params.items() if key != "key"}))
            return {"status": "1", "infocode": "10000", "pois": []}
        if failure == "empty_forecast" and path == "/v3/weather/weatherInfo":
            calls.append((path, {key: value for key, value in params.items() if key != "key"}))
            return {"status": "1", "infocode": "10000", "forecasts": [
                {"adcode": "320100", "casts": []},
            ]}
        return successful(url, params, timeout)

    client.app.state.agent_runtime = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=ScenarioLLM(requirement), amap_transport=missing_data,
    )
    response = client.post("/api/v1/agent/chat", json={"message": message})
    assert response.status_code == 200
    answer = response.json()["answer"]
    assert expected in answer
    assert "中山陵" not in answer
    assert "鸭血粉丝汤" not in answer
    assert "晴" not in answer
    assert "元" not in answer


@pytest.mark.parametrize("days", [2, 3])
@pytest.mark.parametrize("dated", [False, True])
def test_authenticated_multi_day_plan_uses_verified_pois_and_dates(
    client: TestClient, days: int, dated: bool,
) -> None:
    start = date(2026, 10, 10) if dated else None
    requirement = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=days,
        start_date=start.isoformat() if start else None,
    )

    class MultiDayLLM(ScenarioLLM):
        def complete_structured(self, *, system_prompt, user_prompt, output_model):
            if output_model is Itinerary:
                self.calls.append("Itinerary")
                return {"days": [
                    {
                        "day_number": index,
                        "date": (start + timedelta(days=index - 1)).isoformat() if start else None,
                        "items": [
                            {"poi_id": f"A{index}", "poi_name": f"景点{index}",
                             "period": "morning", "activity_type": "ATTRACTION"},
                            {"poi_id": f"F{index}", "poi_name": f"餐馆{index}",
                             "period": "lunch", "activity_type": "FOOD"},
                        ],
                    }
                    for index in range(1, days + 1)
                ]}
            return super().complete_structured(
                system_prompt=system_prompt, user_prompt=user_prompt,
                output_model=output_model,
            )

    calls: list[str] = []

    def transport(url: str, params: dict[str, str], _timeout: float) -> dict:
        assert url.endswith("/v3/place/text")
        calls.append(params["keywords"])
        food = params["keywords"] == "美食"
        return {"status": "1", "infocode": "10000", "pois": [
            {
                "id": f"{'F' if food else 'A'}{index}",
                "name": f"{'餐馆' if food else '景点'}{index}",
                "type": "餐饮服务;中餐厅" if food else "风景名胜",
                "cityname": "南京市", "adcode": "320102",
                "location": "118.800000,32.050000",
            }
            for index in range(1, days + 1)
        ]}

    llm = MultiDayLLM(requirement)
    observer = RecordingAgentObserver()
    client.app.state.agent_runtime = AgentRuntime(
        settings=Settings(token_secret="test-only-secret", amap_web_key="fake-key"),
        llm_client=llm, observer=observer, amap_transport=transport,
    )
    trace_id = f"multi-day-{days}-{'dated' if dated else 'undated'}"
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": f"规划南京{days}日游"},
        headers={"X-Request-ID": trace_id},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == trace_id
    assert response.json()["request_id"] == trace_id
    answer = response.json()["answer"]
    for index in range(1, days + 1):
        assert f"第{index}天" in answer
        assert f"上午：景点{index}" in answer
        assert f"午餐：餐馆{index}" in answer
        if start:
            assert (start + timedelta(days=index - 1)).isoformat() in answer
    if not start:
        assert "2026-" not in answer
    assert calls == ["景点", "美食"]
    assert llm.calls == ["TravelRequirement", "Itinerary"]
    assert any(event.event == "final_response_ready" for event in observer.events)
