"""Deterministic distance and weather answers using verified AMap responses."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Callable

from app.agent.models import TravelRequirement
from app.agent.tools.amap import AmapApiError, AmapWebClient
from app.agent.tools.budget import EstimateBudgetTool
from app.agent.tools.layer import ToolUnavailableError


def china_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


def _relative_weather_date(expression: str | None, today: date) -> date | None:
    if not expression:
        return None
    if "后天" in expression:
        return today + timedelta(days=2)
    if "明天" in expression:
        return today + timedelta(days=1)
    if "今天" in expression or "今晚" in expression:
        return today
    return None


def _straight_meters(left: str, right: str) -> float:
    left_lng, left_lat = (radians(float(value)) for value in left.split(","))
    right_lng, right_lat = (radians(float(value)) for value in right.split(","))
    arc = sin((right_lat - left_lat) / 2) ** 2 + (
        cos(left_lat) * cos(right_lat) * sin((right_lng - left_lng) / 2) ** 2
    )
    return 2 * 6371000 * asin(sqrt(arc))


class FactualAnswerer:
    """Choose fixed provider parameters after the requirement has been parsed."""

    def __init__(
        self,
        amap: AmapWebClient,
        *,
        today_provider: Callable[[], date] = china_today,
    ) -> None:
        self._amap = amap
        self._today_provider = today_provider

    def answer(self, requirement: TravelRequirement) -> str:
        try:
            if requirement.intent == "distance_query":
                return self._distance(requirement)
            if requirement.intent == "weather_query":
                return self._weather(requirement)
            if requirement.intent == "budget_query":
                return self._budget(requirement)
        except (AmapApiError, ToolUnavailableError, ValueError) as error:
            label = {
                "distance_query": "距离信息",
                "weather_query": "天气信息",
                "budget_query": "预算信息",
            }.get(requirement.intent, "信息")
            return f"{label}查询失败，原因：{error}。"
        raise ValueError("factual answerer only supports distance, weather and budget")

    def _budget(self, requirement: TravelRequirement) -> str:
        if requirement.duration_days is None:
            return "请说明旅行天数，才能估算预算。"
        travelers = requirement.travelers or 1
        estimate = EstimateBudgetTool().run(
            city=requirement.city,
            duration_days=requirement.duration_days,
            travelers=travelers,
        ).data
        if estimate is None:
            return "预算估算暂不可用。"
        answer = (
            f"人民币粗略估算：{travelers} 人、{requirement.duration_days} 天，"
            f"约 {estimate.estimated_min:g}～{estimate.estimated_max:g} 元。"
            "不含未提供的景点门票和城际交通，实际价格请核实。"
        )
        if requirement.budget is not None and estimate.estimated_max > requirement.budget:
            answer += f"估算上限超过你提出的 {requirement.budget:g} 元预算。"
        return answer

    def _distance(self, requirement: TravelRequirement) -> str:
        if not requirement.city:
            return "请先说明两个地点所在的城市，避免查到同名地点。"
        if not requirement.origin or not requirement.destination:
            return "请同时说明要测距的起点和终点。"
        locations = []
        for name in (requirement.origin, requirement.destination):
            pois = self._amap.search_verified_pois(
                city=requirement.city, kind="place", place_name=name
            )["pois"]
            if not pois:
                return f"没有找到{requirement.city}的“{name}”，请提供更具体的地点名称。"
            if len(pois) != 1:
                return f"{requirement.city}的“{name}”对应多个地点，结果不唯一，请提供更具体的名称。"
            locations.append(pois[0]["location"])

        mode = {"straight": 0, "driving": 1, "walking": 3}[
            requirement.distance_mode or "straight"
        ]
        walking_fallback = mode == 3 and _straight_meters(*locations) >= 4500
        if walking_fallback:
            mode = 0
        meters = self._amap.measure_distance(*locations, mode=mode)
        label = {0: "直线距离", 1: "驾车距离", 3: "步行距离"}[mode]
        notice = (
            "步行测距仅支持约 5 公里以内，本次先提供直线距离。"
            if walking_fallback else ""
        )
        return (
            f"{notice}{requirement.origin}到{requirement.destination}的{label}"
            f"约 {meters / 1000:g} 公里。"
        )

    def _weather(self, requirement: TravelRequirement) -> str:
        if not requirement.city:
            return "请先说明要查询天气的城市或区县。"
        today = self._today_provider()
        kind = requirement.weather_time_kind
        if kind is None:
            kind = (
                "forecast_range" if requirement.end_date
                else "forecast_date" if requirement.start_date or requirement.date_expression
                else "realtime"
            )
        if kind == "ambiguous":
            return "请说明想看当前实况，还是哪一天的天气预报。"
        if kind == "realtime":
            expression = requirement.date_expression or ""
            if requirement.end_date or any(
                word in expression for word in ("今天", "今晚", "明天", "后天", "未来", "中秋", "国庆")
            ):
                return "该问题涉及指定日期或时间范围，请提供具体日期后查询天气预报。"
            if requirement.start_date and requirement.start_date != today.isoformat():
                return "实时天气不能回答其他日期，请说明要查询的日期。"
            adcode = self._amap.resolve_adcode(requirement.city)
            return self._realtime(requirement.city, adcode)

        relative_range_end = (
            _relative_weather_date(requirement.date_expression, today)
            if kind == "forecast_range"
            and (requirement.date_expression or "").startswith("从现在到")
            else None
        )
        relative_date = (
            _relative_weather_date(requirement.date_expression, today)
            if kind == "forecast_date" else None
        )
        start_date = (
            today.isoformat() if relative_range_end else
            relative_date.isoformat() if relative_date else requirement.start_date
        )
        if not start_date:
            return "请提供具体日期（公历年月日），才能查询对应的天气预报。"
        start = date.fromisoformat(start_date)
        end_date = relative_range_end.isoformat() if relative_range_end else requirement.end_date
        end = date.fromisoformat(end_date) if end_date else start
        if kind == "forecast_range" and end_date is None:
            if requirement.duration_days is None:
                return "请说明预报范围的结束日期或具体天数。"
            end = start + timedelta(days=requirement.duration_days - 1)
        if end < start:
            return "天气预报的结束日期不能早于开始日期。"
        if start < today or end > today + timedelta(days=3):
            return "指定日期超出高德近期天气预报范围，暂时无法查询。"

        adcode = self._amap.resolve_adcode(requirement.city)
        payload = self._amap.weather_adcode(adcode, forecast=True)
        forecasts = payload.get("forecasts")
        if not isinstance(forecasts, list):
            raise AmapApiError("AMap forecast response is invalid")
        matching = [
            item for item in forecasts
            if isinstance(item, dict) and item.get("adcode") == adcode
        ]
        if len(matching) != 1 or not isinstance(matching[0].get("casts"), list):
            raise AmapApiError("AMap forecast adcode or casts are invalid")
        casts = {
            item["date"]: item for item in matching[0]["casts"]
            if isinstance(item, dict) and isinstance(item.get("date"), str)
        }
        dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
        if any(day.isoformat() not in casts for day in dates):
            return "高德返回的预报不包含所问日期，暂时无法回答。"
        night_only = bool(
            requirement.date_expression
            and any(word in requirement.date_expression for word in ("今晚", "夜间", "晚上"))
        )
        lines = []
        for day in dates:
            cast = casts[day.isoformat()]
            if night_only:
                weather = cast.get("nightweather")
                if not isinstance(weather, str) or not weather:
                    raise AmapApiError("AMap night forecast is missing")
                lines.append(f"{day.isoformat()} {requirement.city}夜间：{weather}。")
            else:
                day_weather = cast.get("dayweather")
                night_weather = cast.get("nightweather")
                if not isinstance(day_weather, str) or not isinstance(night_weather, str):
                    raise AmapApiError("AMap day or night forecast is missing")
                lines.append(
                    f"{day.isoformat()} {requirement.city}：白天{day_weather}，夜间{night_weather}。"
                )
        return "\n".join(lines)

    def _realtime(self, city: str, adcode: str) -> str:
        payload = self._amap.weather_adcode(adcode, forecast=False)
        lives = payload.get("lives")
        if not isinstance(lives, list):
            raise AmapApiError("AMap live weather response is invalid")
        matching = [
            item for item in lives
            if isinstance(item, dict) and item.get("adcode") == adcode
        ]
        if len(matching) != 1 or not isinstance(matching[0].get("weather"), str):
            raise AmapApiError("AMap live weather adcode or conditions are invalid")
        item = matching[0]
        temperature = f"，{item['temperature']}℃" if item.get("temperature") else ""
        reported = f"（{item['reporttime']}发布）" if item.get("reporttime") else ""
        return f"{city}当前实况{reported}：{item['weather']}{temperature}。"
