"""AMap Web Service API adapter used by the Travel Agent."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pydantic import Field, field_validator, model_validator

from app.agent.observability import current_request_id
from app.agent.tools.layer import ToolInputModel, ToolResult, ToolUnavailableError
from app.core.config import Settings, get_settings


AmapTransport = Callable[[str, dict[str, str], float], dict[str, Any]]
_LOGGER = logging.getLogger("footmarks.agent.amap")
_COORDINATE_PATTERN = re.compile(
    r"^-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$"
)


class AmapApiError(RuntimeError):
    """高德 Web API 返回业务失败。"""


class AmapTimeoutError(ToolUnavailableError):
    """高德 Web API 请求超时。"""


def default_amap_transport(
    url: str, params: dict[str, str], timeout: float
) -> dict[str, Any]:
    """通过标准库发起高德 JSON GET 请求。"""
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("AMap response must be a JSON object")
    return payload


def required_text(value: str, name: str) -> str:
    """校验并清理必填文本参数。"""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _is_coordinate(value: str) -> bool:
    """判断地点参数是否已经是高德要求的经纬度格式。"""
    return bool(_COORDINATE_PATTERN.fullmatch(value))


def _validate_coordinates(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("coordinates must be a string")
    normalized = value.strip()
    if not _is_coordinate(normalized):
        raise ValueError("coordinates must use longitude,latitude format")
    longitude, latitude = (float(part.strip()) for part in normalized.split(","))
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("coordinates are outside longitude/latitude bounds")
    return normalized


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _optional_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _place_text(value: str, name: str) -> str:
    normalized = _required_text(value, name)
    if _is_coordinate(normalized):
        return _validate_coordinates(normalized)
    return normalized


def _log_amap_event(event: str, **fields: Any) -> None:
    _LOGGER.info(
        json.dumps({"event": event, **fields}, ensure_ascii=False, default=str)
    )


class KeywordSearchInput(ToolInputModel):
    keywords: str = Field(min_length=1, description="要搜索的景点或美食关键词")
    city: str | None = Field(default=None, description="限定的城市名称或高德城市编码")
    types: str | None = Field(default=None, description="高德 POI 分类编码")
    page: int = Field(default=1, ge=1)
    offset: int = Field(default=10, ge=1, le=25)

    @field_validator("keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, value: str) -> str:
        return _required_text(value, "keywords")

    @field_validator("city", "types", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value, "city or types")

    @field_validator("city")
    @classmethod
    def reject_coordinates_as_city(cls, value: str | None) -> str | None:
        if value and _is_coordinate(value):
            raise ValueError("city must be a city name or city code")
        return value


class VerifiedPoiSearchInput(ToolInputModel):
    city: str = Field(min_length=1, description="已确认的查询城市")
    kind: Literal["attraction", "food", "place"] = Field(
        description="景点、餐饮或指定地点"
    )
    place_name: str | None = Field(
        default=None, description="kind=place 时要查找的地点名称"
    )

    @model_validator(mode="after")
    def validate_search(self) -> "VerifiedPoiSearchInput":
        _verified_search_arguments(self.city, self.kind, self.place_name)
        return self


@lru_cache(maxsize=1)
def _known_city_names() -> dict[str, set[str]]:
    source = Path(__file__).resolve().parents[1] / "administrative_divisions_2023.json"
    divisions = json.loads(source.read_text(encoding="utf-8"))
    names: dict[str, set[str]] = {}

    def visit(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            name = node["name"].removesuffix("市")
            names.setdefault(name, set()).add(node["code"])
            visit(node.get("children", []))

    visit(divisions)
    return names


def _verified_search_arguments(
    city: str, kind: str, place_name: str | None
) -> tuple[str, str]:
    normalized_city = _validated_city(city)
    if kind not in {"attraction", "food", "place"}:
        raise ValueError("kind must be attraction, food or place")
    if kind == "place":
        keyword = _required_text(place_name, "place_name")
        if "|" in keyword or "\n" in keyword or "\r" in keyword:
            raise ValueError("place_name must be one place")
    else:
        if place_name is not None:
            raise ValueError("place_name is only valid for kind=place")
        keyword = "景点" if kind == "attraction" else "美食"
    return normalized_city, keyword


def _validated_city(city: str) -> str:
    normalized_city = _required_text(city, "city")
    if (
        _is_coordinate(normalized_city)
        or "|" in normalized_city
        or any(char in normalized_city for char in ("\n", "\r", ","))
        or (normalized_city.isascii() and not re.fullmatch(r"\d{6}", normalized_city))
    ):
        raise ValueError("city must be one administrative name or six-digit adcode")
    if not normalized_city.isascii():
        matches = _known_city_names().get(normalized_city.removesuffix("市"), set())
        if len(matches) != 1:
            raise ValueError("city is unknown or ambiguous in the city catalog")
    return normalized_city


def _strict_coordinate(value: str) -> str:
    normalized = _required_text(value, "coordinates")
    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) != 2 or not all(
        re.fullmatch(r"-?\d+(?:\.\d{1,6})?", part) for part in parts
    ):
        raise ValueError("coordinates must be longitude,latitude with at most 6 decimals")
    return _validate_coordinates(",".join(parts))


def _city_matches(poi: dict[str, Any], city: str) -> bool:
    adcode = poi.get("adcode")
    if adcode is not None and (
        not isinstance(adcode, str) or not re.fullmatch(r"\d{6}", adcode)
    ):
        return False
    if re.fullmatch(r"\d{6}", city):
        if adcode is None:
            return False
        if city.endswith("0000"):
            return adcode[:2] == city[:2]
        if city.endswith("00"):
            return adcode[:4] == city[:4]
        return adcode == city
    requested = city.removesuffix("市")
    return any(
        isinstance(poi.get(field), str)
        and poi[field].removesuffix("市") == requested
        for field in ("cityname", "adname")
    )


def _poi_matches_kind(poi: dict[str, Any], kind: str) -> bool:
    if kind == "place":
        return True
    category = poi["type"]
    if kind == "food":
        return category.startswith("餐饮服务")
    return category.startswith("风景名胜") or (
        category.startswith("科教文化服务")
        and any(word in poi["name"] for word in ("博物馆", "纪念馆", "展览馆"))
    )


class AroundSearchInput(ToolInputModel):
    coordinates: str = Field(description="中心点经纬度，格式为经度,纬度")
    keywords: str | None = Field(default=None, description="周边 POI 关键词")
    types: str | None = Field(default=None, description="高德 POI 分类编码")
    radius: int = Field(default=3000, ge=1, le=50000)
    page: int = Field(default=1, ge=1)
    offset: int = Field(default=10, ge=1, le=25)

    @field_validator("coordinates")
    @classmethod
    def validate_center(cls, value: str) -> str:
        return _validate_coordinates(value)

    @field_validator("keywords", "types", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value, "keywords or types")


class PoiDetailInput(ToolInputModel):
    poi_id: str = Field(min_length=1, description="POI 唯一标识，不是景点名称")

    @field_validator("poi_id", mode="before")
    @classmethod
    def strip_poi_id(cls, value: str) -> str:
        return _required_text(value, "poi_id")


class WeatherInput(ToolInputModel):
    city: str = Field(min_length=1, description="城市名称或高德城市编码，不是坐标")
    forecast: bool = Field(default=False, description="true 查询预报，false 查询实时天气")

    @field_validator("city", mode="before")
    @classmethod
    def validate_city(cls, value: str) -> str:
        normalized = _required_text(value, "city")
        if not normalized or _is_coordinate(normalized):
            raise ValueError("city must be a city name or city code")
        return normalized


class DistanceInput(ToolInputModel):
    origins: list[str] = Field(min_length=1, max_length=100, description="一个或多个明确起点")
    destination: str = Field(min_length=1, description="明确终点")
    distance_type: Literal[0, 1, 3] = Field(default=1)

    @field_validator("origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        return [_place_text(value, "origin") for value in values]

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        return _place_text(value, "destination")


class DrivingRouteInput(ToolInputModel):
    origin: str = Field(min_length=1, description="明确路线起点")
    destination: str = Field(min_length=1, description="明确路线终点")
    city: str | None = Field(default=None, description="路线所在城市，用于地点消歧")

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def clean_endpoints(cls, value: str) -> str:
        return _place_text(value, "route endpoint")

    @field_validator("city", mode="before")
    @classmethod
    def clean_city(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, "city")
        if normalized and _is_coordinate(normalized):
            raise ValueError("city must be a city name or city code")
        return normalized


class TransitRouteInput(ToolInputModel):
    origin: str = Field(min_length=1, description="明确公交路线起点")
    destination: str = Field(min_length=1, description="明确公交路线终点")
    city: str = Field(min_length=1, description="公交路线所在城市")
    destination_city: str | None = Field(default=None, description="终点所在城市")

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def clean_endpoints(cls, value: str) -> str:
        return _place_text(value, "route endpoint")

    @field_validator("city", "destination_city", mode="before")
    @classmethod
    def clean_cities(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, "city")
        if normalized and _is_coordinate(normalized):
            raise ValueError("city must be a city name or city code")
        return normalized


class WalkingRouteInput(DrivingRouteInput):
    pass


class CyclingRouteInput(DrivingRouteInput):
    pass


class GeocodeInput(ToolInputModel):
    address: str = Field(min_length=1, description="要转换为坐标的地址或地点")
    city: str | None = Field(default=None, description="地址所在城市，用于消歧")


class ReverseGeocodeInput(ToolInputModel):
    coordinates: str = Field(description="待反查地址的经纬度，格式为经度,纬度")
    extensions: Literal["base", "all"] = "base"

    @field_validator("coordinates")
    @classmethod
    def validate_location(cls, value: str) -> str:
        return _validate_coordinates(value)


class AmapWebClient:
    """高德 Web 服务 API 的薄适配层，返回未经 Normalizer 处理的原始 JSON。"""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://restapi.amap.com",
        timeout_seconds: float = 10.0,
        transport: AmapTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._api_key = api_key.strip() if api_key else None
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport or default_amap_transport

    def _request(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self._api_key:
            raise ToolUnavailableError("AMap Web API key is not configured")

        request_params = {"key": self._api_key, "output": "json", **params}
        request_id = current_request_id() or "unknown"
        log_params = {
            name: value for name, value in request_params.items() if name != "key"
        }
        _log_amap_event(
            "amap_request",
            request_id=request_id,
            method="GET",
            path=path,
            parameters=log_params,
        )
        try:
            payload = self._transport(
                f"{self._base_url}{path}", request_params, self._timeout_seconds
            )
        except ToolUnavailableError:
            _log_amap_event(
                "amap_transport_error",
                request_id=request_id,
                path=path,
                error_type="ToolUnavailableError",
            )
            raise
        except TimeoutError as error:
            _log_amap_event(
                "amap_transport_error",
                request_id=request_id,
                path=path,
                error_type=type(error).__name__,
            )
            raise AmapTimeoutError("AMap Web API request timed out") from error
        except (OSError, URLError) as error:
            _log_amap_event(
                "amap_transport_error",
                request_id=request_id,
                path=path,
                error_type=type(error).__name__,
            )
            raise ToolUnavailableError("AMap Web API is temporarily unavailable") from error
        except Exception as error:
            _log_amap_event(
                "amap_transport_error",
                request_id=request_id,
                path=path,
                error_type=type(error).__name__,
            )
            raise AmapApiError("AMap Web API request failed") from error

        if not isinstance(payload, dict):
            raise AmapApiError("AMap response must be an object")
        _log_amap_event(
            "amap_response",
            request_id=request_id,
            path=path,
            **{
                name: payload[name]
                for name in ("status", "info", "infocode", "errcode", "errmsg")
                if name in payload
            },
        )
        if str(payload.get("status")) == "0":
            raise AmapApiError(str(payload.get("info") or "AMap request failed"))
        if "errcode" in payload and str(payload["errcode"]) not in {"0", "10000"}:
            raise AmapApiError(str(payload.get("errmsg") or "AMap request failed"))
        return payload

    def keyword_search(
        self,
        keywords: str,
        city: str | None = None,
        types: str | None = None,
        page: int = 1,
        offset: int = 10,
    ) -> dict[str, Any]:
        if page < 1 or offset < 1:
            raise ValueError("page and offset must be positive")
        params = {"keywords": required_text(keywords, "keywords")}
        if city:
            params["city"] = city.strip()
        if types:
            params["types"] = types.strip()
        params.update({"page": str(page), "offset": str(offset)})
        return self._request("/v3/place/text", params)

    def search_verified_pois(
        self,
        city: str,
        kind: Literal["attraction", "food", "place"],
        place_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_city, keyword = _verified_search_arguments(city, kind, place_name)
        payload = self._request(
            "/v3/place/text",
            {
                "keywords": keyword,
                "city": normalized_city,
                "citylimit": "true",
                "page": "1",
                "offset": "10",
                "extensions": "base",
            },
        )
        if str(payload.get("status")) != "1" or (
            "infocode" in payload and str(payload["infocode"]) != "10000"
        ):
            raise AmapApiError(str(payload.get("info") or "AMap POI search failed"))
        pois = payload.get("pois")
        if not isinstance(pois, list):
            raise AmapApiError("AMap POI response must contain a pois list")
        verified: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            if not all(
                isinstance(poi.get(field), str) and poi[field].strip()
                for field in ("id", "name", "type", "location")
            ):
                continue
            if not _city_matches(poi, normalized_city) or not _poi_matches_kind(poi, kind):
                continue
            if kind == "place" and poi["name"].strip() != keyword and not (
                poi["name"].strip() == f"{keyword}景区"
                and poi["type"].startswith("风景名胜")
            ):
                continue
            try:
                location = _validate_coordinates(poi["location"])
            except ValueError:
                continue
            if any(
                len(part.partition(".")[2]) > 6 for part in location.split(",")
            ):
                continue
            if poi["id"] in seen_ids:
                continue
            seen_ids.add(poi["id"])
            verified.append({**poi, "location": location})
        if kind == "place" and any(poi["name"].strip() == keyword for poi in verified):
            verified = [poi for poi in verified if poi["name"].strip() == keyword]
        return {"status": "1", "pois": verified}

    def resolve_adcode(self, city: str) -> str:
        normalized_city = _validated_city(city)
        payload = self._request(
            "/v3/config/district",
            {
                "keywords": normalized_city,
                "subdistrict": "0",
                "extensions": "base",
                "page": "1",
                "offset": "20",
            },
        )
        if str(payload.get("status")) != "1" or (
            "infocode" in payload and str(payload["infocode"]) != "10000"
        ):
            raise AmapApiError(str(payload.get("info") or "AMap district lookup failed"))
        districts = payload.get("districts")
        if not isinstance(districts, list):
            raise AmapApiError("AMap district response must contain a districts list")
        matches = {
            item["adcode"]
            for item in districts
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item.get("level") in {"city", "district", "province"}
            and isinstance(item.get("adcode"), str)
            and re.fullmatch(r"\d{6}", item["adcode"])
            and (
                item["adcode"] == normalized_city
                if normalized_city.isascii()
                else item["name"].removesuffix("市")
                == normalized_city.removesuffix("市")
            )
        }
        if len(matches) != 1:
            raise AmapApiError("AMap district result is missing or ambiguous")
        return matches.pop()

    def weather_adcode(self, adcode: str, *, forecast: bool) -> dict[str, Any]:
        if not isinstance(adcode, str) or not re.fullmatch(r"\d{6}", adcode):
            raise ValueError("weather city must be a six-digit AMap adcode")
        payload = self._request(
            "/v3/weather/weatherInfo",
            {"city": adcode, "extensions": "all" if forecast else "base"},
        )
        if str(payload.get("status")) != "1" or (
            "infocode" in payload and str(payload["infocode"]) != "10000"
        ):
            raise AmapApiError(str(payload.get("info") or "AMap weather request failed"))
        return payload

    def measure_distance(self, origin: str, destination: str, *, mode: int) -> int:
        start = _strict_coordinate(origin)
        end = _strict_coordinate(destination)
        if mode not in {0, 1, 3}:
            raise ValueError("distance mode must be 0, 1 or 3")
        payload = self._request(
            "/v3/distance",
            {"origins": start, "destination": end, "type": str(mode)},
        )
        if str(payload.get("status")) != "1" or (
            "infocode" in payload and str(payload["infocode"]) != "10000"
        ):
            raise AmapApiError(str(payload.get("info") or "AMap distance request failed"))
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1:
            raise AmapApiError("AMap distance response must contain one result")
        result = results[0]
        if (
            not isinstance(result, dict)
            or result.get("info")
            or result.get("code")
            or not re.fullmatch(r"\d+", str(result.get("distance", "")))
        ):
            raise AmapApiError("AMap distance result is invalid")
        return int(result["distance"])

    def around_search(
        self,
        location: str,
        keywords: str | None = None,
        types: str | None = None,
        radius: int = 3000,
        page: int = 1,
        offset: int = 10,
    ) -> dict[str, Any]:
        if radius <= 0 or page < 1 or offset < 1:
            raise ValueError("radius, page and offset must be positive")
        params = {"location": required_text(location, "location")}
        if keywords:
            params["keywords"] = keywords.strip()
        if types:
            params["types"] = types.strip()
        params.update({"radius": str(radius), "page": str(page), "offset": str(offset)})
        return self._request("/v3/place/around", params)

    def poi_detail(self, poi_id: str) -> dict[str, Any]:
        return self._request("/v3/place/detail", {"id": required_text(poi_id, "poi_id")})

    def weather(self, city: str, forecast: bool = False) -> dict[str, Any]:
        return self._request(
            "/v3/weather/weatherInfo",
            {
                "city": required_text(city, "city"),
                "extensions": "all" if forecast else "base",
            },
        )

    def geocode(self, address: str, city: str | None = None) -> dict[str, Any]:
        params = {"address": required_text(address, "address")}
        if city:
            params["city"] = city.strip()
        return self._request("/v3/geocode/geo", params)

    def reverse_geocode(
        self, location: str, extensions: str = "base"
    ) -> dict[str, Any]:
        if extensions not in {"base", "all"}:
            raise ValueError("extensions must be base or all")
        return self._request(
            "/v3/geocode/regeo",
            {
                "location": required_text(location, "location"),
                "extensions": extensions,
            },
        )

    def _resolve_location(self, value: str, city: str | None = None) -> str:
        """将中文地点名转换为路线接口使用的经纬度。"""
        normalized = required_text(value, "location")
        if _is_coordinate(normalized):
            return normalized.replace(" ", "")

        payload = self.geocode(normalized, city=city)
        geocodes = payload.get("geocodes")
        if not isinstance(geocodes, list) or not geocodes:
            raise AmapApiError(f"Unable to geocode location: {normalized}")
        first = geocodes[0]
        if not isinstance(first, dict) or not first.get("location"):
            raise AmapApiError(f"Unable to geocode location: {normalized}")
        return required_text(str(first["location"]), "geocoded location")

    def _poi_candidates(
        self, value: str, city: str | None = None
    ) -> list[tuple[str, str]]:
        """Return POI locations together with their administrative area."""
        payload = self.keyword_search(value, city=city)
        pois = payload.get("pois")
        if not isinstance(pois, list) or not pois:
            raise AmapApiError(f"Unable to find POI location: {value}")
        candidates: list[tuple[str, str]] = []
        for poi in pois:
            if not isinstance(poi, dict) or not poi.get("location"):
                continue
            location = required_text(str(poi["location"]), "POI location")
            area = str(
                poi.get("adcode")
                or poi.get("cityname")
                or poi.get("city")
                or poi.get("adname")
                or ""
            ).strip()
            candidates.append((location, area))
        if not candidates:
            raise AmapApiError(f"Unable to find POI location: {value}")
        return candidates

    def _resolve_poi_location(self, value: str, city: str | None = None) -> str:
        """Use the first POI location as a route fallback."""
        return self._poi_candidates(value, city=city)[0][0]

    def _resolve_route_locations(
        self, origin: str, destination: str, city: str | None = None
    ) -> tuple[str, str]:
        if city:
            return (
                self._resolve_location(origin, city=city),
                self._resolve_location(destination, city=city),
            )

        origin_candidates = (
            [(origin.replace(" ", ""), "")]
            if _is_coordinate(origin)
            else self._poi_candidates(origin)
        )
        destination_candidates = (
            [(destination.replace(" ", ""), "")]
            if _is_coordinate(destination)
            else self._poi_candidates(destination)
        )
        for origin_location, origin_area in origin_candidates:
            for destination_location, destination_area in destination_candidates:
                if origin_area and origin_area == destination_area:
                    return origin_location, destination_location
        return origin_candidates[0][0], destination_candidates[0][0]

    def distance(
        self,
        origins: list[str],
        destination: str,
        distance_type: int = 1,
    ) -> dict[str, Any]:
        if not 1 <= len(origins) <= 100:
            raise ValueError("origins must contain between 1 and 100 locations")
        if distance_type not in {0, 1, 3}:
            raise ValueError("distance_type must be 0, 1 or 3")
        resolved_origins = [
            self._resolve_location(origin) for origin in origins
        ]
        resolved_destination = self._resolve_location(destination)
        return self._request(
            "/v3/distance",
            {
                "origins": "|".join(resolved_origins),
                "destination": resolved_destination,
                "type": str(distance_type),
            },
        )

    def route(
        self,
        mode: str,
        origin: str,
        destination: str,
        city: str | None = None,
        cityd: str | None = None,
        strategy: int | None = None,
        extensions: str | None = None,
        waypoints: list[str] | None = None,
    ) -> dict[str, Any]:
        paths = {
            "driving": "/v3/direction/driving",
            "transit": "/v3/direction/transit/integrated",
            "walking": "/v3/direction/walking",
            "cycling": "/v4/direction/bicycling",
        }
        if mode not in paths:
            raise ValueError("mode must be driving, transit, walking or cycling")
        if mode == "transit" and not city:
            raise ValueError("city is required for transit routes")

        normalized_origin = required_text(origin, "origin")
        normalized_destination = required_text(destination, "destination")
        resolved_origin, resolved_destination = self._resolve_route_locations(
            normalized_origin, normalized_destination, city=city
        )
        params = {
            "origin": resolved_origin,
            "destination": resolved_destination,
        }
        if city:
            params["city"] = city.strip()
        if cityd:
            params["cityd"] = cityd.strip()
        if strategy is not None:
            params["strategy"] = str(strategy)
        if extensions:
            params["extensions"] = extensions.strip()
        if waypoints:
            params["waypoints"] = ";".join(
                required_text(point, "waypoint") for point in waypoints
            )
        try:
            return self._request(paths[mode], params)
        except AmapApiError as error:
            if (
                str(error) != "ENGINE_RESPONSE_DATA_ERROR"
                or _is_coordinate(normalized_origin)
                or _is_coordinate(normalized_destination)
            ):
                raise
            params["origin"] = self._resolve_poi_location(normalized_origin, city=city)
            params["destination"] = self._resolve_poi_location(
                normalized_destination, city=city
            )
            return self._request(paths[mode], params)


class AmapWebTool:
    """将一个高德 Web API 方法包装成 Agent Tool。"""

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., dict[str, Any]],
        input_model: type[ToolInputModel],
        information_need: str | None,
        examples: tuple[dict[str, Any], ...] = (),
    ) -> None:
        self.name = name
        self.description = description
        self._handler = handler
        self.input_model = input_model
        self.information_need = information_need
        self.examples = examples

    def run(self, **arguments: Any) -> ToolResult[dict[str, Any]]:
        try:
            payload = self._handler(**arguments)
        except AmapTimeoutError as error:
            return ToolResult.unavailable(str(error), error_code="tool_timeout")
        except AmapApiError as error:
            return ToolResult.failed(str(error), error_code="tool_provider_error")
        return ToolResult.completed(payload)


def create_amap_tools(client: AmapWebClient) -> tuple[AmapWebTool, ...]:
    """创建高德 Web API 工具集合。"""
    return (
        AmapWebTool(
            "keyword_search",
            "在已确认城市搜索景点、餐饮或指定地点",
            client.search_verified_pois,
            VerifiedPoiSearchInput,
            "pois",
            ({"city": "南京", "kind": "attraction"},),
        ),
        AmapWebTool(
            "around_search",
            "搜索坐标周边的 POI",
            lambda *, coordinates, **arguments: client.around_search(
                location=coordinates, **arguments
            ),
            AroundSearchInput,
            "pois",
            ({"coordinates": "118.796877,32.060255", "keywords": "美食"},),
        ),
        AmapWebTool(
            "poi_detail",
            "查询 POI 详情",
            client.poi_detail,
            PoiDetailInput,
            "pois",
            ({"poi_id": "B000000001"},),
        ),
        AmapWebTool(
            "weather",
            "查询城市实时天气或预报",
            client.weather,
            WeatherInput,
            "weather",
            ({"city": "南京", "forecast": True},),
        ),
        AmapWebTool(
            "distance",
            "测量多个起点到终点的距离，地点可以是名称或经纬度",
            client.distance,
            DistanceInput,
            "distances",
            ({"origins": ["中山陵"], "destination": "夫子庙"},),
        ),
        AmapWebTool(
            "driving_route",
            "查询驾车路线，起点和终点可以是名称或经纬度",
            lambda **arguments: client.route("driving", **arguments),
            DrivingRouteInput,
            "routes",
            ({"origin": "中山陵", "destination": "夫子庙", "city": "南京"},),
        ),
        AmapWebTool(
            "transit_route",
            "查询公交路线，起点和终点可以是名称或经纬度",
            lambda **arguments: client.route(
                "transit",
                cityd=arguments.pop("destination_city", None),
                **arguments,
            ),
            TransitRouteInput,
            "routes",
            ({"origin": "中山陵", "destination": "夫子庙", "city": "南京"},),
        ),
        AmapWebTool(
            "walking_route",
            "查询步行路线，起点和终点可以是名称或经纬度",
            lambda **arguments: client.route("walking", **arguments),
            WalkingRouteInput,
            "routes",
            ({"origin": "中山陵", "destination": "夫子庙", "city": "南京"},),
        ),
        AmapWebTool(
            "cycling_route",
            "查询骑行路线，起点和终点可以是名称或经纬度",
            lambda **arguments: client.route("cycling", **arguments),
            CyclingRouteInput,
            "routes",
            ({"origin": "中山陵", "destination": "夫子庙", "city": "南京"},),
        ),
        AmapWebTool(
            "geocode", "将地址转换为经纬度", client.geocode, GeocodeInput, None
        ),
        AmapWebTool(
            "reverse_geocode",
            "将经纬度转换为地址",
            lambda *, coordinates, **arguments: client.reverse_geocode(
                coordinates, **arguments
            ),
            ReverseGeocodeInput,
            None,
        ),
    )


def create_amap_tools_from_settings(
    settings: Settings | None = None,
    transport: AmapTransport | None = None,
) -> tuple[AmapWebTool, ...]:
    """从服务端配置创建高德工具，Key 只从环境变量读取。"""
    current_settings = settings or get_settings()
    client = AmapWebClient(
        api_key=current_settings.amap_web_key,
        base_url=current_settings.amap_base_url,
        timeout_seconds=current_settings.amap_timeout_seconds,
        transport=transport,
    )
    return create_amap_tools(client)
