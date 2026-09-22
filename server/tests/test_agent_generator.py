import pytest

from app.agent.generator import (
    ITINERARY_GENERATOR_SYSTEM_PROMPT,
    StructuredItineraryGenerator,
)
from app.agent.models import (
    CollectedInfo,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    TravelHistoryInfo,
    TravelRequirement,
)


class FakeItineraryClient:
    def __init__(self, response) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls: list[dict] = []

    def complete_structured(self, *, system_prompt, user_prompt, output_model):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "output_model": output_model,
            }
        )
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def build_requirement() -> TravelRequirement:
    return TravelRequirement(
        intent="trip_planning",
        destination="南京",
        start_date="2026-10-01",
        duration_days=2,
        preferences=["历史文化"],
        constraints=["每天安排不要太满"],
    )


def build_collected_info() -> CollectedInfo:
    return CollectedInfo(
        pois=[
            POIInfo(
                poi_id="B1",
                name="中山陵",
                location="118.858,32.058",
                category="历史文化",
            ),
            POIInfo(
                poi_id="B2",
                name="夫子庙",
                location="118.789,32.022",
                category="历史文化",
            ),
        ]
    )


def build_itinerary() -> Itinerary:
    return Itinerary(
        days=[
            ItineraryDay(
                date="2026-10-01",
                items=[
                    ItineraryItem(
                        poi_id="B1",
                        poi_name="中山陵",
                        start_time="09:00",
                        end_time="12:00",
                        activity_type="游览",
                    )
                ],
            ),
            ItineraryDay(
                date="2026-10-02",
                items=[
                    ItineraryItem(
                        poi_id="B2",
                        poi_name="夫子庙",
                        start_time="10:00",
                        end_time="12:00",
                        activity_type="游览",
                    )
                ],
            ),
        ]
    )


def test_generator_requests_structured_itinerary_and_preserves_poi_ids() -> None:
    client = FakeItineraryClient(build_itinerary())

    result = StructuredItineraryGenerator(client).generate(
        build_requirement(),
        build_collected_info(),
    )

    assert result == build_itinerary()
    assert client.calls[0]["output_model"] is Itinerary
    assert "历史文化" in client.calls[0]["user_prompt"]
    assert "中山陵" in client.calls[0]["user_prompt"]
    assert "不要输出自然语言旅行攻略" in ITINERARY_GENERATOR_SYSTEM_PROMPT


def test_generator_prompt_declares_exact_itinerary_shape() -> None:
    assert "根对象只能包含 days" in ITINERARY_GENERATOR_SYSTEM_PROMPT
    assert "不要使用 itinerary 字段包裹" in ITINERARY_GENERATOR_SYSTEM_PROMPT
    assert "poi_id、poi_name、start_time、end_time、activity_type" in ITINERARY_GENERATOR_SYSTEM_PROMPT
    assert "days 必须恰好包含 duration_days 天" in ITINERARY_GENERATOR_SYSTEM_PROMPT


def test_generator_rejects_poi_that_is_not_in_collected_info() -> None:
    itinerary = build_itinerary()
    itinerary.days[0].items[0].poi_id = "UNKNOWN"
    client = FakeItineraryClient(itinerary)

    with pytest.raises(ValueError, match="unknown poi_id"):
        StructuredItineraryGenerator(client).generate(
            build_requirement(),
            build_collected_info(),
        )


def test_generator_rejects_duration_mismatch() -> None:
    itinerary = build_itinerary()
    itinerary.days.pop()
    client = FakeItineraryClient(itinerary)

    with pytest.raises(ValueError, match="duration_days"):
        StructuredItineraryGenerator(client).generate(
            build_requirement(),
            build_collected_info(),
        )


def test_generator_retries_after_business_validation_failure() -> None:
    invalid_itinerary = build_itinerary()
    invalid_itinerary.days.clear()
    client = FakeItineraryClient([invalid_itinerary, build_itinerary()])

    result = StructuredItineraryGenerator(client).generate(
        build_requirement(),
        build_collected_info(),
    )

    assert result == build_itinerary()
    assert len(client.calls) == 2
    assert "previous itinerary failed validation" in client.calls[1]["user_prompt"]


def test_generator_rejects_dates_that_do_not_start_from_requirement_date() -> None:
    itinerary = build_itinerary()
    itinerary.days[0].date = "2026-10-02"
    client = FakeItineraryClient(itinerary)

    with pytest.raises(ValueError, match="start_date"):
        StructuredItineraryGenerator(client).generate(
            build_requirement(),
            build_collected_info(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date", "2026/10/01"),
        ("start_time", "9:00"),
        ("end_time", "25:00"),
    ],
)
def test_generator_rejects_invalid_date_or_time_format(field: str, value: str) -> None:
    itinerary = build_itinerary()
    if field == "date":
        itinerary.days[0].date = value
    else:
        setattr(itinerary.days[0].items[0], field, value)
    client = FakeItineraryClient(itinerary)

    with pytest.raises(ValueError, match="date or time"):
        StructuredItineraryGenerator(client).generate(
            build_requirement(),
            build_collected_info(),
        )


def test_generator_rejects_known_visited_poi_when_constraint_avoids_previous_places() -> None:
    client = FakeItineraryClient(build_itinerary())
    collected = build_collected_info()
    collected.history = TravelHistoryInfo(visited_poi_ids=["B1"])
    requirement = build_requirement()
    requirement.constraints = ["不要去以前去过的景点"]

    with pytest.raises(ValueError, match="previously visited"):
        StructuredItineraryGenerator(client).generate(requirement, collected)
