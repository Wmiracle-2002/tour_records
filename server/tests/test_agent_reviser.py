from dataclasses import dataclass
from typing import Any

from app.agent.models import (
    CollectedInfo,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    RouteInfo,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
)
from app.agent.reviser import (
    MAX_VALIDATION_ROUNDS,
    ItineraryValidationLoop,
    LocalItineraryReviser,
)
from app.agent.validator import ItineraryValidator


class FakeRevisionClient:
    def __init__(self, response: Itinerary) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete_structured(self, *, system_prompt, user_prompt, output_model):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "output_model": output_model,
            }
        )
        return self.response


def build_requirement() -> TravelRequirement:
    return TravelRequirement(intent="trip_planning", city="南京", duration_days=2)


def build_info() -> CollectedInfo:
    return CollectedInfo(
        pois=[
            POIInfo(poi_id="P1", name="中山陵", location="118.858,32.058", opening_hours="08:00-18:00"),
            POIInfo(poi_id="P2", name="夫子庙", location="118.789,32.022", opening_hours="08:00-18:00"),
            POIInfo(poi_id="P3", name="玄武湖", location="118.796,32.070", opening_hours="08:00-18:00"),
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
    )


def build_itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="P1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="10:00",
                        activity_type="游览",
                    ),
                    ItineraryItem(
                        poi_id="P2",
                        poi_name="夫子庙",
                        start_time="10:15",
                        end_time="12:00",
                        activity_type="游览",
                    ),
                ],
            ),
            ItineraryDay(
                date="2026-10-02",
                items=[
                    ItineraryItem(
                        poi_id="P3",
                        poi_name="玄武湖",
                        start_time="09:00",
                        end_time="11:00",
                        activity_type="游览",
                    )
                ],
            ),
        ]
    )


def travel_time_issue() -> ValidationIssue:
    return ValidationIssue(
        type="travel_time",
        status="fail",
        day=1,
        related_poi_ids=["P1", "P2"],
        message="从中山陵到夫子庙的移动时间不足。",
    )


def test_reviser_returns_structured_itinerary_and_preserves_unrelated_day() -> None:
    revised = build_itinerary()
    revised.days[0].items[1].start_time = "10:45"
    client = FakeRevisionClient(revised)

    result = LocalItineraryReviser(client).revise(
        build_itinerary(),
        [travel_time_issue()],
        build_requirement(),
        build_info(),
    )

    assert result.days[0].items[1].start_time == "10:45"
    assert result.days[1] == build_itinerary().days[1]
    assert client.calls[0]["output_model"] is Itinerary
    assert "移动时间不足" in client.calls[0]["user_prompt"]


def test_reviser_rejects_changes_outside_validation_scope() -> None:
    revised = build_itinerary()
    revised.days[1].items[0].start_time = "10:00"
    client = FakeRevisionClient(revised)

    try:
        LocalItineraryReviser(client).revise(
            build_itinerary(),
            [travel_time_issue()],
            build_requirement(),
            build_info(),
        )
    except ValueError as error:
        assert "scope" in str(error)
    else:
        raise AssertionError("Expected out-of-scope revision to be rejected")


def test_reviser_does_not_call_client_when_there_are_no_failures() -> None:
    client = FakeRevisionClient(build_itinerary())
    itinerary = build_itinerary()
    issues = [
        ValidationIssue(
            type="travel_time",
            status="unknown",
            day=1,
            related_poi_ids=["P1", "P2"],
            message="没有可靠路线时间。",
        )
    ]

    result = LocalItineraryReviser(client).revise(
        itinerary,
        issues,
        build_requirement(),
        build_info(),
    )

    assert result == itinerary
    assert client.calls == []


@dataclass
class FakeLoopReviser:
    replacement: Itinerary
    calls: int = 0

    def revise(self, current, issues, requirement, collected_info) -> Itinerary:
        self.calls += 1
        return self.replacement.model_copy(deep=True)


def test_validation_loop_revises_then_revalidates_until_valid() -> None:
    invalid = build_itinerary()
    fixed = build_itinerary()
    fixed.days[0].items[1].start_time = "11:00"
    reviser = FakeLoopReviser(fixed)

    result = ItineraryValidationLoop(ItineraryValidator(), reviser).run(
        build_requirement(), invalid, build_info()
    )

    assert result.validation.valid is True
    assert result.itinerary == fixed
    assert result.revision_rounds == 1
    assert reviser.calls == 1


def test_validation_loop_stops_after_maximum_revision_rounds() -> None:
    invalid = build_itinerary()
    reviser = FakeLoopReviser(invalid)

    result = ItineraryValidationLoop(ItineraryValidator(), reviser).run(
        build_requirement(), invalid, build_info()
    )

    assert result.validation.valid is False
    assert result.revision_rounds == MAX_VALIDATION_ROUNDS
    assert reviser.calls == MAX_VALIDATION_ROUNDS


def test_validation_loop_does_not_revise_unknown_only_results() -> None:
    info = build_info().model_copy(deep=True)
    info.routes = []
    reviser = FakeLoopReviser(build_itinerary())

    result = ItineraryValidationLoop(ItineraryValidator(), reviser).run(
        build_requirement(), build_itinerary(), info
    )

    assert result.validation.valid is True
    assert result.revision_rounds == 0
    assert reviser.calls == 0
