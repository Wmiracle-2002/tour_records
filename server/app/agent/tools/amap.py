"""AMap Web Service API adapter used by the Travel Agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.agent.tools.layer import ToolResult, ToolUnavailableError
from app.core.config import Settings, get_settings


AmapTransport = Callable[[str, dict[str, str], float], dict[str, Any]]


class AmapApiError(RuntimeError):
    """高德 Web API 返回业务失败。"""


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
        try:
            payload = self._transport(
                f"{self._base_url}{path}", request_params, self._timeout_seconds
            )
        except ToolUnavailableError:
            raise
        except (OSError, TimeoutError, URLError) as error:
            raise ToolUnavailableError("AMap Web API is temporarily unavailable") from error
        except Exception as error:
            raise AmapApiError("AMap Web API request failed") from error

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
        return self._request(
            "/v3/distance",
            {
                "origins": "|".join(required_text(origin, "origin") for origin in origins),
                "destination": required_text(destination, "destination"),
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

        params = {
            "origin": required_text(origin, "origin"),
            "destination": required_text(destination, "destination"),
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
        return self._request(paths[mode], params)


class AmapWebTool:
    """将一个高德 Web API 方法包装成 Agent Tool。"""

    def __init__(self, name: str, description: str, handler: Callable[..., dict[str, Any]]) -> None:
        self.name = name
        self.description = description
        self._handler = handler

    def run(self, **arguments: Any) -> ToolResult[dict[str, Any]]:
        try:
            payload = self._handler(**arguments)
        except AmapApiError as error:
            return ToolResult.failed(str(error), error_code="amap_api_error")
        return ToolResult.completed(payload)


def create_amap_tools(client: AmapWebClient) -> tuple[AmapWebTool, ...]:
    """创建高德 Web API 工具集合。"""
    return (
        AmapWebTool("keyword_search", "搜索关键词对应的 POI", client.keyword_search),
        AmapWebTool("around_search", "搜索坐标周边的 POI", client.around_search),
        AmapWebTool("poi_detail", "查询 POI 详情", client.poi_detail),
        AmapWebTool("weather", "查询城市实时天气或预报", client.weather),
        AmapWebTool("distance", "测量多个起点到终点的距离", client.distance),
        AmapWebTool(
            "driving_route",
            "查询驾车路线",
            lambda **arguments: client.route("driving", **arguments),
        ),
        AmapWebTool(
            "transit_route",
            "查询公交路线",
            lambda **arguments: client.route("transit", **arguments),
        ),
        AmapWebTool(
            "walking_route",
            "查询步行路线",
            lambda **arguments: client.route("walking", **arguments),
        ),
        AmapWebTool(
            "cycling_route",
            "查询骑行路线",
            lambda **arguments: client.route("cycling", **arguments),
        ),
        AmapWebTool("geocode", "将地址转换为经纬度", client.geocode),
        AmapWebTool("reverse_geocode", "将经纬度转换为地址", client.reverse_geocode),
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
