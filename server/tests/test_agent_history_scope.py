import pytest

from app.agent.analyzer import RequirementAnalyzer
from app.agent.models import CollectedInfo, InfoRequirement, InformationStatus, TravelRequirement
from app.agent.normalizer import normalize_history, normalize_records
from app.agent.response import FinalResponseGenerator


TRIPS = [
    {"city_name": "南京市", "records": [
        {"name": "中山陵", "category": "ATTRACTION"},
        {"name": "鸭血粉丝汤", "category": "FOOD"},
    ]},
    {"city_name": "苏州市", "records": [
        {"name": "拙政园", "category": "ATTRACTION"},
        {"name": "松鼠桂鱼", "category": "FOOD"},
    ]},
    {"city_name": "南京市", "records": [
        {"name": "中山陵", "category": "ATTRACTION"},
    ]},
]


@pytest.mark.parametrize("query,category", [
    ("我之前去过哪些城市？", None),
    ("我去过哪些地方？", "ATTRACTION"),
    ("我吃过哪些美食？", "FOOD"),
    ("我去过哪些景点，吃过哪些美食？", "BOTH"),
])
def test_history_category_overrides_incorrect_llm_category(query, category):
    class Client:
        def complete_structured(self, **kwargs):
            return TravelRequirement(intent="history_query", history_category="FOOD")

    assert RequirementAnalyzer(Client()).analyze(query).history_category == category


@pytest.mark.parametrize("normalizer", [normalize_history, normalize_records])
@pytest.mark.parametrize("category,label,names,excluded", [
    (None, "", [], ["中山陵", "鸭血粉丝汤", "拙政园", "松鼠桂鱼"]),
    ("ATTRACTION", "去过的地点", ["中山陵", "拙政园"], ["鸭血粉丝汤", "松鼠桂鱼"]),
    ("FOOD", "吃过的美食", ["鸭血粉丝汤", "松鼠桂鱼"], ["中山陵", "拙政园"]),
])
def test_history_answers_group_correct_record_type_by_city(normalizer, category, label, names, excluded):
    raw = TRIPS if normalizer is normalize_history else [
        dict(record, city_name=trip["city_name"], trip_id=index)
        for index, trip in enumerate(TRIPS, 1) for record in trip["records"]
    ]
    answer = FinalResponseGenerator().generate(
        TravelRequirement(intent="history_query", history_category=category),
        CollectedInfo(history=normalizer(raw)),
        InformationStatus(history=InfoRequirement(status="completed")),
    )
    if category is None:
        assert answer == "去过的城市：南京市、苏州市。"
    else:
        assert answer == f"去过的城市1：南京市，{label}：{names[0]}；\n去过的城市2：苏州市，{label}：{names[1]}。"
    for name in excluded:
        assert name not in answer


def test_empty_city_has_no_fabricated_places():
    answer = FinalResponseGenerator().generate(
        TravelRequirement(intent="history_query", history_category="ATTRACTION"),
        CollectedInfo(history=normalize_history([{"city_name": "南京市", "records": []}])),
        InformationStatus(history=InfoRequirement(status="completed")),
    )
    assert "南京市" in answer
    assert "暂无相关记录" in answer


def test_explicit_combined_query_keeps_places_and_food_separate():
    class Client:
        def complete_structured(self, **kwargs):
            return TravelRequirement(intent="history_query")

    requirement = RequirementAnalyzer(Client()).analyze("去过哪些景点，吃过哪些美食？")
    answer = FinalResponseGenerator().generate(
        requirement, CollectedInfo(history=normalize_history(TRIPS)),
        InformationStatus(history=InfoRequirement(status="completed")),
    )
    assert "去过的地点：中山陵，吃过的美食：鸭血粉丝汤" in answer
    assert "去过的地点：拙政园，吃过的美食：松鼠桂鱼" in answer


@pytest.mark.parametrize("query", ["我去过哪些城市", "我去过哪些地方", "我吃过哪些美食"])
def test_global_history_question_without_punctuation_does_not_infer_a_city(query):
    class Client:
        def complete_structured(self, **kwargs):
            return TravelRequirement(intent="history_query")

    assert RequirementAnalyzer(Client()).analyze(query).city is None


def test_history_tool_arguments_cannot_override_explicit_city_and_type():
    from app.agent.collector import ToolCall, _normalize_tool_arguments

    arguments = _normalize_tool_arguments(
        ToolCall(name="search_trip_history", arguments={"city": "上海", "category": "FOOD"}),
        TravelRequirement(intent="history_query", city="南京", history_category="ATTRACTION"),
    )
    assert arguments == {"city": "南京", "category": "ATTRACTION"}
