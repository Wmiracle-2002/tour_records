"""Structured itinerary generation boundary."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.agent.models import CollectedInfo, Itinerary, TravelRequirement
from app.agent.utils import avoids_previous_places, time_to_minutes


MAX_ITINERARY_GENERATION_ATTEMPTS = 2


ITINERARY_GENERATOR_SYSTEM_PROMPT = """
你是旅行 Agent 的结构化行程生成器。

输入是 TravelRequirement 和 CollectedInfo。请根据已有候选地点、路线、距离、预算、偏好和硬约束生成 Itinerary。

输出 JSON 必须严格使用以下结构：根对象只能包含 days，days 是数组；每个 day 只能包含 date 和 items；每个 item 只能包含 poi_id、poi_name、start_time、end_time、activity_type、estimated_cost。不要使用 itinerary 字段包裹，不要改名或增加外层字段。

规则：
- 只能使用 CollectedInfo 中已有的事实，不要虚构地点、地址、开放时间、价格、距离或路线时间；
- 每个行程项必须使用候选 POI 的 poi_id，并填写对应的 poi_name；
- 如果 TravelRequirement.duration_days 有值，days 必须恰好包含 duration_days 天，不得省略、合并或追加；
- 遵守用户的 preferences 和 constraints；
- date 只能使用 YYYY-MM-DD；如果用户使用“国庆”等非具体日期表达，不能把该词写入 date 字段，应转化为标准格式的日期；
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
            output = self._client.complete_structured(
                system_prompt=ITINERARY_GENERATOR_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                output_model=Itinerary,
            )
            try:
                itinerary = Itinerary.model_validate(output)
                self._validate_itinerary(itinerary, requirement, collected_info)
                return itinerary
            except ValueError as error:
                last_error = error
                if attempt == MAX_ITINERARY_GENERATION_ATTEMPTS - 1:
                    raise
        raise ValueError("Itinerary generation failed validation")

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
