"""Convert raw tool responses into the Agent's structured business models."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agent.models import (
    BudgetInfo,
    DistanceInfo,
    POIInfo,
    RouteInfo,
    RouteMode,
    TravelHistoryInfo,
    WeatherInfo,
)
from app.agent.tools.layer import ToolResult


T = TypeVar("T")


class NormalizerError(ValueError):
    """工具结果结构不符合预期，无法安全转换为业务模型。"""


def is_empty_result(value: Any) -> bool:
    """判断工具是否成功返回了空数据。空数据不是异常。"""
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return not value.strip()
    if isinstance(value, (Mapping, Sequence)):
        return len(value) == 0
    return False


def _mapping(value: Any, name: str = "response") -> Mapping[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if not isinstance(value, Mapping):
        raise NormalizerError(f"{name} must be an object")
    return value


def _text(value: Any, name: str, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise NormalizerError(f"{name} is missing")
        return None
    if not isinstance(value, (str, int, float)):
        raise NormalizerError(f"{name} must be text")
    result = str(value).strip()
    if not result and required:
        raise NormalizerError(f"{name} must not be blank")
    return result or None


def _number(value: Any, name: str, required: bool = True) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise NormalizerError(f"{name} is missing")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizerError(f"{name} must be numeric") from error
    if not result.is_finite():
        raise NormalizerError(f"{name} must be finite")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    number = _number(value, name)
    assert number is not None
    if number < 0 or number != number.to_integral_value():
        raise NormalizerError(f"{name} must be a non-negative integer")
    return int(number)


def _list_value(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise NormalizerError(f"{name} must be a list")
    return list(value)


def normalize_poi(raw: Any) -> list[POIInfo]:
    """将高德 POI 搜索或详情响应转换为 POI 列表。"""
    if is_empty_result(raw):
        return []

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        items = list(raw)
    else:
        payload = _mapping(raw)
        if "pois" in payload:
            items = _list_value(payload["pois"], "pois")
        elif isinstance(payload.get("data"), Mapping) and "pois" in payload["data"]:
            items = _list_value(payload["data"]["pois"], "data.pois")
        elif "id" in payload:
            items = [payload]
        else:
            if payload.get("status") == "1":
                return []
            raise NormalizerError("pois is missing")

    result: list[POIInfo] = []
    for index, item in enumerate(items):
        poi = _mapping(item, f"pois[{index}]")
        business = poi.get("biz_ext")
        if business is not None and not isinstance(business, Mapping):
            raise NormalizerError(f"pois[{index}].biz_ext must be an object")
        result.append(
            POIInfo(
                poi_id=_text(poi.get("id"), f"pois[{index}].id", required=True),
                name=_text(poi.get("name"), f"pois[{index}].name", required=True),
                address=_text(poi.get("address"), f"pois[{index}].address"),
                location=_text(
                    poi.get("location"), f"pois[{index}].location", required=True
                ),
                category=_text(poi.get("type") or poi.get("typecode"), "category"),
                opening_hours=_text(
                    business.get("open_time") if business else None,
                    f"pois[{index}].biz_ext.open_time",
                ),
            )
        )
    return result


def _weather_items(raw: Any) -> tuple[Mapping[str, Any], str | None, bool]:
    payload = _mapping(raw)
    root_location = _text(payload.get("city") or payload.get("location"), "location")
    if "lives" in payload:
        return tuple(_mapping(item, "lives item") for item in _list_value(payload["lives"], "lives")), root_location, True
    if "casts" in payload:
        return tuple(_mapping(item, "casts item") for item in _list_value(payload["casts"], "casts")), root_location, True
    if "date" in payload or "reporttime" in payload:
        return (payload,), root_location, "daytemp" in payload or "nighttemp" in payload
    if payload.get("status") == "1":
        return (), root_location, False
    raise NormalizerError("weather data is missing")


def _weather_description(item: Mapping[str, Any], forecast: bool) -> str | None:
    if not forecast:
        return _text(item.get("weather"), "weather")
    day = _text(item.get("dayweather") or item.get("weather"), "dayweather")
    night = _text(item.get("nightweather"), "nightweather")
    if day and night and day != night:
        return f"{day} / {night}"
    return day or night


def normalize_weather(raw: Any, location: str | None = None) -> list[WeatherInfo]:
    """将高德实时天气或预报响应转换为天气信息列表。"""
    if is_empty_result(raw):
        return []
    items, response_location, forecast = _weather_items(raw)
    result: list[WeatherInfo] = []
    for index, item in enumerate(items):
        date_value = _text(
            item.get("date") or item.get("reporttime"), f"weather[{index}].date", True
        )
        assert date_value is not None
        if " " in date_value:
            date_value = date_value.split(" ", 1)[0]
        item_location = _text(item.get("city") or item.get("location"), "location")
        resolved_location = item_location or response_location or location
        if not resolved_location:
            raise NormalizerError(f"weather[{index}].location is missing")

        minimum = _number(item.get("nighttemp"), "nighttemp", required=False)
        maximum = _number(item.get("daytemp"), "daytemp", required=False)
        result.append(
            WeatherInfo(
                location=resolved_location,
                date=date_value,
                description=_weather_description(item, forecast),
                temperature_min=float(minimum) if minimum is not None else None,
                temperature_max=float(maximum) if maximum is not None else None,
            )
        )
    return result


def _route_container(raw: Any) -> Mapping[str, Any]:
    payload = _mapping(raw)
    route = payload.get("route")
    if isinstance(route, Mapping):
        return route
    data = payload.get("data")
    if isinstance(data, Mapping):
        return data
    if "paths" in payload or "transits" in payload:
        return payload
    raise NormalizerError("route data is missing")


def normalize_route(
    raw: Any,
    *,
    mode: RouteMode,
    origin_id: str,
    destination_id: str,
) -> RouteInfo:
    """将高德路线响应的第一条可用路线转换为 RouteInfo。"""
    if is_empty_result(raw):
        raise NormalizerError("route result is empty")
    route = _route_container(raw)
    options_key = "transits" if mode == "transit" else "paths"
    options = _list_value(route.get(options_key), options_key)
    if not options:
        raise NormalizerError(f"route.{options_key} is empty")
    first = _mapping(options[0], f"route.{options_key}[0]")
    distance = _nonnegative_int(first.get("distance"), "route.distance")
    duration = _number(first.get("duration"), "route.duration")
    assert duration is not None
    if duration < 0:
        raise NormalizerError("route.duration must be non-negative")
    return RouteInfo(
        origin_id=_text(origin_id, "origin_id", True),
        destination_id=_text(destination_id, "destination_id", True),
        mode=mode,
        distance_meters=distance,
        duration_minutes=ceil(float(duration) / 60),
    )


def normalize_distance(raw: Any, *, origin_id: str, destination_id: str) -> DistanceInfo:
    """将高德距离响应的第一条结果转换为 DistanceInfo。"""
    if is_empty_result(raw):
        raise NormalizerError("distance result is empty")
    payload = _mapping(raw)
    if "distance" in payload:
        first = payload
    else:
        results = _list_value(payload.get("results"), "results")
        if not results:
            raise NormalizerError("distance.results is empty")
        first = _mapping(results[0], "results[0]")
    return DistanceInfo(
        origin_id=_text(origin_id, "origin_id", True),
        destination_id=_text(destination_id, "destination_id", True),
        distance_meters=_nonnegative_int(first.get("distance"), "distance"),
    )


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def normalize_history(raw: Any) -> TravelHistoryInfo:
    """将内部数据库旅行查询结果汇总为历史事实。"""
    if is_empty_result(raw):
        return TravelHistoryInfo()
    if isinstance(raw, TravelHistoryInfo):
        return raw

    payload: Mapping[str, Any] | None = None
    if isinstance(raw, Mapping):
        payload = raw
        if "trips" in payload:
            items = _list_value(payload["trips"], "trips")
        elif isinstance(payload.get("data"), Sequence) and not isinstance(payload["data"], (str, bytes)):
            items = list(payload["data"])
        elif "trip_id" in payload:
            items = [payload]
        elif "trip_count" in payload:
            return TravelHistoryInfo.model_validate(payload)
        else:
            raise NormalizerError("history data is missing")
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        items = list(raw)
    else:
        raise NormalizerError("history must be a list or object")

    cities: list[str] = []
    names: list[str] = []
    poi_ids: list[str] = []
    for index, item in enumerate(items):
        trip = _mapping(item, f"history[{index}]")
        _append_unique(cities, _text(trip.get("city_name"), "city_name"))
        records = _list_value(trip.get("records", []), f"history[{index}].records")
        for record_index, record in enumerate(records):
            record_value = _mapping(record, f"history[{index}].records[{record_index}]")
            _append_unique(names, _text(record_value.get("name"), "record.name"))
            _append_unique(poi_ids, _text(record_value.get("poi_id"), "record.poi_id"))
    trip_count = int(payload["trip_count"]) if payload and "trip_count" in payload else len(items)
    return TravelHistoryInfo(
        trip_count=trip_count,
        visited_cities=cities,
        visited_names=names,
        visited_poi_ids=poi_ids,
    )


def normalize_budget(raw: Any) -> BudgetInfo | None:
    """将预算工具结果转换为 BudgetInfo；空预算保持为 None。"""
    if is_empty_result(raw):
        return None
    if isinstance(raw, BudgetInfo):
        return raw
    return BudgetInfo.model_validate(_mapping(raw, "budget"))


def normalize_tool_result(
    result: ToolResult[Any], normalizer: Callable[[Any], T]
) -> ToolResult[T]:
    """保留工具状态，并将 completed 的数据转换为业务模型。"""
    if result.status == "unavailable":
        return ToolResult.unavailable(
            result.message or "Tool unavailable",
            error_code=result.error_code or "tool_unavailable",
        )
    if result.status == "failed":
        return ToolResult.failed(
            result.message or "Tool execution failed",
            error_code=result.error_code or "tool_failed",
        )
    try:
        data = normalizer(result.data)
    except Exception:
        return ToolResult.failed(
            "Tool response could not be normalized",
            error_code="invalid_tool_response",
        )
    return ToolResult.completed(data, message=result.message)
