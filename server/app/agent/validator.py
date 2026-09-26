"""Deterministic validation rules for generated itineraries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.models import (
    CollectedInfo,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    RouteInfo,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
)
from app.agent.utils import avoids_previous_places, is_food_category, time_to_minutes


@dataclass(frozen=True)
class ValidatorConfig:
    """Validator thresholds kept in one place for later adjustment."""

    max_daily_minutes: int = 12 * 60

    def __post_init__(self) -> None:
        if self.max_daily_minutes <= 0:
            raise ValueError("max_daily_minutes must be positive")


class ItineraryValidator:
    """Run deterministic rules without asking an LLM to judge the itinerary."""

    def __init__(self, *, config: ValidatorConfig | None = None) -> None:
        self._config = config or ValidatorConfig()

    def validate(
        self,
        requirement: TravelRequirement,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        issues.extend(self._coarse_integrity_issues(itinerary, collected_info))
        issues.extend(self._time_conflict_issues(itinerary))
        issues.extend(self._travel_time_issues(itinerary, collected_info))
        issues.extend(self._opening_hours_issues(itinerary, collected_info))
        issues.extend(self._constraint_issues(requirement, itinerary, collected_info))
        issues.extend(self._budget_issues(requirement, collected_info))
        issues.extend(self._daily_load_issues(itinerary))
        return ValidationResult(
            valid=not any(issue.status == "fail" for issue in issues),
            issues=issues,
        )

    def _coarse_integrity_issues(
        self, itinerary: Itinerary, collected_info: CollectedInfo,
    ) -> list[ValidationIssue]:
        known_pois = {poi.poi_id: poi for poi in collected_info.pois}
        issues: list[ValidationIssue] = []
        for day_number, day in enumerate(itinerary.days, start=1):
            seen_pois: set[str] = set()
            seen_periods: set[str] = set()
            for item in day.items:
                if item.period is None:
                    continue
                poi = known_pois.get(item.poi_id)
                food_period = item.period in {"breakfast", "lunch", "dinner"}
                if (
                    item.poi_id in seen_pois
                    or item.period in seen_periods
                    or poi is None
                    or poi.name != item.poi_name
                    or not poi.category
                    or is_food_category(poi.category) != food_period
                    or item.activity_type != ("FOOD" if food_period else "ATTRACTION")
                ):
                    issues.append(_issue(
                        "constraint", "fail", day_number, [item.poi_id],
                        f"第{day_number}天 {item.poi_name} 的候选类别、时段或去重校验失败。",
                        "仅使用已验证且不重复的景点或餐饮候选。",
                    ))
                seen_pois.add(item.poi_id)
                seen_periods.add(item.period)
        return issues

    def _time_conflict_issues(self, itinerary: Itinerary) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for day_number, day in enumerate(itinerary.days, start=1):
            for index, left in enumerate(day.items):
                if left.start_time is None:
                    continue
                left_start = time_to_minutes(left.start_time)
                left_end = time_to_minutes(left.end_time)
                for right in day.items[index + 1 :]:
                    if right.start_time is None:
                        continue
                    right_start = time_to_minutes(right.start_time)
                    right_end = time_to_minutes(right.end_time)
                    if left_start < right_end and right_start < left_end:
                        issues.append(
                            _issue(
                                "time_conflict",
                                "fail",
                                day_number,
                                [left.poi_id, right.poi_id],
                                f"第{day_number}天 {left.poi_name} 与 {right.poi_name} 的时间重叠。",
                                "调整活动时间或顺序。",
                            )
                        )
        return issues

    def _travel_time_issues(
        self,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for day_number, day in enumerate(itinerary.days, start=1):
            for previous, current in zip(day.items, day.items[1:]):
                if previous.end_time is None or current.start_time is None:
                    continue
                if previous.poi_id == current.poi_id:
                    continue
                duration = _route_duration(
                    collected_info.routes,
                    previous.poi_id,
                    current.poi_id,
                )
                related_ids = [previous.poi_id, current.poi_id]
                if duration is None:
                    issues.append(
                        _issue(
                            "travel_time",
                            "unknown",
                            day_number,
                            related_ids,
                            f"没有 {previous.poi_name} 到 {current.poi_name} 的可靠路线时间。",
                            "补充路线信息后再校验移动时间。",
                        )
                    )
                    continue
                earliest_start = time_to_minutes(previous.end_time) + duration
                current_start = time_to_minutes(current.start_time)
                if earliest_start > current_start:
                    issues.append(
                        _issue(
                            "travel_time",
                            "fail",
                            day_number,
                            related_ids,
                            f"从 {previous.poi_name} 到 {current.poi_name} 的移动时间不足。",
                            "延后下一项活动或调整地点顺序。",
                        )
                    )
        return issues

    def _opening_hours_issues(
        self,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> list[ValidationIssue]:
        pois = {poi.poi_id: poi for poi in collected_info.pois}
        issues: list[ValidationIssue] = []
        for day_number, day in enumerate(itinerary.days, start=1):
            for item in day.items:
                if item.start_time is None:
                    continue
                poi = pois.get(item.poi_id)
                if poi is None or poi.opening_hours is None:
                    issues.append(
                        _issue(
                            "opening_hours",
                            "unknown",
                            day_number,
                            [item.poi_id],
                            f"暂时没有 {item.poi_name} 的可靠开放时间。",
                            "出发前确认当天开放安排。",
                        )
                    )
                    continue

                windows = _parse_opening_hours(poi.opening_hours)
                if windows is None:
                    issues.append(
                        _issue(
                            "opening_hours",
                            "unknown",
                            day_number,
                            [item.poi_id],
                            f"无法解析 {item.poi_name} 的开放时间。",
                            "出发前确认当天开放安排。",
                        )
                    )
                    continue

                start = time_to_minutes(item.start_time)
                end = time_to_minutes(item.end_time)
                if not any(open_time <= start and end <= close_time for open_time, close_time in windows):
                    issues.append(
                        _issue(
                            "opening_hours",
                            "fail",
                            day_number,
                            [item.poi_id],
                            f"{item.poi_name} 的安排时间超出开放时间。",
                            "调整活动时间。",
                        )
                    )
        return issues

    def _constraint_issues(
        self,
        requirement: TravelRequirement,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> list[ValidationIssue]:
        if not avoids_previous_places(requirement.constraints):
            return []

        planned_ids = _unique_poi_ids(itinerary)
        history = collected_info.history
        if history is None:
            return [
                _issue(
                    "constraint",
                    "unknown",
                    None,
                    planned_ids,
                    "没有历史记录，无法校验是否安排了以前去过的地点。",
                    "补充历史记录后再检查去重约束。",
                )
            ]

        duplicated_ids = [
            poi_id for poi_id in planned_ids if poi_id in set(history.visited_poi_ids)
        ]
        if not duplicated_ids:
            return []
        return [
            _issue(
                "constraint",
                "fail",
                None,
                duplicated_ids,
                "行程包含用户以前去过的地点。",
                "替换这些地点或移除去重约束。",
            )
        ]

    def _budget_issues(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> list[ValidationIssue]:
        if requirement.budget is None:
            return []
        if collected_info.budget is None:
            return [
                _issue(
                    "budget",
                    "unknown",
                    None,
                    [],
                    "没有预算估算，无法校验预算约束。",
                    "补充预算估算后再检查。",
                )
            ]
        if collected_info.budget.estimated_max <= requirement.budget:
            return []
        return [
            _issue(
                "budget",
                "fail",
                None,
                [],
                f"预算估算上限 {collected_info.budget.estimated_max:g} 元超过用户预算 {requirement.budget:g} 元。",
                "减少活动、住宿或交通费用。",
            )
        ]

    def _daily_load_issues(self, itinerary: Itinerary) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for day_number, day in enumerate(itinerary.days, start=1):
            total_minutes = sum(
                time_to_minutes(item.end_time) - time_to_minutes(item.start_time)
                for item in day.items if item.start_time is not None
            )
            if total_minutes > self._config.max_daily_minutes:
                issues.append(
                    _issue(
                        "daily_load",
                        "fail",
                        day_number,
                        [item.poi_id for item in day.items],
                        f"第{day_number}天安排 {total_minutes} 分钟，超过每日上限 {self._config.max_daily_minutes} 分钟。",
                        "减少当天活动或拆分到其他日期。",
                    )
                )
        return issues


def _issue(
    issue_type: str,
    status: str,
    day: int | None,
    related_poi_ids: list[str],
    message: str,
    suggested_action: str,
) -> ValidationIssue:
    return ValidationIssue(
        type=issue_type,
        status=status,
        day=day,
        related_poi_ids=related_poi_ids,
        message=message,
        suggested_action=suggested_action,
    )


def _route_duration(
    routes: list[RouteInfo],
    origin_id: str,
    destination_id: str,
) -> int | None:
    durations = [
        route.duration_minutes
        for route in routes
        if route.origin_id == origin_id and route.destination_id == destination_id
    ]
    return min(durations) if durations else None


def _parse_opening_hours(value: str) -> list[tuple[int, int]] | None:
    normalized = value.strip().lower().replace(" ", "")
    if normalized in {"全天", "24小时", "24h"}:
        return [(0, 24 * 60)]

    parts = re.split(r"[,，;；、/]+", normalized)
    windows: list[tuple[int, int]] = []
    for part in parts:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})[-~至](\d{1,2}):(\d{2})", part)
        if match is None:
            return None
        open_hour, open_minute, close_hour, close_minute = (
            int(value) for value in match.groups()
        )
        if open_hour > 23 or close_hour > 24 or open_minute > 59 or close_minute > 59:
            return None
        open_time = open_hour * 60 + open_minute
        close_time = close_hour * 60 + close_minute
        if close_time <= open_time:
            return None
        windows.append((open_time, close_time))
    return windows or None


def _unique_poi_ids(itinerary: Itinerary) -> list[str]:
    result: list[str] = []
    for day in itinerary.days:
        for item in day.items:
            if item.poi_id not in result:
                result.append(item.poi_id)
    return result
