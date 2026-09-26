"""Shared pure helpers used by multiple Agent modules."""

from __future__ import annotations

import re


_PREVIOUS_PLACE_KEYWORDS = ("以前", "之前", "曾经", "去过", "visited", "previous")


def avoids_previous_places(constraints: list[str]) -> bool:
    """Return whether constraints ask to avoid places visited before."""
    normalized = " ".join(constraints).lower()
    return any(keyword in normalized for keyword in _PREVIOUS_PLACE_KEYWORDS)


def is_food_category(category: str | None) -> bool:
    normalized = (category or "").lower()
    return any(word in normalized for word in ("餐饮", "美食", "food"))


def time_to_minutes(value: str) -> int:
    """Convert an exact HH:MM value to minutes after midnight."""
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"invalid date or time format: {value}")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"invalid date or time format: {value}")
    return hour * 60 + minute
