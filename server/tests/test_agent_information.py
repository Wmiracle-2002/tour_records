import pytest

from app.agent.information import (
    MAX_INFO_ATTEMPTS,
    all_information_terminal,
    has_critical_failure,
    initialize_information_status,
    update_information_status,
)
from app.agent.models import InfoRequirement, InformationStatus, TravelRequirement


def test_initialize_status_for_each_direct_query() -> None:
    cases = [
        ("weather_query", "weather"),
        ("history_query", "history"),
        ("budget_query", "budget"),
        ("poi_recommendation", "pois"),
    ]

    for intent, field in cases:
        status = initialize_information_status(TravelRequirement(intent=intent))

        requirement = getattr(status, field)
        assert requirement == InfoRequirement(status="pending", critical=True)
        assert sum(value is not None for value in status.model_dump().values()) == 1

    route_status = initialize_information_status(TravelRequirement(intent="route_query"))
    assert all(value is None for value in route_status.model_dump().values())


def test_initialize_trip_planning_adds_explicit_budget_and_history_needs() -> None:
    status = initialize_information_status(
        TravelRequirement(
            intent="trip_planning",
            budget=3000,
            constraints=["不要安排以前去过的景点"],
        )
    )

    assert status.pois == InfoRequirement(status="pending", critical=True)
    assert status.budget == InfoRequirement(status="pending", critical=True)
    assert status.history == InfoRequirement(status="pending", critical=True)
    assert status.weather is None
    assert status.routes is None


def test_general_query_has_no_required_information() -> None:
    status = initialize_information_status(TravelRequirement(intent="general_query"))

    assert status == InformationStatus()
    assert all_information_terminal(status)


def test_empty_result_retries_until_unavailable() -> None:
    status = InformationStatus(weather=InfoRequirement(critical=True))

    status = update_information_status(status, "weather", outcome="empty", reason="no data")
    assert status.weather.status == "pending"
    assert status.weather.attempts == 1

    status = update_information_status(status, "weather", outcome="empty", reason="still empty")
    assert status.weather.status == "pending"
    assert status.weather.attempts == 2

    status = update_information_status(status, "weather", outcome="empty", reason="provider returned no data")
    assert status.weather.status == "unavailable"
    assert status.weather.attempts == MAX_INFO_ATTEMPTS
    assert status.weather.reason == "provider returned no data"


def test_error_retries_until_failed() -> None:
    status = InformationStatus(routes=InfoRequirement())

    for _ in range(MAX_INFO_ATTEMPTS - 1):
        status = update_information_status(status, "routes", outcome="error", reason="timeout")
        assert status.routes.status == "pending"

    status = update_information_status(status, "routes", outcome="error", reason="connection failed")
    assert status.routes.status == "failed"
    assert status.routes.attempts == MAX_INFO_ATTEMPTS


def test_success_completes_before_retry_limit_and_does_not_mutate_input() -> None:
    original = InformationStatus(weather=InfoRequirement(attempts=2, critical=True))

    updated = update_information_status(original, "weather", outcome="completed")

    assert original.weather.status == "pending"
    assert original.weather.attempts == 2
    assert updated.weather.status == "completed"
    assert updated.weather.attempts == 2


def test_terminal_status_cannot_be_retried_or_revived() -> None:
    status = InformationStatus(weather=InfoRequirement(status="unavailable", attempts=3))

    updated = update_information_status(status, "weather", outcome="completed")

    assert updated == status


def test_critical_failure_is_distinguished_from_optional_failure() -> None:
    status = InformationStatus(
        history=InfoRequirement(status="failed", critical=True, attempts=3),
        weather=InfoRequirement(status="unavailable", critical=False, attempts=3),
    )

    assert has_critical_failure(status)
    assert all_information_terminal(status)

    status.history.critical = False
    assert not has_critical_failure(status)


def test_pending_requirement_means_information_is_not_terminal() -> None:
    status = InformationStatus(budget=InfoRequirement())

    assert not all_information_terminal(status)


def test_missing_need_and_invalid_outcome_are_rejected() -> None:
    status = InformationStatus()

    with pytest.raises(ValueError, match="not configured"):
        update_information_status(status, "weather", outcome="completed")
    with pytest.raises(ValueError, match="outcome"):
        update_information_status(
            InformationStatus(weather=InfoRequirement()),
            "weather",
            outcome="unknown",  # type: ignore[arg-type]
        )
