from datetime import date

import pytest

from app.agent.budget import AgentBudget
from app.agent.factual import FactualAnswerer
from app.agent.models import CollectedInfo, InformationStatus, TravelRequirement
from app.agent.response import FinalResponseGenerator
from app.agent.runtime import AgentRuntime
from app.agent.utils import note_supports_food
from app.core.config import Settings
from test_agent_food_review import food, note, plan, requirement
from test_agent_factual import FakeTransport, answerer


def test_dish_note_supports_verified_restaurant_and_has_visible_citation():
    saved = note("午餐优先选择清淡鸭血粉丝汤，店铺须经过本轮地点核验。")
    saved.tags = ["清淡", "鸭血粉丝汤"]
    poi = food("鸭血粉丝汤示例店")
    assert note_supports_food(saved, poi.name, "lunch")
    answer = FinalResponseGenerator().generate(
        requirement(), CollectedInfo(pois=[poi], knowledge=[saved]),
        InformationStatus(), plan(poi),
    )
    assert "参考收藏" in answer and "收藏#42" in answer and saved.title in answer


@pytest.mark.parametrize("excerpt,tags", [
    ("不推荐鸭血粉丝汤", ["鸭血粉丝汤"]),
    ("旧笔记推荐鸭血粉丝汤", ["鸭血粉丝汤"]),
    ("午餐优先选择清淡食物", ["鸭血粉丝汤"]),
    ("午餐推荐南京", ["南京"]),
])
def test_dish_tags_do_not_create_unsupported_recommendations(excerpt, tags):
    saved = note(excerpt)
    saved.tags = tags
    assert not note_supports_food(saved, "鸭血粉丝汤店", "lunch")


def test_old_note_is_quoted_as_old_content_not_current_fact():
    saved = note("旧笔记写中山陵门票固定999元、全天开放。这是过时素材。")
    answer = FinalResponseGenerator().generate(
        requirement(), CollectedInfo(knowledge=[saved]),
        InformationStatus(), plan(food("家常菜")),
    )
    assert saved.excerpt in answer
    assert "旧笔记原文（过时，非当前事实）" in answer
    assert "本轮未核实" in answer


@pytest.mark.parametrize("text", [
    "根据 message_id=65，你最早明确说的总预算是2000元，不想去寺庙。",
    "总预算是2000元，不想去寺庙（依据 message_id=153）。",
    "2000元，不想去寺庙，message_id: 65。",
])
def test_memory_answer_hides_internal_pointer_but_keeps_source_context(text):
    class Client:
        def complete_structured(self, **kwargs):
            assert "message_id" in kwargs["user_prompt"]
            return {"answer": text}

    runtime = AgentRuntime(Settings(), llm_client=Client())
    class Message:
        content = "最早的预算和不想去的类型是什么？"

    context = {"message_id": 65, "content": "预算2000元，不想去寺庙"}
    result = runtime._answer_memory(
        {"messages": [Message()], "conversation_context": context},
        AgentBudget(total_timeout_seconds=30, stage_timeout_seconds=10),
    )
    assert "message_id" not in result and "65" not in result and "153" not in result
    assert "2000" in result and "寺庙" in result
    assert context["message_id"] == 65


def test_future_weather_notice_does_not_expose_provider():
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", start_date="2026-12-01",
        weather_time_kind="forecast_date",
    ))
    assert "预报范围" in result and "高德" not in result
    assert not transport.calls


def test_missing_forecast_date_notice_does_not_expose_provider():
    class Amap:
        def resolve_adcode(self, city):
            return "320100"

        def weather_adcode(self, adcode, forecast):
            return {"forecasts": [{"adcode": adcode, "casts": []}]}

    result = FactualAnswerer(Amap(), today_provider=lambda: date(2026, 10, 9)).answer(
        TravelRequirement(intent="weather_query", city="南京", start_date="2026-10-10",
                          weather_time_kind="forecast_date"),
    )
    assert "不包含" in result and "高德" not in result
