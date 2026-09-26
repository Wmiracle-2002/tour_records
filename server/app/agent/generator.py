"""Structured itinerary generation boundary."""

from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.agent.budget import AgentBudget
from app.agent.models import CollectedInfo, Itinerary, ItineraryDay, ItineraryItem, TravelRequirement
from app.agent.utils import avoids_previous_places, is_food_category, time_to_minutes


MAX_ITINERARY_GENERATION_ATTEMPTS = 2


def fallback_itinerary(
    requirement: TravelRequirement, collected_info: CollectedInfo,
) -> Itinerary:
    """Build a sparse plan from verified candidates when generation fails."""
    visited = set(
        collected_info.history.visited_poi_ids if collected_info.history else []
    ) if avoids_previous_places(requirement.constraints) else set()
    attractions = []
    foods = []
    for poi in collected_info.pois:
        if poi.poi_id in visited:
            continue
        category = (poi.category or "").lower()
        if is_food_category(category):
            foods.append(poi)
        elif any(word in category for word in (
            "风景名胜", "景点", "历史文化", "博物馆", "公园", "attraction",
        )):
            attractions.append(poi)
    start = datetime.strptime(requirement.start_date, "%Y-%m-%d") if requirement.start_date else None
    days = []
    for index in range(requirement.duration_days or 1):
        items = []
        for period, pool, activity in (
            ("breakfast", foods, "FOOD"),
            ("morning", attractions, "ATTRACTION"),
            ("lunch", foods, "FOOD"),
            ("afternoon", attractions, "ATTRACTION"),
            ("dinner", foods, "FOOD"),
            ("evening", attractions, "ATTRACTION"),
        ):
            if pool:
                poi = pool.pop(0)
                items.append(ItineraryItem(
                    poi_id=poi.poi_id, poi_name=poi.name,
                    period=period, activity_type=activity,
                ))
        days.append(ItineraryDay(
            date=(start + timedelta(days=index)).date().isoformat() if start else None,
            day_number=index + 1,
            items=items,
        ))
    return Itinerary(days=days)


ITINERARY_GENERATOR_SYSTEM_PROMPT = """
你是旅行 Agent 的结构化行程生成器。

输入是 TravelRequirement 和 CollectedInfo。请根据已有候选地点、路线、距离、预算、偏好和硬约束生成 Itinerary。

输出 JSON 必须严格使用以下结构：根对象只能包含 days；每个 day 包含 day_number、date、items；每个 item 包含 poi_id、poi_name、period、activity_type。不要使用 itinerary 字段包裹，不要改名或增加外层字段。

规则：
- 只能使用 CollectedInfo 中已有的事实，不要虚构地点、地址、开放时间、价格、距离或路线时间；
- 每个行程项必须使用候选 POI 的 poi_id，并填写对应的 poi_name；
- 如果 TravelRequirement.duration_days 有值，days 必须恰好包含 duration_days 天，不得省略、合并或追加；
- 遵守用户的 preferences 和 constraints；
- day_number 从 1 连续编号；仅当 TravelRequirement.start_date 是具体 YYYY-MM-DD 日期时填写逐日 date，否则 date 为 null，不猜测日期；
- 景点用 morning/afternoon/evening 和 ATTRACTION，美食用 breakfast/lunch/dinner 和 FOOD；每个时段最多一个地点，同一天不得重复 POI；候选不足时省略对应时段，不编造地点；
- 不生成 HH:MM 精确时间、价格或导航路线；
- 只返回符合 Itinerary 的结构化数据，不要输出自然语言旅行攻略。
""".strip()


class StructuredItineraryClient(Protocol):
    """提供 Pydantic 结构化输出的行程生成客户端。"""

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Itinerary],
    ) -> Itinerary | dict[str, Any]:
        ...


class StructuredItineraryGenerator:
    """调用结构化输出客户端并校验行程与已收集事实的关联。"""

    def __init__(
        self,
        client: StructuredItineraryClient,
        budget: AgentBudget | None = None,
    ) -> None:
        self._client = client
        self._budget = budget

    def generate(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> Itinerary:
        base_prompt = self._build_user_prompt(requirement, collected_info)
        last_error: ValueError | None = None
        for attempt in range(MAX_ITINERARY_GENERATION_ATTEMPTS):
            user_prompt = base_prompt
            if attempt > 0 and last_error is not None:
                user_prompt += (
                    "\n\nThe previous itinerary failed validation: "
                    f"{last_error}. Regenerate the complete Itinerary JSON and "
                    "correct the validation problem."
                )
            with (
                self._budget.stage("itinerary_generator")
                if self._budget
                else nullcontext()
            ):
                output = self._client.complete_structured(
                    system_prompt=ITINERARY_GENERATOR_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    output_model=Itinerary,
                )
            try:
                itinerary = Itinerary.model_validate(output)
                self._validate_itinerary(itinerary, requirement, collected_info)
                itinerary = self._fill_missing_meals(itinerary, requirement, collected_info)
                self._validate_itinerary(itinerary, requirement, collected_info)
                return itinerary
            except ValueError as error:
                last_error = error
                if attempt == MAX_ITINERARY_GENERATION_ATTEMPTS - 1:
                    raise
        raise ValueError("Itinerary generation failed validation")

    @staticmethod
    def _fill_missing_meals(
        itinerary: Itinerary,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> Itinerary:
        if not all(day.day_number is not None for day in itinerary.days):
            return itinerary
        used_ids = {item.poi_id for day in itinerary.days for item in day.items}
        if avoids_previous_places(requirement.constraints) and collected_info.history:
            used_ids.update(collected_info.history.visited_poi_ids)
        foods = iter(
            poi for poi in collected_info.pois
            if is_food_category(poi.category) and poi.poi_id not in used_ids
        )
        result = itinerary.model_copy(deep=True)
        for day in result.days:
            periods = {item.period for item in day.items}
            for period in ("lunch", "dinner"):
                if period in periods:
                    continue
                poi = next(foods, None)
                if poi is None:
                    break
                day.items.append(ItineraryItem(
                    poi_id=poi.poi_id, poi_name=poi.name,
                    period=period, activity_type="FOOD",
                ))
        return result

    def _build_user_prompt(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> str:
        return (
            "TravelRequirement:\n"
            f"{requirement.model_dump_json(indent=2)}\n\n"
            "CollectedInfo:\n"
            f"{collected_info.model_dump_json(indent=2)}"
        )

    def _validate_itinerary(
        self,
        itinerary: Itinerary,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> None:
        if requirement.end_date and not requirement.start_date:
            raise ValueError("Itinerary start_date is required when end_date is given")
        if (
            requirement.duration_days is not None
            and len(itinerary.days) != requirement.duration_days
        ):
            raise ValueError(
                "Itinerary days do not match requirement duration_days"
            )

        if not itinerary.days:
            raise ValueError("Itinerary must contain at least one day")

        known_pois = {poi.poi_id: poi for poi in collected_info.pois}
        visited_poi_ids = set(
            collected_info.history.visited_poi_ids
            if collected_info.history is not None
            else []
        )
        should_avoid_previous_places = avoids_previous_places(requirement.constraints)

        planned_dates = []
        for day_number, day in enumerate(itinerary.days, start=1):
            if day.day_number is not None and day.day_number != day_number:
                raise ValueError("Itinerary day_number must be consecutive")
            if requirement.start_date:
                if day.date is None:
                    raise ValueError("Itinerary date is required when start_date is known")
                planned_dates.append(self._parse_date(day.date))
            elif day.date is not None:
                raise ValueError("Itinerary date is not allowed without start_date")
            elif day.day_number is None:
                raise ValueError("Itinerary day_number is required without start_date")
            used_periods: set[str] = set()
            used_pois: set[str] = set()
            for item in day.items:
                if item.period is None:
                    time_to_minutes(item.start_time)
                    time_to_minutes(item.end_time)
                poi = known_pois.get(item.poi_id)
                if poi is None:
                    raise ValueError(f"unknown poi_id: {item.poi_id}")
                if item.poi_name != poi.name:
                    raise ValueError(
                        f"poi_name does not match poi_id: {item.poi_id}"
                    )
                if should_avoid_previous_places and item.poi_id in visited_poi_ids:
                    raise ValueError(
                        f"itinerary contains previously visited poi_id: {item.poi_id}"
                    )
                if item.period is not None:
                    if item.period in used_periods or item.poi_id in used_pois:
                        raise ValueError("duplicate period or poi_id within a day")
                    used_periods.add(item.period)
                    used_pois.add(item.poi_id)
                    food = item.period in {"breakfast", "lunch", "dinner"}
                    category = (poi.category or "").lower()
                    poi_is_food = is_food_category(category)
                    if not category or poi_is_food != food or item.activity_type != (
                        "FOOD" if food else "ATTRACTION"
                    ):
                        raise ValueError(f"poi category does not match period: {item.poi_id}")

        if requirement.start_date:
            start_date = self._parse_date(requirement.start_date)
            if planned_dates[0] != start_date:
                raise ValueError("Itinerary does not start at requirement start_date")
        if requirement.end_date:
            end_date = self._parse_date(requirement.end_date)
            if planned_dates[-1] != end_date:
                raise ValueError("Itinerary does not end at requirement end_date")
        for previous, current in zip(planned_dates, planned_dates[1:]):
            if current - previous != timedelta(days=1):
                raise ValueError("Itinerary dates are not consecutive")

    @staticmethod
    def _parse_date(value: str) -> datetime:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"invalid date or time format: {value}")
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"invalid date or time format: {value}") from exc
