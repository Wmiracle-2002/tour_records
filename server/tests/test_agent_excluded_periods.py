import pytest

from app.agent.generator import StructuredItineraryGenerator, fallback_itinerary
from app.agent.models import (
    CollectedInfo, Itinerary, ItineraryDay, ItineraryItem, POIInfo, TravelRequirement,
)


PERIODS = ("breakfast", "morning", "lunch", "afternoon", "dinner", "evening")
EXCLUSIONS = [
    ("不安排早餐", {"morning", "lunch", "afternoon", "dinner", "evening"}),
    ("晚上休息", {"breakfast", "morning", "lunch", "afternoon", "dinner"}),
    ("只安排上午和下午", {"morning", "afternoon"}),
    ("只安排上午下午", {"morning", "afternoon"}),
    ("不安排早餐，晚上休息", {"morning", "lunch", "afternoon", "dinner"}),
]


def candidates():
    return CollectedInfo(pois=[
        POIInfo(poi_id=period, name=f"候选{index}", location="118.8,32.0",
                category="餐饮服务" if period in {"breakfast", "lunch", "dinner"} else "风景名胜")
        for index, period in enumerate(PERIODS)
    ])


def plan(periods):
    info = candidates()
    return Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(poi_id=poi.poi_id, poi_name=poi.name, period=poi.poi_id,
                      activity_type="FOOD" if poi.category == "餐饮服务" else "ATTRACTION")
        for poi in info.pois if poi.poi_id in periods
    ])])


def requirement(text="", field="constraints"):
    return TravelRequirement(intent="trip_planning", city="南京", duration_days=1,
                             **{field: [text] if text else []})


@pytest.mark.parametrize("field", ["constraints", "preferences"])
def test_meal_fill_does_not_add_explicitly_excluded_breakfast(field):
    result = StructuredItineraryGenerator._fill_missing_meals(
        plan({"morning", "afternoon", "evening"}),
        requirement("不安排早餐", field), candidates(),
    )
    assert {item.period for item in result.days[0].items} == {
        "morning", "lunch", "afternoon", "dinner", "evening",
    }


@pytest.mark.parametrize("text,allowed", EXCLUSIONS)
def test_sufficient_candidates_do_not_require_excluded_periods(text, allowed):
    StructuredItineraryGenerator._validate_requested_periods(
        plan(allowed), requirement(text), candidates(),
    )


@pytest.mark.parametrize("text,allowed", EXCLUSIONS)
def test_fallback_only_uses_allowed_periods(text, allowed):
    result = fallback_itinerary(requirement(text), candidates())
    assert {item.period for item in result.days[0].items} == allowed


@pytest.mark.parametrize("text,allowed", EXCLUSIONS)
def test_generator_rejects_explicitly_excluded_items(text, allowed):
    with pytest.raises(ValueError, match="excluded period"):
        StructuredItineraryGenerator(None)._validate_itinerary(
            plan(PERIODS), requirement(text), candidates(),
        )


@pytest.mark.parametrize("text,allowed", EXCLUSIONS)
def test_preview_hides_excluded_items_and_accepts_corrected_plan(text, allowed):
    class Client:
        calls = 0

        def complete_structured_stream(self, **kwargs):
            self.calls += 1
            output = plan(PERIODS if self.calls == 1 else allowed)
            kwargs["on_delta"](output.model_dump_json())
            return output

    previews = []
    result = StructuredItineraryGenerator(Client(), on_preview=previews.append).generate(
        requirement(text), candidates(),
    )
    assert {item.period for item in result.days[0].items} == allowed
    assert any(previews)
    for poi in candidates().pois:
        if poi.poi_id not in allowed:
            assert all(poi.name not in preview for preview in previews)


def test_excluding_breakfast_keeps_default_evening_requirement():
    with pytest.raises(ValueError, match="evening"):
        StructuredItineraryGenerator._validate_requested_periods(
            plan({"morning", "lunch", "afternoon", "dinner"}),
            requirement("不安排早餐"), candidates(),
        )


def test_no_exclusions_keeps_all_six_default_periods():
    result = fallback_itinerary(requirement(), candidates())
    assert {item.period for item in result.days[0].items} == set(PERIODS)
    with pytest.raises(ValueError, match="breakfast"):
        StructuredItineraryGenerator._validate_requested_periods(
            plan(set(PERIODS) - {"breakfast"}), requirement(), candidates(),
        )


@pytest.mark.parametrize("text", [
    "晚上不休息，要安排景点",
    "不仅安排上午和下午，晚上也要游玩",
    "早餐不安排辣菜",
])
def test_non_exclusion_statements_keep_default_periods(text):
    result = fallback_itinerary(requirement(text), candidates())
    assert {item.period for item in result.days[0].items} == set(PERIODS)
