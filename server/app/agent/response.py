"""Generate user-facing responses from verified structured Agent state."""

from __future__ import annotations

from app.agent.utils import dietary_notice, is_food_category, note_supports_food, stale_note

from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
    ItineraryDay,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
)


_ROUTE_MODE_LABELS = {
    "walking": "步行",
    "driving": "驾车",
    "transit": "公共交通",
    "cycling": "骑行",
}

_PERIOD_LABELS = {
    "breakfast": "早餐", "morning": "上午", "lunch": "午餐",
    "afternoon": "下午", "dinner": "晚餐", "evening": "晚上",
}

_BUDGET_LABELS = {
    "accommodation": "住宿", "food": "餐饮", "transport": "交通",
    "poi_tickets": "景点门票",
}


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def _budget_details(breakdown: dict[str, float]) -> str:
    return "、".join(
        "景点门票未计入" if name == "poi_tickets" and amount == 0 else
        f"{_BUDGET_LABELS.get(name, name)} {_number_text(amount)} 元"
        for name, amount in breakdown.items()
    )


def _status_notice(
    status: InformationStatus,
    name: str,
    label: str,
) -> str | None:
    requirement = getattr(status, name)
    if requirement is None:
        return None
    if requirement.status == "unavailable":
        reason = requirement.reason or "数据源没有返回结果"
        return f"{label}暂不可用。原因：{reason}。"
    if requirement.status == "failed":
        reason = requirement.reason or "数据源调用失败"
        return f"{label}查询失败。原因：{reason}。"
    if requirement.status == "pending":
        return f"{label}仍在收集，暂时无法给出完整结果。"
    return None


def format_itinerary_day(day: ItineraryDay, day_number: int) -> list[str]:
    heading = f"第{day_number}天"
    if day.date:
        heading += f"（{day.date}）"
    lines = [f"{heading}："]
    if day.day_number is not None:
        by_period = {item.period: item for item in day.items if item.period}
        for period, label in _PERIOD_LABELS.items():
            item = by_period.get(period)
            lines.append(f"- {label}：{item.poi_name if item else '暂无可靠推荐'}")
        return lines
    if not day.items:
        return lines + ["- 暂无安排。"]
    for item in day.items:
        line = (
            f"- {item.start_time}-{item.end_time}：{item.poi_name}"
            f"（{item.activity_type}）"
        )
        if item.estimated_cost is not None:
            line += f"，预计花费 {_number_text(item.estimated_cost)} 元"
        lines.append(line)
    return lines


class FinalResponseGenerator:
    """把 State 中已有事实转换为不补充外部事实的用户回答。"""

    def generate(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
        itinerary: Itinerary | None = None,
        validation: ValidationResult | None = None,
    ) -> str:
        if requirement.intent == "trip_planning":
            return self._trip_planning(
                requirement,
                collected_info,
                information_status,
                itinerary,
                validation,
            )
        if requirement.intent == "weather_query":
            return self._weather(collected_info, information_status)
        if requirement.intent == "history_query":
            return self._history(requirement, collected_info, information_status)
        if requirement.intent == "budget_query":
            return self._budget(collected_info, information_status)
        if requirement.intent == "poi_recommendation":
            return self._pois(collected_info, information_status)
        if requirement.intent == "route_query":
            if information_status.routes is None:
                return "当前不提供具体路线导航；可以询问两个地点相距多远。"
            return self._routes(collected_info, information_status)
        if requirement.intent == "distance_query":
            return "距离查询正在完善，请稍后再试。"
        return "当前支持天气、路线、历史记录、预算和景点推荐等通用旅行问答。"

    def _trip_planning(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
        itinerary: Itinerary | None,
        validation: ValidationResult | None,
    ) -> str:
        if itinerary is None:
            return "当前还没有可展示的完整行程。"

        lines = ["行程安排："]
        for day_number, day in enumerate(itinerary.days, start=1):
            lines.extend(format_itinerary_day(day, day_number))

        coarse = any(day.day_number is not None for day in itinerary.days)
        route_lines = [] if coarse else self._trip_route_lines(itinerary, collected_info)
        if route_lines:
            lines.append("路线参考：")
            lines.extend(route_lines)

        self._append_trip_weather(lines, collected_info, information_status)
        self._append_trip_budget(lines, collected_info, information_status)
        self._append_trip_history_notice(lines, collected_info, information_status)
        self._append_validation_notes(lines, itinerary, validation)
        selected_names = {
            item.poi_name for day in itinerary.days for item in day.items
            if len(item.poi_name) >= 2
        }
        food_names = {poi.name for poi in collected_info.pois if is_food_category(poi.category)}
        cited = [
            note for note in collected_info.knowledge
            if not stale_note(note) and any(
                note_supports_food(note, name) if name in food_names
                else name in (note.title + note.excerpt)
                for name in selected_names
            )
        ]
        if cited:
            lines.append("参考收藏：" + "、".join(
                f"[收藏#{note.id}] {note.title}" for note in cited
            ) + "（餐食与兴趣参考，店铺仍以本轮地点查询为准）。")
        outdated = [note for note in collected_info.knowledge if stale_note(note)]
        if outdated:
            for note in outdated:
                lines.append(f"旧笔记原文（过时，非当前事实）：[收藏#{note.id}] {note.title}：\n“{note.excerpt}”")
            lines.append("过时笔记说明：" + "、".join(
                f"[收藏#{note.id}] {note.title}" for note in outdated
            ) + "已标明过时，不作为当前事实依据；本轮未核实其中的当前门票、价格和开放时间。")
        notice = dietary_notice(requirement)
        if notice:
            lines.append(notice)
        if coarse:
            lines.append("开放时间和实际费用请在出行前核实。")
        return "\n".join(lines)

    def _trip_route_lines(
        self,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> list[str]:
        routes = {
            (route.origin_id, route.destination_id): route
            for route in collected_info.routes
        }
        lines: list[str] = []
        for day in itinerary.days:
            for left, right in zip(day.items, day.items[1:]):
                route = routes.get((left.poi_id, right.poi_id))
                if route is None:
                    continue
                mode = _ROUTE_MODE_LABELS.get(route.mode, route.mode)
                lines.append(
                    f"- {left.poi_name} 到 {right.poi_name}：{mode}，"
                    f"约 {_number_text(route.distance_meters / 1000)} 公里，"
                    f"预计 {route.duration_minutes} 分钟。"
                )
        return lines

    def _append_trip_weather(
        self,
        lines: list[str],
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> None:
        weather = collected_info.weather
        requirement = information_status.weather
        if weather is not None:
            details = [f"{weather.location}，日期：{weather.date}"]
            if weather.description:
                details.append(f"天气：{weather.description}")
            if weather.temperature_min is not None and weather.temperature_max is not None:
                details.append(
                    f"温度：{_number_text(weather.temperature_min)}℃至"
                    f"{_number_text(weather.temperature_max)}℃"
                )
            lines.append(f"天气参考：{'，'.join(details)}。")
        elif requirement is not None:
            lines.append("天气参考：未获取到可用天气信息，未将天气因素纳入安排。")

    def _append_trip_budget(
        self,
        lines: list[str],
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> None:
        budget = collected_info.budget
        requirement = information_status.budget
        if budget is None:
            if requirement is not None:
                lines.append("预算参考：暂未获取到可用预算信息。")
            return

        line = (
            "预算参考（人民币）：约 "
            f"{_number_text(budget.estimated_min)} 元至 "
            f"{_number_text(budget.estimated_max)} 元（非实时粗估）。"
        )
        if budget.breakdown:
            line += f"费用明细：{_budget_details(budget.breakdown)}。"
        lines.append(line)

    def _append_trip_history_notice(
        self,
        lines: list[str],
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> None:
        requirement = information_status.history
        if requirement is None:
            return
        if collected_info.history is None:
            lines.append("历史记录：未找到可用历史记录，本次行程未完成去重。")

    def _append_validation_notes(
        self,
        lines: list[str],
        itinerary: Itinerary,
        validation: ValidationResult | None,
    ) -> None:
        if validation is None:
            lines.append("校验说明：行程尚未完成完整校验。")
            return

        name_by_id = {
            item.poi_id: item.poi_name
            for day in itinerary.days
            for item in day.items
        }
        unknowns = [issue for issue in validation.issues if issue.status == "unknown"]
        failures = [issue for issue in validation.issues if issue.status == "fail"]
        if not failures:
            incomplete = any(
                day.day_number is not None
                and set(_PERIOD_LABELS) - {item.period for item in day.items}
                for day in itinerary.days
            )
            lines.append(
                "校验说明：已安排地点通过规则检查，空白时段尚无可靠推荐。"
                if incomplete else "校验说明：行程已通过可确定规则检查。"
            )
        if unknowns:
            lines.append("未完成验证：")
            lines.extend(
                f"- {self._validation_issue_text(issue, name_by_id)}"
                for issue in unknowns
            )
        if failures:
            lines.append("行程尚未完全通过校验：")
            lines.extend(
                f"- {self._validation_issue_text(issue, name_by_id)}"
                for issue in failures
            )

    @staticmethod
    def _validation_issue_text(
        issue: ValidationIssue,
        name_by_id: dict[str, str],
    ) -> str:
        day_prefix = f"第{issue.day}天：" if issue.day is not None else ""
        if issue.type == "opening_hours":
            names = "、".join(
                name_by_id[poi_id]
                for poi_id in issue.related_poi_ids
                if poi_id in name_by_id
            ) or "相关景点"
            action = issue.suggested_action or "出发前确认景点当天的开放安排。"
            return f"{day_prefix}未获取到{names}可靠的开放时间，建议{action}"

        result = f"{day_prefix}{issue.message}"
        if issue.suggested_action:
            result += f"建议{issue.suggested_action}"
        return result

    def _weather(
        self,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "weather", "天气信息")
        if notice:
            return notice
        weather = collected_info.weather
        if weather is None:
            return "天气信息当前没有可展示的数据。"

        parts = [f"天气查询结果：{weather.location}，日期：{weather.date}。"]
        if weather.description:
            parts.append(f"天气：{weather.description}。")
        if weather.temperature_min is not None and weather.temperature_max is not None:
            parts.append(
                f"温度：{_number_text(weather.temperature_min)}℃至"
                f"{_number_text(weather.temperature_max)}℃。"
            )
        elif weather.temperature_min is not None:
            parts.append(f"最低温度：{_number_text(weather.temperature_min)}℃。")
        elif weather.temperature_max is not None:
            parts.append(f"最高温度：{_number_text(weather.temperature_max)}℃。")
        return "".join(parts)

    def _history(
        self,
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "history", "历史记录信息")
        if notice:
            return notice
        history = collected_info.history
        if history is None:
            return "历史记录当前没有可展示的数据。"

        destination = (requirement.city or "").strip()
        if destination:
            matched_city = any(
                destination in city or city in destination
                for city in history.visited_cities
            )
            if not matched_city:
                return f"没有找到在{destination}的历史旅行记录。"

        cities = [
            city for city in history.visited_cities
            if not destination or destination in city or city in destination
        ]
        if not cities:
            return "没有找到历史旅行记录。"
        if requirement.history_view == "trips":
            lines = []
            for city in cities:
                periods = history.trip_periods_by_city.get(city, [])
                if not periods:
                    lines.append(f"{city}：暂无可核实的出行次数和日期区间")
                    continue
                dates = "、".join(
                    f"{start or '日期未知'} 至 {end or '日期未知'}"
                    for start, end in periods
                )
                lines.append(f"{city}：共{len(periods)}次，日期区间：{dates}")
            return "；\n".join(lines) + "。"
        if requirement.history_view == "ratings":
            lines = []
            for city in cities:
                for name, ratings in history.ratings_by_city.get(city, {}).items():
                    if requirement.history_record_name is not None and name != requirement.history_record_name:
                        continue
                    if not ratings:
                        continue
                    values = "、".join(
                        "未评分" if rating is None else f"{_number_text(rating)}分"
                        for rating in ratings
                    )
                    lines.append(f"{city}，{name}：{values}")
            return "；\n".join(lines) + "。" if lines else "没有找到符合条件的历史评分记录。"
        if requirement.history_category is None:
            return f"去过的城市：{'、'.join(cities)}。"
        label = "吃过的美食" if requirement.history_category == "FOOD" else "去过的地点"
        lines = []
        for index, city in enumerate(cities, start=1):
            if requirement.history_category == "BOTH":
                categories = history.records_by_city.get(city, {})
                places = "、".join(categories.get("ATTRACTION", [])) or "暂无相关记录"
                foods = "、".join(categories.get("FOOD", [])) or "暂无相关记录"
                lines.append(f"去过的城市{index}：{city}，去过的地点：{places}，吃过的美食：{foods}")
                continue
            names = history.records_by_city.get(city, {}).get(requirement.history_category, [])
            value = "、".join(names) or "暂无相关记录"
            lines.append(f"去过的城市{index}：{city}，{label}：{value}")
        return "；\n".join(lines) + "。"

    def _budget(
        self,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "budget", "预算信息")
        if notice:
            return notice
        budget = collected_info.budget
        if budget is None:
            return "预算信息当前没有可展示的数据。"

        response = (
            "预算估算（人民币）：约 "
            f"{_number_text(budget.estimated_min)} 元至 "
            f"{_number_text(budget.estimated_max)} 元。"
        )
        if budget.breakdown:
            response += f"费用明细：{_budget_details(budget.breakdown)}。"
        if budget.assumptions:
            response += f"估算依据：{'；'.join(budget.assumptions)}。"
        return response

    def _pois(
        self,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "pois", "地点信息")
        if notice:
            return notice
        if not collected_info.pois:
            return "地点信息当前没有可展示的数据。"

        lines = ["地点推荐："]
        for index, poi in enumerate(collected_info.pois, start=1):
            details = []
            if poi.category:
                details.append(poi.category)
            if poi.address:
                details.append(poi.address)
            suffix = f"（{'，'.join(details)}）" if details else ""
            lines.append(f"{index}. {poi.name}{suffix}")
        return "\n".join(lines)

    def _routes(
        self,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "routes", "路线信息")
        if notice:
            return notice

        lines = ["路线查询结果："]
        for route in collected_info.routes:
            mode = _ROUTE_MODE_LABELS.get(route.mode, route.mode)
            lines.append(
                f"{route.origin_id} 到 {route.destination_id}：{mode}，"
                f"约 {route.distance_meters / 1000:.1f} 公里，"
                f"预计 {route.duration_minutes} 分钟。"
            )
        for distance in collected_info.distances:
            lines.append(
                f"{distance.origin_id} 到 {distance.destination_id}："
                f"距离约 {distance.distance_meters / 1000:.1f} 公里。"
            )
        if len(lines) == 1:
            return "路线信息当前没有可展示的数据。"
        return "\n".join(lines)
