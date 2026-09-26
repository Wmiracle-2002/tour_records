import pytest
from pydantic import TypeAdapter, ValidationError

from app.agent.models import (
    BudgetInfo,
    CollectedInfo,
    InfoRequirement,
    InformationStatus,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    RouteInfo,
    TravelHistoryInfo,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
    WeatherInfo,
)
from app.agent.state import TravelAgentState


def test_travel_requirement_uses_safe_defaults_and_optional_fields() -> None:
    requirement = TravelRequirement(intent="general_query")

    assert requirement.city is None
    assert requirement.preferences == []
    assert requirement.constraints == []

    other = TravelRequirement(intent="general_query")
    requirement.preferences.append("历史文化")
    assert other.preferences == []


def test_invalid_intent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TravelRequirement(intent="unknown_query")


def test_requirement_uses_city_for_city_and_destination_only_for_route_endpoints() -> None:
    weather = TravelRequirement(intent="weather_query", city="南京")
    route = TravelRequirement(
        intent="route_query", origin="中山陵", destination="夫子庙"
    )

    assert weather.city == "南京"
    assert route.destination == "夫子庙"
    with pytest.raises(ValidationError):
        TravelRequirement(intent="weather_query", destination="南京")


def test_distance_requirement_keeps_city_and_endpoint_names_separate() -> None:
    requirement = TravelRequirement(
        intent="distance_query",
        city="南京",
        origin="中山陵",
        destination="夫子庙",
        distance_mode="straight",
    )
    assert requirement.city == "南京"
    assert requirement.destination == "夫子庙"
    assert requirement.distance_mode == "straight"


def test_weather_requirement_has_explicit_time_kind() -> None:
    requirement = TravelRequirement(
        intent="weather_query",
        city="南京",
        date_expression="今晚",
        start_date="2026-09-25",
        weather_time_kind="forecast_date",
    )
    assert requirement.weather_time_kind == "forecast_date"
    with pytest.raises(ValidationError):
        TravelRequirement(intent="history_query", weather_time_kind="realtime")


def test_itinerary_accepts_day_number_and_coarse_period_without_clock_times() -> None:
    itinerary = Itinerary(
        days=[
            ItineraryDay(
                day_number=1,
                items=[
                    ItineraryItem(
                        poi_id="p1",
                        poi_name="中山陵",
                        period="morning",
                        activity_type="ATTRACTION",
                    ),
                    ItineraryItem(
                        poi_id="p2",
                        poi_name="南京小吃店",
                        period="lunch",
                        activity_type="FOOD",
                    ),
                ],
            )
        ]
    )
    assert itinerary.days[0].date is None
    assert itinerary.days[0].items[0].start_time is None


@pytest.mark.parametrize(
    "item",
    [
        {"poi_id": "p1", "poi_name": "中山陵", "activity_type": "ATTRACTION"},
        {
            "poi_id": "p1",
            "poi_name": "中山陵",
            "activity_type": "ATTRACTION",
            "period": "noonish",
        },
        {
            "poi_id": "p1",
            "poi_name": "中山陵",
            "activity_type": "ATTRACTION",
            "start_time": "09:00",
        },
    ],
)
def test_itinerary_rejects_incomplete_or_unknown_time_slots(item: dict) -> None:
    with pytest.raises(ValidationError):
        ItineraryItem(**item)


def test_itinerary_day_requires_date_or_day_number() -> None:
    with pytest.raises(ValidationError):
        ItineraryDay(items=[])


def test_requirement_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TravelRequirement(intent="general_query", location="南京")


def test_invalid_information_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InfoRequirement(status="unknown")


def test_requirement_lower_boundary_values_are_accepted() -> None:
    requirement = TravelRequirement(
        intent="trip_planning",
        duration_days=1,
        travelers=1,
        budget=0,
    )

    assert requirement.duration_days == 1
    assert requirement.travelers == 1
    assert requirement.budget == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_days", 0),
        ("travelers", 0),
        ("budget", -0.01),
    ],
)
def test_requirement_values_below_lower_bound_are_rejected(
    field: str, value: float
) -> None:
    with pytest.raises(ValidationError):
        TravelRequirement(intent="trip_planning", **{field: value})


@pytest.mark.parametrize("value", ["国庆", "2026/10/01", "2026-02-30"])
def test_requirement_dates_must_be_valid_iso_dates(value: str) -> None:
    with pytest.raises(ValidationError):
        TravelRequirement(intent="trip_planning", start_date=value)


def test_zero_boundaries_are_accepted_for_collected_info() -> None:
    history = TravelHistoryInfo(trip_count=0)
    info_requirement = InfoRequirement(attempts=0)
    route = RouteInfo(
        origin_id="poi-1",
        destination_id="poi-2",
        mode="walking",
        distance_meters=0,
        duration_minutes=0,
    )
    budget = BudgetInfo(estimated_min=0, estimated_max=0)

    assert history.trip_count == 0
    assert info_requirement.attempts == 0
    assert route.distance_meters == 0
    assert route.duration_minutes == 0
    assert budget.estimated_min == 0
    assert budget.estimated_max == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: InfoRequirement(attempts=-1),
        lambda: TravelHistoryInfo(trip_count=-1),
        lambda: RouteInfo(
            origin_id="poi-1",
            destination_id="poi-2",
            mode="walking",
            distance_meters=-1,
            duration_minutes=0,
        ),
        lambda: RouteInfo(
            origin_id="poi-1",
            destination_id="poi-2",
            mode="walking",
            distance_meters=0,
            duration_minutes=-1,
        ),
        lambda: BudgetInfo(estimated_min=-1, estimated_max=0),
        lambda: BudgetInfo(estimated_min=0, estimated_max=-1),
    ],
)
def test_values_below_zero_are_rejected(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_collected_info_contains_structured_business_models() -> None:
    info = CollectedInfo(
        history=TravelHistoryInfo(
            trip_count=1,
            visited_cities=["南京"],
            visited_names=["夫子庙"],
        ),
        pois=[
            POIInfo(
                poi_id="poi-1",
                name="中山陵",
                location="118.85,32.06",
            )
        ],
        weather=WeatherInfo(
            location="南京",
            date="2026-10-01",
            description="晴",
        ),
        routes=[
            RouteInfo(
                origin_id="poi-1",
                destination_id="poi-2",
                mode="walking",
                distance_meters=1200,
                duration_minutes=18,
            )
        ],
        budget=BudgetInfo(
            estimated_min=800,
            estimated_max=1200,
            breakdown={"food": 300},
            assumptions=["按两人估算"],
        ),
    )

    assert info.pois[0].poi_id == "poi-1"
    assert info.routes[0].duration_minutes == 18
    assert info.budget is not None


def test_itinerary_round_trips_through_json() -> None:
    itinerary = Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="poi-1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="11:00",
                        activity_type="attraction",
                    )
                ],
            )
        ]
    )

    restored = Itinerary.model_validate_json(itinerary.model_dump_json())

    assert restored.days[0].items[0].poi_id == "poi-1"
    assert restored.days[0].items[0].estimated_cost is None


def test_validation_result_serializes_issue_status_and_type() -> None:
    result = ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(
                type="travel_time",
                status="fail",
                day=1,
                related_poi_ids=["poi-1", "poi-2"],
                message="移动时间不足",
            )
        ],
    )

    payload = result.model_dump(mode="json")

    assert payload["issues"][0]["type"] == "travel_time"
    assert payload["issues"][0]["status"] == "fail"


def test_complete_state_validates_and_round_trips() -> None:
    state: TravelAgentState = {
        "messages": [{"role": "user", "content": "帮我规划南京三日游"}],
        "requirement": TravelRequirement(
            intent="trip_planning",
            city="南京",
            duration_days=3,
        ),
        "information_status": InformationStatus(
            history=InfoRequirement(status="pending", critical=False)
        ),
        "collected_info": CollectedInfo(),
        "itinerary": None,
        "validation": None,
        "react_round": 0,
        "validation_round": 0,
        "final_response": None,
    }

    adapter = TypeAdapter(TravelAgentState)
    restored = adapter.validate_json(adapter.dump_json(state))

    assert restored["requirement"].intent == "trip_planning"
    assert restored["information_status"].history.status == "pending"
