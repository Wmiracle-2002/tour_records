"""Information need initialization and lifecycle transitions for the Agent."""

from __future__ import annotations

from typing import Literal

from app.agent.models import InfoRequirement, InformationStatus, TravelRequirement
from app.agent.utils import avoids_previous_places


MAX_INFO_ATTEMPTS = 3
InformationNeedName = Literal[
    "history",
    "pois",
    "weather",
    "routes",
    "distances",
    "budget",
]
InformationOutcome = Literal["completed", "empty", "error", "unavailable"]
_TERMINAL_STATUSES = {"completed", "unavailable", "failed"}


def _add_need(
    status: InformationStatus,
    name: InformationNeedName,
    *,
    critical: bool,
) -> InformationStatus:
    current = getattr(status, name)
    if current is not None:
        return status
    updated = status.model_copy(deep=True)
    setattr(updated, name, InfoRequirement(critical=critical))
    return updated


def initialize_information_status(
    requirement: TravelRequirement,
) -> InformationStatus:
    """根据需求创建当前信息任务，不预先创建无关的信息项。"""
    status = InformationStatus()
    if requirement.intent == "weather_query":
        return _add_need(status, "weather", critical=True)
    if requirement.intent == "history_query":
        return _add_need(status, "history", critical=True)
    if requirement.intent == "budget_query":
        return _add_need(status, "budget", critical=True)
    if requirement.intent == "route_query":
        return status
    if requirement.intent == "poi_recommendation":
        return _add_need(status, "pois", critical=True)

    if requirement.intent == "trip_planning":
        status = _add_need(status, "pois", critical=True)
        if requirement.budget is not None:
            status = _add_need(status, "budget", critical=True)
        if avoids_previous_places(requirement.constraints):
            status = _add_need(status, "history", critical=True)
    return status


def ensure_information_need(
    status: InformationStatus,
    name: InformationNeedName,
    *,
    critical: bool = False,
) -> InformationStatus:
    """在后续 ReAct 决策需要新信息时加入一个 pending 任务。"""
    if name not in InformationStatus.model_fields:
        raise ValueError(f"Information need is not supported: {name}")
    current = getattr(status, name)
    if current is not None:
        if critical and not current.critical:
            updated = status.model_copy(deep=True)
            getattr(updated, name).critical = True
            return updated
        return status.model_copy(deep=True)
    return _add_need(status, name, critical=critical)


def update_information_status(
    status: InformationStatus,
    name: InformationNeedName,
    *,
    outcome: InformationOutcome,
    reason: str | None = None,
) -> InformationStatus:
    """更新一次信息获取结果，并在达到上限后终止重试。"""
    if name not in InformationStatus.model_fields:
        raise ValueError(f"Information need is not supported: {name}")
    if outcome not in {"completed", "empty", "error", "unavailable"}:
        raise ValueError(f"Unsupported information outcome: {outcome}")

    current = getattr(status, name)
    if current is None:
        raise ValueError(f"Information need is not configured: {name}")

    updated = status.model_copy(deep=True)
    current = getattr(updated, name)
    if current.status in _TERMINAL_STATUSES:
        return updated

    if outcome == "completed":
        current.status = "completed"
        current.reason = reason
        return updated

    if outcome == "unavailable":
        current.attempts += 1
        current.status = "unavailable"
        current.reason = reason
        return updated

    current.attempts += 1
    current.reason = reason
    if current.attempts < MAX_INFO_ATTEMPTS:
        return updated

    current.status = "unavailable" if outcome == "empty" else "failed"
    return updated


def all_information_terminal(status: InformationStatus) -> bool:
    """判断当前已登记的所有信息任务是否都进入终止状态。"""
    return all(
        requirement is None or requirement.status in _TERMINAL_STATUSES
        for name in InformationStatus.model_fields
        for requirement in (getattr(status, name),)
    )


def has_critical_failure(status: InformationStatus) -> bool:
    """判断是否有核心信息以 unavailable 或 failed 结束。"""
    return any(
        requirement is not None
        and requirement.critical
        and requirement.status in {"unavailable", "failed"}
        for requirement in (
            status.history,
            status.pois,
            status.weather,
            status.routes,
            status.distances,
            status.budget,
        )
    )
