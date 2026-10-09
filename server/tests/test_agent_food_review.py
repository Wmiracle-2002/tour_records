import pytest

from app.agent.factual import FactualAnswerer
from app.agent.generator import StructuredItineraryGenerator, fallback_itinerary
from app.agent.models import (
    CollectedInfo, InformationStatus, Itinerary, ItineraryDay, ItineraryItem,
    KnowledgeInfo, POIInfo, TravelRequirement,
)
from app.agent.response import FinalResponseGenerator
from app.agent.validator import ItineraryValidator
from app.agent.utils import meal_matches, note_supports_food


def food(name, number=1):
    return POIInfo(poi_id=str(number), name=name, category="餐饮服务", location="118.8,32.0")


def note(text):
    return KnowledgeInfo(id=42, title="我的笔记", category="food_guide",
                         city_code="320100", excerpt=text, updated_at="2026-10-01")


def requirement(**kwargs):
    return TravelRequirement(intent="trip_planning", city="南京", duration_days=1, **kwargs)


def plan(poi, period="lunch"):
    return Itinerary(days=[ItineraryDay(day_number=1, items=[ItineraryItem(
        poi_id=poi.poi_id, poi_name=poi.name, period=period, activity_type="FOOD",
    )])])


@pytest.mark.parametrize("name,period", [("清淡早餐店", "lunch"), ("晚餐店", "breakfast")])
def test_incompatible_meal_rejected_by_generator_and_validator(name, period):
    poi = food(name)
    info = CollectedInfo(pois=[poi])
    itinerary = plan(poi, period)
    generator = StructuredItineraryGenerator(None)
    with pytest.raises(ValueError, match="meal"):
        generator._validate_itinerary(itinerary, requirement(), info)
    assert not ItineraryValidator().validate(requirement(), itinerary, info).valid


def test_fill_and_fallback_skip_breakfast_only_food_for_lunch_and_dinner():
    info = CollectedInfo(pois=[food("早餐店"), food("家常菜", 2), food("晚餐店", 3)])
    empty = Itinerary(days=[ItineraryDay(day_number=1, items=[])])
    result = StructuredItineraryGenerator._fill_missing_meals(empty, requirement(), info)
    assert {i.period: i.poi_name for i in result.days[0].items} == {
        "breakfast": "早餐店", "lunch": "家常菜", "dinner": "晚餐店",
    }
    fallback = fallback_itinerary(requirement(), info)
    assert next(i for i in fallback.days[0].items if i.period == "breakfast").poi_name == "早餐店"


def test_non_spicy_preference_filters_explicit_conflicts_and_explains_unknowns():
    class Amap:
        def search_verified_pois(self, **kwargs):
            return {"pois": [{"name": "麻辣小吃"}, {"name": "家常菜"}]}

    answer = FactualAnswerer(Amap()).answer(TravelRequirement(
        intent="poi_recommendation", city="南京", poi_kind="food", preferences=["不吃辣"],
    ))
    assert "美食推荐：家常菜" in answer
    assert "不吃辣" in answer and "筛选依据" in answer
    assert "无法确认" in answer and "辣度" in answer


def test_planning_excludes_conflicting_food_and_explains_dietary_basis():
    poi = food("麻辣小吃")
    info = CollectedInfo(pois=[poi])
    req = requirement(constraints=["不吃辣"])
    with pytest.raises(ValueError, match="diet"):
        StructuredItineraryGenerator(None)._validate_itinerary(plan(poi), req, info)
    assert not ItineraryValidator().validate(req, plan(poi), info).valid
    assert not fallback_itinerary(req, info).days[0].items
    answer = FinalResponseGenerator().generate(req, info, InformationStatus(),
                                              Itinerary(days=[ItineraryDay(day_number=1, items=[])]))
    assert "筛选依据" in answer and "不吃辣" in answer and "无法确认" in answer


def test_fill_prioritizes_matching_note_without_creating_a_poi():
    info = CollectedInfo(pois=[food("普通饭店"), food("家常菜", 2), food("晚餐店", 3)],
                         knowledge=[note("午餐推荐家常菜；虚构饭店也好吃。")])
    empty = Itinerary(days=[ItineraryDay(day_number=1, items=[])])
    result = StructuredItineraryGenerator._fill_missing_meals(empty, requirement(), info)
    assert next(item for item in result.days[0].items if item.period == "lunch").poi_name == "家常菜"
    assert all(i.poi_name != "虚构饭店" for i in result.days[0].items)


def test_stale_note_is_explicitly_disclosed_not_presented_as_current_fact():
    poi = food("家常菜")
    info = CollectedInfo(pois=[poi], knowledge=[note("家常菜全天开放，固定999元。这是过时笔记。")])
    answer = FinalResponseGenerator().generate(requirement(), info, InformationStatus(), plan(poi))
    assert "过时" in answer and "本轮未核实" in answer and "收藏#42" in answer
    assert "旧笔记原文（过时，非当前事实）" in answer and "固定999元" in answer


def test_old_timestamp_alone_does_not_prove_note_is_stale():
    poi = food("家常菜")
    saved = note("推荐家常菜")
    saved.updated_at = "2020-01-01"
    answer = FinalResponseGenerator().generate(
        requirement(), CollectedInfo(pois=[poi], knowledge=[saved]), InformationStatus(), plan(poi),
    )
    assert "笔记已过时" not in answer


@pytest.mark.parametrize("name,period,expected", [
    ("早午餐", "lunch", True), ("早餐晚餐店", "dinner", True),
    ("早午餐", "breakfast", True),
    ("家常菜", "breakfast", True), ("夜宵店", "breakfast", False),
])
def test_meal_label_boundaries(name, period, expected):
    assert meal_matches(name, period) is expected


@pytest.mark.parametrize("text", ["不推荐家常菜", "家常菜不适合午餐", "旧笔记推荐家常菜"])
def test_negative_or_stale_mentions_are_not_positive_recommendations(text):
    assert not note_supports_food(note(text), "家常菜")


def test_recommendation_prioritizes_and_cites_user_note_without_inventing_pois():
    class Amap:
        def search_verified_pois(self, **kwargs):
            return {"pois": [{"name": "普通饭店"}, {"name": "家常菜"}]}

    answer = FactualAnswerer(Amap(), knowledge_searcher=lambda city, preferences, kind: [
        note("推荐家常菜，推荐虚构饭店。"),
    ]).answer(TravelRequirement(intent="poi_recommendation", city="南京", poi_kind="food"))
    assert "美食推荐：家常菜、普通饭店" in answer and "收藏#42" in answer
    assert "虚构饭店" not in answer
    assert "不吃辣" not in answer


def test_generator_retries_bad_meal_once_and_does_not_stream_invalid_day():
    breakfast = food("早餐店")
    lunch = food("家常菜", 2)
    info = CollectedInfo(pois=[breakfast, lunch])

    class Client:
        calls = 0

        def complete_structured_stream(self, **kwargs):
            self.calls += 1
            result = plan(breakfast if self.calls == 1 else lunch).model_dump_json()
            if self.calls == 2:
                assert "meal does not match period" in kwargs["user_prompt"]
            kwargs["on_delta"](result)
            return Itinerary.model_validate_json(result)

    client = Client()
    previews = []
    result = StructuredItineraryGenerator(client, on_preview=previews.append).generate(requirement(), info)
    assert client.calls == 2
    assert result.days[0].items[0].poi_name == "家常菜"
    assert previews and all("午餐：早餐店" not in text for text in previews)


def test_negative_food_note_is_not_cited_as_a_recommendation():
    poi = food("家常菜")
    answer = FinalResponseGenerator().generate(
        requirement(), CollectedInfo(pois=[poi], knowledge=[note("不推荐家常菜")]),
        InformationStatus(), plan(poi),
    )
    assert "参考收藏" not in answer
