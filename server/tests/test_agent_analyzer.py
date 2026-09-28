from datetime import date

import pytest
from pydantic import ValidationError

from app.agent.analyzer import REQUIREMENT_ANALYZER_SYSTEM_PROMPT, RequirementAnalyzer
from app.agent.models import TravelRequirement


class FakeStructuredOutputClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete_structured(
        self, *, system_prompt: str, user_prompt: str, output_model
    ):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "output_model": output_model,
            }
        )
        return self.response


def test_analyzer_forwards_query_to_structured_output_client() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(
            intent="trip_planning",
            origin="上海",
            city="南京",
            duration_days=3,
            travelers=2,
            budget=3000,
            preferences=["历史文化", "当地美食"],
            constraints=["避免以前去过的景点"],
        )
    )

    result = RequirementAnalyzer(client).analyze(
        "十一从上海去南京玩三天，两个人预算3000。"
    )

    assert result.city == "南京"
    assert result.preferences == ["历史文化", "当地美食"]
    assert result.constraints == ["避免以前去过的景点"]
    assert client.calls[0]["user_prompt"] == "十一从上海去南京玩三天，两个人预算3000。"
    assert client.calls[0]["output_model"] is TravelRequirement
    assert "不要决定调用哪些 Tool" in client.calls[0]["system_prompt"]


def test_analyzer_keeps_missing_fields_empty() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(
            intent="trip_planning",
            city="南京",
            duration_days=3,
        )
    )

    result = RequirementAnalyzer(client).analyze("帮我规划南京三日游")

    assert result.origin is None
    assert result.budget is None
    assert result.travelers is None


def test_analyzer_inherits_city_for_follow_up_and_passes_memory_context() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(intent="poi_recommendation", poi_kind="food")
    )

    result = RequirementAnalyzer(client).analyze(
        "美食呢？",
        conversation_context="用户刚才在讨论南京景点。",
        session_state={"city": "南京", "topic": "南京景点"},
    )

    assert result.city == "南京"
    assert "用户刚才在讨论南京景点。" in client.calls[0]["user_prompt"]
    assert "当前用户消息" in client.calls[0]["user_prompt"]


def test_explicit_current_city_overrides_conversation_memory() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(intent="weather_query", city="上海")
    )

    result = RequirementAnalyzer(client).analyze(
        "那上海呢？",
        session_state={"city": "南京"},
    )

    assert result.city == "上海"


def test_analyzer_adds_explicit_long_term_preferences_to_requirement() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(intent="trip_planning", city="南京")
    )

    result = RequirementAnalyzer(client).analyze(
        "规划南京周末游",
        long_term_preferences=[
            {"category": "food_restriction", "content": "不吃辣"},
            {"category": "attraction_interest", "content": "喜欢博物馆"},
            {"category": "travel_pace", "content": "喜欢慢节奏"},
            {"category": "budget_tendency", "content": "偏好经济型"},
        ],
    )

    assert result.constraints == ["不吃辣"]
    assert result.preferences == ["喜欢博物馆", "喜欢慢节奏", "偏好经济型"]
    assert "用户明确保存的长期旅行偏好" in client.calls[0]["user_prompt"]
    assert "不吃辣" in client.calls[0]["user_prompt"]
    assert "当前请求优先" in client.calls[0]["system_prompt"]


def test_current_trip_request_overrides_saved_preference_in_its_category() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(
            intent="poi_recommendation", city="南京", poi_kind="food",
            constraints=["本次可以吃辣"],
        )
    )

    result = RequirementAnalyzer(client).analyze(
        "这次想吃辣，推荐南京美食",
        long_term_preferences=[
            {"category": "food_restriction", "content": "不吃辣"}
        ],
    )

    assert result.constraints == ["本次可以吃辣"]


def test_analyzer_supplies_current_date_for_holiday_weather_queries() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(
            intent="weather_query",
            city="南京",
            date_expression="中秋",
            start_date="2026-09-25",
        )
    )

    result = RequirementAnalyzer(
        client,
        today_provider=lambda: date(2026, 9, 23),
    ).analyze("南京中秋天气怎么样？")

    assert result.date_expression == "中秋"
    assert result.start_date == "2026-09-25"
    assert "当前日期：2026-09-23" in client.calls[0]["system_prompt"]
    assert "中秋" in client.calls[0]["system_prompt"]


def test_analyzer_infers_history_city_when_provider_omits_destination() -> None:
    client = FakeStructuredOutputClient(TravelRequirement(intent="history_query"))

    result = RequirementAnalyzer(client).analyze("我去过哈尔滨哪些地方？")

    assert result.city == "哈尔滨"


def test_analyzer_infers_history_city_when_provider_returns_blank_destination() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(intent="history_query", city="")
    )

    result = RequirementAnalyzer(client).analyze("我去过哈尔滨哪些地方？")

    assert result.city == "哈尔滨"


def test_analyzer_corrects_food_recommendation_even_if_model_says_attraction() -> None:
    client = FakeStructuredOutputClient({
        "intent": "poi_recommendation", "city": "南京", "poi_kind": "attraction",
    })
    result = RequirementAnalyzer(client).analyze("推荐南京美食")
    assert result.poi_kind == "food"


@pytest.mark.parametrize(("query", "expected_city"), [
    ("福州长乐有哪些好看的风景推荐？", "福州长乐"),
    ("福州市长乐区有哪些好看的风景推荐？", "福州市长乐区"),
])
def test_analyzer_preserves_explicit_district_for_poi_recommendation(
    query: str, expected_city: str,
) -> None:
    client = FakeStructuredOutputClient({
        "intent": "poi_recommendation", "city": "福州", "poi_kind": "attraction",
    })

    result = RequirementAnalyzer(client).analyze(query)

    assert result.city == expected_city


def test_analyzer_corrects_distance_question_mislabeled_as_route() -> None:
    client = FakeStructuredOutputClient({
        "intent": "route_query", "city": "南京",
        "origin": "中山陵", "destination": "夫子庙",
    })
    result = RequirementAnalyzer(client).analyze("南京中山陵到夫子庙有多远？")
    assert result.intent == "distance_query"
    assert result.origin == "中山陵"
    assert result.destination == "夫子庙"


@pytest.mark.parametrize("now_word", ["现在", "当前", "此刻", "目前"])
@pytest.mark.parametrize("model_kind", ["forecast_date", "ambiguous", None])
def test_analyzer_treats_explicit_current_weather_as_realtime(
    now_word: str, model_kind: str | None,
) -> None:
    client = FakeStructuredOutputClient({
        "intent": "weather_query", "city": "南京",
        "date_expression": now_word, "weather_time_kind": model_kind,
        "start_date": "2026-09-27",
    })
    result = RequirementAnalyzer(client).analyze(f"南京{now_word}天气怎么样？")
    assert result.weather_time_kind == "realtime"
    assert result.start_date is None
    assert result.end_date is None


def test_analyzer_does_not_turn_now_to_tomorrow_range_into_realtime() -> None:
    client = FakeStructuredOutputClient({
        "intent": "weather_query", "city": "南京",
        "date_expression": "从现在到明天", "weather_time_kind": "forecast_range",
    })
    result = RequirementAnalyzer(client).analyze("从现在到明天南京天气怎么样？")
    assert result.weather_time_kind == "forecast_range"


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("帮我规划南京三日游", "trip_planning"),
        ("南京明天天气怎么样", "weather_query"),
        ("推荐几个杭州自然景点", "poi_recommendation"),
        ("从中山陵怎么去夫子庙", "route_query"),
        ("我以前去过南京吗", "history_query"),
        ("南京玩三天大概多少钱", "budget_query"),
    ],
)
def test_analyzer_accepts_typical_intents(query: str, intent: str) -> None:
    client = FakeStructuredOutputClient(TravelRequirement(intent=intent))

    result = RequirementAnalyzer(client).analyze(query)

    assert result.intent == intent


def test_blank_query_is_rejected_without_calling_client() -> None:
    client = FakeStructuredOutputClient(TravelRequirement(intent="general_query"))

    with pytest.raises(ValueError, match="must not be blank"):
        RequirementAnalyzer(client).analyze("   ")

    assert client.calls == []


def test_provider_output_is_validated_as_travel_requirement() -> None:
    client = FakeStructuredOutputClient({"intent": "unknown_query"})

    with pytest.raises(ValidationError):
        RequirementAnalyzer(client).analyze("帮我规划一次旅行")


def test_requirement_analyzer_prompt_has_a_narrow_responsibility() -> None:
    assert "不要决定调用哪些 Tool" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
    assert "不要生成旅行方案" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT


def test_requirement_analyzer_prompt_declares_exact_output_fields() -> None:
    assert "intent" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
    assert "preferences" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
    assert "constraints" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
    assert "history_category" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
    assert "不要使用 task_type" in REQUIREMENT_ANALYZER_SYSTEM_PROMPT
