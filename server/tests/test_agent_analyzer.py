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
            destination="南京",
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

    assert result.destination == "南京"
    assert result.preferences == ["历史文化", "当地美食"]
    assert result.constraints == ["避免以前去过的景点"]
    assert client.calls[0]["user_prompt"] == "十一从上海去南京玩三天，两个人预算3000。"
    assert client.calls[0]["output_model"] is TravelRequirement
    assert "不要决定调用哪些 Tool" in client.calls[0]["system_prompt"]


def test_analyzer_keeps_missing_fields_empty() -> None:
    client = FakeStructuredOutputClient(
        TravelRequirement(
            intent="trip_planning",
            destination="南京",
            duration_days=3,
        )
    )

    result = RequirementAnalyzer(client).analyze("帮我规划南京三日游")

    assert result.origin is None
    assert result.budget is None
    assert result.travelers is None


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
