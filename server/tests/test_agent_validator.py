from app.agent.models import (
    BudgetInfo,
    CollectedInfo,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    RouteInfo,
    TravelHistoryInfo,
    TravelRequirement,
)
from app.agent.validator import ItineraryValidator, ValidatorConfig


def base_requirement() -> TravelRequirement:
    return TravelRequirement(
        intent="trip_planning",
        destination="南京",
        duration_days=1,
        budget=1000,
    )


def base_info() -> CollectedInfo:
    return CollectedInfo(
        pois=[
            POIInfo(
                poi_id="P1",
                name="中山陵",
                location="118.858,32.058",
                opening_hours="08:00-18:00",
            ),
            POIInfo(
                poi_id="P2",
                name="夫子庙",
                location="118.789,32.022",
                opening_hours="09:00-18:00",
            ),
        ],
        routes=[
            RouteInfo(
                origin_id="P1",
                destination_id="P2",
                mode="transit",
                distance_meters=8000,
                duration_minutes=30,
            )
        ],
        budget=BudgetInfo(estimated_min=700, estimated_max=900),
    )


def base_itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="P1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="11:00",
                        activity_type="游览",
                    ),
                    ItineraryItem(
                        poi_id="P2",
                        poi_name="夫子庙",
                        start_time="12:00",
                        end_time="14:00",
                        activity_type="游览",
                    ),
                ],
            )
        ]
    )


def validate(
    requirement: TravelRequirement | None = None,
    info: CollectedInfo | None = None,
    itinerary: Itinerary | None = None,
    *,
    config: ValidatorConfig | None = None,
):
    return ItineraryValidator(config=config).validate(
        requirement or base_requirement(),
        itinerary or base_itinerary(),
        info or base_info(),
    )


def test_validator_returns_pass_for_consistent_itinerary() -> None:
    result = validate()

    assert result.valid is True
    assert result.issues == []


def test_validator_reports_overlapping_activities() -> None:
    itinerary = base_itinerary()
    itinerary.days[0].items[1].start_time = "10:30"

    result = validate(itinerary=itinerary)

    assert result.valid is False
    assert any(issue.type == "time_conflict" for issue in result.issues)
    conflict = next(issue for issue in result.issues if issue.type == "time_conflict")
    assert conflict.status == "fail"
    assert conflict.day == 1
    assert conflict.related_poi_ids == ["P1", "P2"]


def test_validator_reports_insufficient_travel_time() -> None:
    itinerary = base_itinerary()
    itinerary.days[0].items[1].start_time = "11:15"

    result = validate(itinerary=itinerary)

    assert result.valid is False
    assert any(issue.type == "travel_time" for issue in result.issues)


def test_validator_marks_missing_route_as_unknown() -> None:
    info = base_info()
    info.routes = []

    result = validate(info=info)

    assert result.valid is True
    route_issue = next(issue for issue in result.issues if issue.type == "travel_time")
    assert route_issue.status == "unknown"


def test_validator_checks_opening_hours_and_unknown_hours() -> None:
    itinerary = base_itinerary()
    itinerary.days[0].items[0].start_time = "07:00"
    fail_result = validate(itinerary=itinerary)

    assert fail_result.valid is False
    assert any(issue.type == "opening_hours" and issue.status == "fail" for issue in fail_result.issues)

    info = base_info()
    info.pois[0].opening_hours = None
    unknown_result = validate(info=info)

    assert unknown_result.valid is True
    assert any(
        issue.type == "opening_hours" and issue.status == "unknown"
        for issue in unknown_result.issues
    )


def test_validator_checks_previous_place_constraint() -> None:
    requirement = base_requirement()
    requirement.constraints = ["不要去以前去过的景点"]
    info = base_info()
    info.history = TravelHistoryInfo(visited_poi_ids=["P1"])

    result = validate(requirement=requirement, info=info)

    assert result.valid is False
    constraint_issue = next(issue for issue in result.issues if issue.type == "constraint")
    assert constraint_issue.status == "fail"
    assert constraint_issue.related_poi_ids == ["P1"]


def test_validator_marks_missing_history_as_unknown_and_ignores_preferences() -> None:
    requirement = base_requirement()
    requirement.constraints = ["不要去以前去过的景点"]
    requirement.preferences = ["历史文化"]

    result = validate(requirement=requirement)

    assert result.valid is True
    constraint_issue = next(issue for issue in result.issues if issue.type == "constraint")
    assert constraint_issue.status == "unknown"
    assert not any(issue.status == "fail" for issue in result.issues)


def test_validator_checks_budget_upper_bound_and_missing_estimate() -> None:
    requirement = base_requirement()
    requirement.budget = 800
    fail_result = validate(requirement=requirement)

    assert fail_result.valid is False
    assert any(issue.type == "budget" and issue.status == "fail" for issue in fail_result.issues)

    unknown_result = validate(
        requirement=requirement,
        info=base_info().model_copy(update={"budget": None}),
    )
    assert unknown_result.valid is True
    assert any(
        issue.type == "budget" and issue.status == "unknown"
        for issue in unknown_result.issues
    )


def test_validator_uses_configured_daily_load_limit() -> None:
    itinerary = base_itinerary()
    itinerary.days[0].items = [
        ItineraryItem(
            poi_id="P1",
            poi_name="中山陵",
            start_time="08:00",
            end_time="18:00",
            activity_type="游览",
        )
    ]

    result = validate(
        itinerary=itinerary,
        config=ValidatorConfig(max_daily_minutes=540),
    )

    assert result.valid is False
    daily_issue = next(issue for issue in result.issues if issue.type == "daily_load")
    assert daily_issue.status == "fail"
