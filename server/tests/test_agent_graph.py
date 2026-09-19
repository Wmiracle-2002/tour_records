from collections.abc import Sequence

from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.models import (
    CollectedInfo,
    InfoRequirement,
    InformationStatus,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    POIInfo,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
)
from app.agent.response import FinalResponseGenerator


class FakeAnalyzer:
    def __init__(self, requirement: TravelRequirement) -> None:
        self.requirement = requirement

    def analyze(self, user_query: str) -> TravelRequirement:
        return self.requirement


class FakeCollector:
    def __init__(
        self,
        information_status: InformationStatus,
        collected_info: CollectedInfo,
    ) -> None:
        self.information_status = information_status
        self.collected_info = collected_info
        self.max_rounds = 2
        self.calls = 0

    def collect_round(self, state):
        self.calls += 1
        updated = dict(state)
        updated["information_status"] = self.information_status.model_copy(deep=True)
        updated["collected_info"] = self.collected_info.model_copy(deep=True)
        updated["react_round"] += 1
        return updated


class FakeGenerator:
    def __init__(self, itinerary: Itinerary) -> None:
        self.itinerary = itinerary
        self.calls = 0

    def generate(self, requirement, collected_info) -> Itinerary:
        self.calls += 1
        return self.itinerary.model_copy(deep=True)


class FakeValidator:
    def __init__(self, results: Sequence[ValidationResult]) -> None:
        self.results = list(results)
        self.calls = 0

    def validate(self, requirement, itinerary, collected_info) -> ValidationResult:
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result.model_copy(deep=True)


class FakeReviser:
    def __init__(self) -> None:
        self.calls = 0

    def revise(self, itinerary, issues, requirement, collected_info) -> Itinerary:
        self.calls += 1
        return itinerary.model_copy(deep=True)


def _build_graph(
    requirement: TravelRequirement,
    information_status: InformationStatus,
    collected_info: CollectedInfo,
    *,
    itinerary: Itinerary | None = None,
    validation_results: Sequence[ValidationResult] = (),
):
    generator = FakeGenerator(itinerary or Itinerary(days=[]))
    validator = FakeValidator(validation_results or [ValidationResult(valid=True)])
    reviser = FakeReviser()
    collector = FakeCollector(information_status, collected_info)
    graph = build_agent_graph(
        analyzer=FakeAnalyzer(requirement),
        collector=collector,
        itinerary_generator=generator,
        validator=validator,
        reviser=reviser,
        response_generator=FinalResponseGenerator(),
    )
    return graph, generator, validator, reviser, collector


def test_graph_compiles_and_routes_non_trip_request_to_final_response() -> None:
    requirement = TravelRequirement(intent="general_query")
    graph, generator, validator, reviser, _ = _build_graph(
        requirement,
        InformationStatus(),
        CollectedInfo(),
    )

    result = graph.invoke(make_initial_state("你能做什么？"))

    assert result["requirement"] == requirement
    assert "通用旅行问答" in result["final_response"]
    assert generator.calls == 0
    assert validator.calls == 0
    assert reviser.calls == 0


def test_graph_finishes_with_available_final_response_when_information_is_incomplete() -> None:
    requirement = TravelRequirement(intent="general_query")
    graph, _, validator, _, collector = _build_graph(
        requirement,
        InformationStatus(pois=InfoRequirement(status="pending")),
        CollectedInfo(),
    )

    result = graph.invoke(make_initial_state("给我一个旅行建议。"))

    assert result["final_response"] is not None
    assert validator.calls == 0
    assert collector.calls == 2


def test_graph_degrades_incomplete_trip_before_itinerary_generation() -> None:
    requirement = TravelRequirement(
        intent="trip_planning",
        destination="南京",
        duration_days=1,
    )
    graph, generator, validator, reviser, collector = _build_graph(
        requirement,
        InformationStatus(pois=InfoRequirement(status="pending")),
        CollectedInfo(),
    )

    result = graph.invoke(make_initial_state("帮我规划南京一日游。"))

    assert result["final_response"] == "当前还没有可展示的完整行程。"
    assert generator.calls == 0
    assert validator.calls == 0
    assert reviser.calls == 0
    assert collector.calls == 2


def test_graph_routes_trip_planning_through_generator_validator_and_final_response() -> None:
    requirement = TravelRequirement(
        intent="trip_planning",
        destination="南京",
        duration_days=1,
    )
    itinerary = Itinerary(
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
                    )
                ],
            )
        ]
    )
    graph, generator, validator, reviser, _ = _build_graph(
        requirement,
        InformationStatus(pois=InfoRequirement(status="completed")),
        CollectedInfo(
            pois=[POIInfo(poi_id="P1", name="中山陵", location="118.8,32.0")]
        ),
        itinerary=itinerary,
        validation_results=[ValidationResult(valid=True)],
    )

    result = graph.invoke(make_initial_state("帮我规划南京一日游。"))

    assert generator.calls == 1
    assert validator.calls == 1
    assert reviser.calls == 0
    assert result["itinerary"] == itinerary
    assert result["validation"].valid is True
    assert "中山陵" in result["final_response"]


def test_graph_revises_failures_before_final_response() -> None:
    requirement = TravelRequirement(intent="trip_planning", destination="南京")
    itinerary = Itinerary(
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
                    )
                ],
            )
        ]
    )
    failure = ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(
                type="time_conflict",
                status="fail",
                day=1,
                related_poi_ids=["P1"],
                message="行程存在时间冲突。",
                suggested_action="调整活动时间。",
            )
        ],
    )
    graph, _, validator, reviser, _ = _build_graph(
        requirement,
        InformationStatus(pois=InfoRequirement(status="completed")),
        CollectedInfo(
            pois=[POIInfo(poi_id="P1", name="中山陵", location="118.8,32.0")]
        ),
        itinerary=itinerary,
        validation_results=[failure, ValidationResult(valid=True)],
    )

    result = graph.invoke(make_initial_state("规划南京一日游。"))

    assert validator.calls == 2
    assert reviser.calls == 1
    assert result["validation"].valid is True
    assert result["validation_round"] == 1
