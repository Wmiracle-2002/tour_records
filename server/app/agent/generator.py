"""Structured itinerary generation boundary."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.agent.models import CollectedInfo, Itinerary, TravelRequirement
from app.agent.utils import avoids_previous_places, time_to_minutes


ITINERARY_GENERATOR_SYSTEM_PROMPT = """
你是旅行 Agent 的结构化行程生成器。

输入是 TravelRequirement 和 CollectedInfo。请根据已有候选地点、路线、距离、预算、偏好和硬约束生成 Itinerary。

规则：
- 只能使用 CollectedInfo 中已有的事实，不要虚构地点、地址、开放时间、价格、距离或路线时间；
- 每个行程项必须使用候选 POI 的 poi_id，并填写对应的 poi_name；
- 遵守用户的 preferences 和 constraints；
- 日期格式必须是 YYYY-MM-DD，时间格式必须是 HH:MM；
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

    def __init__(self, client: StructuredItineraryClient) -> None:
        self._client = client

    def generate(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> Itinerary:
        output = self._client.complete_structured(
            system_prompt=ITINERARY_GENERATOR_SYSTEM_PROMPT,
            user_prompt=self._build_user_prompt(requirement, collected_info),
            output_model=Itinerary,
        )
        itinerary = Itinerary.model_validate(output)
        self._validate_itinerary(itinerary, requirement, collected_info)
        return itinerary

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
        for day in itinerary.days:
            planned_date = self._parse_date(day.date)
            planned_dates.append(planned_date)
            for item in day.items:
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
