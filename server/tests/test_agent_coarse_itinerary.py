import pytest

from app.agent.budget import AgentTimeoutError
from app.agent.generator import StructuredItineraryGenerator, fallback_itinerary
from app.agent.graph import (
    _collection_route, _initialize_information_node, _itinerary_generator_node, _validation_route,
    make_initial_state,
)
from app.agent.llm import LLMTimeoutError
from app.agent.models import (
    CollectedInfo, InfoRequirement, InformationStatus, Itinerary, ItineraryDay, ItineraryItem,
    POIInfo, TravelHistoryInfo, TravelRequirement, ValidationIssue, ValidationResult,
)
from app.agent.response import FinalResponseGenerator
from app.agent.validator import ItineraryValidator


class FakeClient:
    def __init__(self, output: dict) -> None:
        self.output = output

    def complete_structured(self, **_kwargs):
        return self.output


def candidates() -> CollectedInfo:
    return CollectedInfo(pois=[
        POIInfo(poi_id="A1", name="中山陵", location="118.858,32.058", category="风景名胜"),
        POIInfo(poi_id="F1", name="鸭血粉丝汤", location="118.800,32.050", category="餐饮服务"),
    ])


def coarse_output() -> dict:
    return {"days": [
        {"day_number": 1, "items": [
            {"poi_id": "A1", "poi_name": "中山陵", "period": "morning", "activity_type": "ATTRACTION"},
            {"poi_id": "F1", "poi_name": "鸭血粉丝汤", "period": "lunch", "activity_type": "FOOD"},
        ]},
        {"day_number": 2, "items": []},
    ]}


def test_undated_coarse_itinerary_generates_valid_readable_two_day_result() -> None:
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=2)
    info = candidates()
    itinerary = StructuredItineraryGenerator(FakeClient(coarse_output())).generate(requirement, info)
    validation = ItineraryValidator().validate(requirement, itinerary, info)
    answer = FinalResponseGenerator().generate(
        requirement, info, InformationStatus(), itinerary, validation,
    )
    assert validation.valid is True
    assert "第1天" in answer and "第2天" in answer
    assert "上午：中山陵" in answer
    assert "午餐：鸭血粉丝汤" in answer
    assert "暂无可靠推荐" in answer
    assert "None" not in answer and "路线时间" not in answer


def test_coarse_generator_rejects_food_in_attraction_period() -> None:
    output = {"days": [{"day_number": 1, "items": [
        {"poi_id": "F1", "poi_name": "鸭血粉丝汤", "period": "morning", "activity_type": "ATTRACTION"},
    ]}]}
    with pytest.raises(ValueError, match="category|period"):
        StructuredItineraryGenerator(FakeClient(output)).generate(
            TravelRequirement(intent="trip_planning", city="南京", duration_days=1), candidates(),
        )


def test_coarse_generator_rejects_duplicate_period_and_poi() -> None:
    output = {"days": [{"day_number": 1, "items": [
        {"poi_id": "A1", "poi_name": "中山陵", "period": "morning", "activity_type": "ATTRACTION"},
        {"poi_id": "A1", "poi_name": "中山陵", "period": "morning", "activity_type": "ATTRACTION"},
    ]}]}
    with pytest.raises(ValueError, match="duplicate"):
        StructuredItineraryGenerator(FakeClient(output)).generate(
            TravelRequirement(intent="trip_planning", city="南京", duration_days=1), candidates(),
        )


def test_coarse_generator_rejects_fabricated_date_when_request_has_none() -> None:
    output = {"days": [{"date": "2026-10-01", "day_number": 1, "items": []}]}
    with pytest.raises(ValueError, match="date"):
        StructuredItineraryGenerator(FakeClient(output)).generate(
            TravelRequirement(intent="trip_planning", city="南京", duration_days=1), candidates(),
        )


def test_llm_timeout_returns_sparse_verified_itinerary_without_visited_place() -> None:
    class TimeoutClient:
        def complete_structured(self, **_kwargs):
            raise LLMTimeoutError("provider timeout")

    requirement = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=2,
        constraints=["不要去以前去过的景点"],
    )
    info = candidates()
    info.history = TravelHistoryInfo(visited_poi_ids=["A1"])
    state = make_initial_state("南京两日游")
    state["requirement"] = requirement
    state["collected_info"] = info
    itinerary = _itinerary_generator_node(
        StructuredItineraryGenerator(TimeoutClient()), None,
    )(state)["itinerary"]
    assert len(itinerary.days) == 2
    assert all(day.date is None for day in itinerary.days)
    assert all(item.poi_id != "A1" for day in itinerary.days for item in day.items)
    assert [item.poi_id for day in itinerary.days for item in day.items] == ["F1"]


def test_planning_budget_is_precomputed_without_llm_tool_choice() -> None:
    state = make_initial_state("两人南京三日游预算两千元")
    state["requirement"] = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=3,
        travelers=2, budget=2000,
    )
    initialized = _initialize_information_node(state)
    assert initialized["collected_info"].budget is not None
    assert initialized["information_status"].budget.status == "completed"
    assert initialized["collected_info"].budget.estimated_max > 0


def test_rough_budget_over_limit_does_not_trigger_llm_revision() -> None:
    state = make_initial_state("南京三日游预算一百元")
    state["validation"] = ValidationResult(valid=False, issues=[ValidationIssue(
        type="budget", status="fail", message="预算估算上限超过用户预算。",
    )])
    assert _validation_route(state, max_validation_rounds=2) == "validation_finish"


def test_period_item_rejects_hidden_clock_time() -> None:
    with pytest.raises(ValueError, match="period.*time"):
        ItineraryItem(
            poi_id="A1", poi_name="中山陵", period="morning",
            start_time="09:00", end_time="11:00", activity_type="ATTRACTION",
        )


def test_period_item_rejects_unverified_item_price() -> None:
    with pytest.raises(ValueError, match="estimated_cost"):
        ItineraryItem(
            poi_id="A1", poi_name="中山陵", period="morning",
            activity_type="ATTRACTION", estimated_cost=100,
        )


def test_invalid_llm_itinerary_falls_back_to_three_dated_days() -> None:
    requirement = TravelRequirement(
        intent="trip_planning", city="南京", start_date="2026-10-01",
        duration_days=3,
    )
    state = make_initial_state("十月一日开始南京三日游")
    state["requirement"] = requirement
    state["collected_info"] = candidates()
    itinerary = _itinerary_generator_node(
        StructuredItineraryGenerator(FakeClient({"days": []})), None,
    )(state)["itinerary"]
    assert [day.date for day in itinerary.days] == [
        "2026-10-01", "2026-10-02", "2026-10-03",
    ]
    assert [item.poi_id for day in itinerary.days for item in day.items] == ["F1", "A1"]
    assert ItineraryValidator().validate(requirement, itinerary, candidates()).valid


def test_end_date_without_departure_date_is_rejected_cleanly() -> None:
    with pytest.raises(ValueError, match="start_date"):
        StructuredItineraryGenerator(FakeClient(coarse_output())).generate(
            TravelRequirement(
                intent="trip_planning", city="南京", duration_days=2,
                end_date="2026-10-03",
            ), candidates(),
        )


def test_itinerary_rejects_unmodeled_route_claim() -> None:
    output = coarse_output()
    output["days"][0]["items"][0]["route_minutes"] = 10
    with pytest.raises(ValueError, match="route_minutes"):
        StructuredItineraryGenerator(FakeClient(output)).generate(
            TravelRequirement(intent="trip_planning", city="南京", duration_days=2),
            candidates(),
        )


def test_itinerary_stage_budget_timeout_uses_verified_fallback() -> None:
    class StageTimeoutClient:
        def complete_structured(self, **_kwargs):
            raise AgentTimeoutError("itinerary_generator stage timeout exceeded")

    state = make_initial_state("南京一日游")
    state["requirement"] = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=1,
    )
    state["collected_info"] = candidates()
    itinerary = _itinerary_generator_node(
        StructuredItineraryGenerator(StageTimeoutClient()), None,
    )(state)["itinerary"]
    assert [item.poi_id for item in itinerary.days[0].items] == ["F1", "A1"]


def test_planning_budget_is_labeled_as_non_realtime_estimate() -> None:
    requirement = TravelRequirement(
        intent="trip_planning", city="南京", duration_days=1, travelers=1,
    )
    state = make_initial_state("南京一日游")
    state["requirement"] = requirement
    initialized = _initialize_information_node(state)
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[])])
    answer = FinalResponseGenerator().generate(
        requirement, initialized["collected_info"],
        initialized["information_status"], itinerary,
        ValidationResult(valid=True),
    )
    assert "人民币" in answer
    assert "非实时" in answer or "粗估" in answer


def test_completed_planning_information_skips_extra_react_decision() -> None:
    state = make_initial_state("南京一日游")
    state["requirement"] = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)
    state["information_status"] = InformationStatus(
        pois=InfoRequirement(status="completed", critical=True),
        budget=InfoRequirement(status="completed"),
    )
    state["react_round"] = 1
    state["react_action"] = "tool"
    assert _collection_route(state, max_react_rounds=4) == "information_complete"


def test_validator_rejects_duplicate_poi_after_revision() -> None:
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(
            poi_id="A1", poi_name="中山陵", period="morning", activity_type="ATTRACTION",
        ),
        ItineraryItem(
            poi_id="A1", poi_name="中山陵", period="afternoon", activity_type="ATTRACTION",
        ),
    ])])
    result = ItineraryValidator().validate(requirement, itinerary, candidates())
    assert result.valid is False
    assert any(issue.type == "constraint" and issue.status == "fail" for issue in result.issues)


def test_validator_rejects_food_candidate_used_as_attraction() -> None:
    requirement = TravelRequirement(intent="trip_planning", city="南京", duration_days=1)
    itinerary = Itinerary(days=[ItineraryDay(day_number=1, items=[
        ItineraryItem(
            poi_id="F1", poi_name="鸭血粉丝汤", period="morning",
            activity_type="ATTRACTION",
        ),
    ])])
    result = ItineraryValidator().validate(requirement, itinerary, candidates())
    assert result.valid is False
    assert any(issue.type == "constraint" and issue.status == "fail" for issue in result.issues)


def test_fallback_keeps_verified_museum_candidate() -> None:
    info = CollectedInfo(pois=[POIInfo(
        poi_id="M1", name="南京博物院", location="118.830000,32.040000",
        category="科教文化服务;博物馆",
    )])
    itinerary = fallback_itinerary(
        TravelRequirement(intent="trip_planning", city="南京", duration_days=1), info,
    )
    assert [item.poi_id for item in itinerary.days[0].items] == ["M1"]
