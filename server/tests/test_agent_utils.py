import pytest

from app.agent.utils import avoids_previous_places, time_to_minutes


@pytest.mark.parametrize(
    "constraints",
    [
        ["不要去以前去过的景点"],
        ["避免之前访问过的地点"],
        ["previous places should be excluded"],
        ["Do not use visited POIs"],
    ],
)
def test_avoids_previous_places_recognizes_supported_phrases(
    constraints: list[str],
) -> None:
    assert avoids_previous_places(constraints) is True


@pytest.mark.parametrize(
    "constraints",
    [[], ["历史文化"], ["每天安排不要太满"]],
)
def test_avoids_previous_places_ignores_unrelated_constraints(
    constraints: list[str],
) -> None:
    assert avoids_previous_places(constraints) is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [("00:00", 0), ("09:30", 570), ("23:59", 1439)],
)
def test_time_to_minutes_accepts_valid_hhmm_values(value: str, expected: int) -> None:
    assert time_to_minutes(value) == expected


@pytest.mark.parametrize("value", ["9:00", "24:00", "12:60", "noon"])
def test_time_to_minutes_rejects_invalid_hhmm_values(value: str) -> None:
    with pytest.raises(ValueError, match="date or time"):
        time_to_minutes(value)
