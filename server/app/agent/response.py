"""Generate user-facing responses from verified structured Agent state."""

from __future__ import annotations

from app.agent.models import (
    CollectedInfo,
    InformationStatus,
    Itinerary,
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


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


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
                collected_info,
                information_status,
                itinerary,
                validation,
            )
        if requirement.intent == "weather_query":
            return self._weather(collected_info, information_status)
        if requirement.intent == "history_query":
            return self._history(collected_info, information_status)
        if requirement.intent == "budget_query":
            return self._budget(collected_info, information_status)
        if requirement.intent == "poi_recommendation":
            return self._pois(collected_info, information_status)
        if requirement.intent == "route_query":
            return self._routes(collected_info, information_status)
        return "当前支持天气、路线、历史记录、预算和景点推荐等通用旅行问答。"

    def _trip_planning(
        self,
        collected_info: CollectedInfo,
        information_status: InformationStatus,
        itinerary: Itinerary | None,
        validation: ValidationResult | None,
    ) -> str:
        if itinerary is None:
            return "当前还没有可展示的完整行程。"

        poi_names = {
            item.poi_id: item.poi_name
            for day in itinerary.days
            for item in day.items
        }
        lines = ["行程安排："]
        for day_number, day in enumerate(itinerary.days, start=1):
            lines.append(f"第{day_number}天（{day.date}）：")
            if not day.items:
                lines.append("- 暂无安排。")
                continue
            for item in day.items:
                line = (
                    f"- {item.start_time}-{item.end_time}：{item.poi_name}"
                    f"（{item.activity_type}）"
                )
                if item.estimated_cost is not None:
                    line += f"，预计花费 {_number_text(item.estimated_cost)} 元"
                lines.append(line)

        route_lines = self._trip_route_lines(itinerary, collected_info)
        if route_lines:
            lines.append("路线参考：")
            lines.extend(route_lines)

        self._append_trip_weather(lines, collected_info, information_status)
        self._append_trip_budget(lines, collected_info, information_status)
        self._append_trip_history_notice(lines, collected_info, information_status)
        self._append_validation_notes(lines, itinerary, validation)
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
            f"{_number_text(budget.estimated_max)} 元。"
        )
        if budget.breakdown:
            details = "、".join(
                f"{name} {_number_text(amount)} 元"
                for name, amount in budget.breakdown.items()
            )
            line += f"费用明细：{details}。"
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
            lines.append("校验说明：行程已通过可确定规则检查。")
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
        collected_info: CollectedInfo,
        information_status: InformationStatus,
    ) -> str:
        notice = _status_notice(information_status, "history", "历史记录信息")
        if notice:
            return notice
        history = collected_info.history
        if history is None:
            return "历史记录当前没有可展示的数据。"

        parts = [f"历史记录：共记录 {history.trip_count} 次旅行。"]
        if history.visited_cities:
            parts.append(f"去过的城市：{'、'.join(history.visited_cities)}。")
        if history.visited_names:
            parts.append(f"去过的地点：{'、'.join(history.visited_names)}。")
        return "".join(parts)

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
            details = "、".join(
                f"{name} {_number_text(amount)} 元"
                for name, amount in budget.breakdown.items()
            )
            response += f"费用明细：{details}。"
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
