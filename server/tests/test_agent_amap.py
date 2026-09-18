from typing import Any

from app.agent.tools.amap import (
    AmapWebClient,
    create_amap_tools,
    create_amap_tools_from_settings,
)
from app.agent.tools.layer import ToolLayer, ToolRegistry
from app.core.config import Settings


class FakeTransport:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"status": "1", "info": "OK"}
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(
        self, url: str, params: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.calls.append((url, params, timeout))
        return self.response


def amap_layer(client: AmapWebClient) -> ToolLayer:
    registry = ToolRegistry()
    for tool in create_amap_tools(client):
        registry.register(tool)
    return ToolLayer(registry)


def test_weather_request_uses_web_service_key_and_adcode() -> None:
    transport = FakeTransport({"status": "1", "lives": [{"city": "南京"}]})
    client = AmapWebClient(
        api_key="test-amap-key",
        transport=transport,
    )

    result = client.weather("320100", forecast=True)

    assert result["lives"][0]["city"] == "南京"
    assert transport.calls == [
        (
            "https://restapi.amap.com/v3/weather/weatherInfo",
            {
                "key": "test-amap-key",
                "output": "json",
                "city": "320100",
                "extensions": "all",
            },
            10.0,
        )
    ]


def test_client_covers_poi_geo_distance_and_route_endpoints() -> None:
    transport = FakeTransport()
    client = AmapWebClient(api_key="test-amap-key", transport=transport)

    client.keyword_search("景点", city="南京", types="110000")
    client.around_search("118.796877,32.060255", keywords="美食")
    client.poi_detail("B000000001")
    client.geocode("南京市中山陵", city="南京")
    client.reverse_geocode("118.796877,32.060255")
    client.distance(["118.796877,32.060255"], "118.805000,32.065000")
    client.route("driving", "118.796877,32.060255", "118.805000,32.065000")
    client.route("transit", "118.796877,32.060255", "118.805000,32.065000", city="南京")
    client.route("walking", "118.796877,32.060255", "118.805000,32.065000")
    client.route("cycling", "118.796877,32.060255", "118.805000,32.065000")

    assert [call[0] for call in transport.calls] == [
        "https://restapi.amap.com/v3/place/text",
        "https://restapi.amap.com/v3/place/around",
        "https://restapi.amap.com/v3/place/detail",
        "https://restapi.amap.com/v3/geocode/geo",
        "https://restapi.amap.com/v3/geocode/regeo",
        "https://restapi.amap.com/v3/distance",
        "https://restapi.amap.com/v3/direction/driving",
        "https://restapi.amap.com/v3/direction/transit/integrated",
        "https://restapi.amap.com/v3/direction/walking",
        "https://restapi.amap.com/v4/direction/bicycling",
    ]


def test_amap_tool_registry_exposes_planned_capabilities() -> None:
    names = {tool.name for tool in create_amap_tools(AmapWebClient("test-key"))}

    assert names == {
        "keyword_search",
        "around_search",
        "poi_detail",
        "weather",
        "distance",
        "driving_route",
        "transit_route",
        "walking_route",
        "cycling_route",
        "geocode",
        "reverse_geocode",
    }


def test_missing_key_is_reported_as_unavailable_without_network_call() -> None:
    transport = FakeTransport()
    result = amap_layer(AmapWebClient(api_key=None, transport=transport)).execute(
        "weather", city="320100"
    )

    assert result.status == "unavailable"
    assert result.error_code == "tool_unavailable"
    assert transport.calls == []


def test_amap_api_error_is_converted_to_failed_result() -> None:
    transport = FakeTransport({"status": "0", "info": "INVALID_USER_KEY"})

    result = amap_layer(
        AmapWebClient(api_key="test-key", transport=transport)
    ).execute("weather", city="320100")

    assert result.status == "failed"
    assert result.error_code == "amap_api_error"
    assert "INVALID_USER_KEY" in result.message


def test_settings_factory_passes_key_to_amap_client() -> None:
    transport = FakeTransport({"status": "1", "lives": []})
    tools = create_amap_tools_from_settings(
        Settings(amap_web_key="configured-key", amap_timeout_seconds=3),
        transport=transport,
    )

    result = amap_layer_from_tools(tools).execute("weather", city="320100")

    assert result.status == "completed"
    assert transport.calls[0][1]["key"] == "configured-key"
    assert transport.calls[0][2] == 3.0


def amap_layer_from_tools(tools) -> ToolLayer:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolLayer(registry)
