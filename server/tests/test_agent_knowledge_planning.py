from app.agent.graph import _initialize_information_node, make_initial_state
from app.agent.models import (
    CollectedInfo, InformationStatus, Itinerary, ItineraryDay, ItineraryItem,
    KnowledgeInfo, POIInfo, TravelRequirement,
)
from app.agent.response import FinalResponseGenerator


def note(title: str, excerpt: str) -> KnowledgeInfo:
    return KnowledgeInfo(
        id=42, title=title, category="food_guide", city_code="320100",
        tags=["小吃"], excerpt=excerpt, updated_at="2026-09-30T00:00:00",
    )


def test_planning_collects_bounded_user_knowledge_after_requirement_analysis() -> None:
    state = make_initial_state("规划南京一日游")
    state["requirement"] = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=1,
    )
    calls = []
    result = _initialize_information_node(
        state, knowledge_searcher=lambda city, preferences, kind: (
            calls.append((city, preferences)) or [note("南京小吃", "鸭血粉丝汤")]
        ),
    )
    assert calls == [("南京", [])]
    assert result["collected_info"].knowledge[0].id == 42


def test_final_answer_cites_only_notes_relevant_to_verified_selected_pois() -> None:
    info = CollectedInfo(
        pois=[POIInfo(poi_id="F1", name="鸭血粉丝汤", location="118.8,32.0", category="餐饮服务")],
        knowledge=[note("南京小吃", "鸭血粉丝汤值得尝试")],
    )
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(poi_id="F1", poi_name="鸭血粉丝汤", period="lunch", activity_type="FOOD"),
    ])])
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)
    answer = FinalResponseGenerator().generate(
        requirement, info, InformationStatus(), itinerary,
    )
    assert "南京小吃" in answer and "收藏#42" in answer

    info.knowledge = [note("南京博物馆", "请提前预约")]
    unrelated = FinalResponseGenerator().generate(
        requirement, info, InformationStatus(), itinerary,
    )
    assert "收藏#42" not in unrelated
