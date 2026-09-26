import json
import logging
from typing import Any

import pytest

from app.agent.tools.amap import (
    AmapApiError,
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


def test_amap_rejects_non_object_response() -> None:
    client = AmapWebClient(api_key="test-amap-key", transport=lambda *_: [])
    with pytest.raises(AmapApiError, match="response"):
        client.weather_adcode("320100", forecast=True)


def test_amap_logs_request_parameters_and_error_metadata_without_api_key(caplog) -> None:
    transport = FakeTransport(
        {"status": "0", "info": "ENGINE_RESPONSE_DATA_ERROR", "infocode": "30001"}
    )
    client = AmapWebClient(api_key="test-amap-key", transport=transport)

    with caplog.at_level(logging.INFO, logger="footmarks.agent.amap"):
        with pytest.raises(AmapApiError):
            client.weather("南京", forecast=True)

    events = [json.loads(record.message) for record in caplog.records]
    request_event = next(event for event in events if event["event"] == "amap_request")
    response_event = next(event for event in events if event["event"] == "amap_response")

    assert request_event["path"] == "/v3/weather/weatherInfo"
    assert request_event["parameters"] == {
        "city": "南京",
        "extensions": "all",
        "output": "json",
    }
    assert "key" not in request_event["parameters"]
    assert response_event["infocode"] == "30001"
    assert response_event["info"] == "ENGINE_RESPONSE_DATA_ERROR"
    assert "test-amap-key" not in caplog.text


def amap_layer(client: AmapWebClient) -> ToolLayer:
    registry = ToolRegistry()
    for tool in create_amap_tools(client):
        if tool.information_need is not None:
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


def test_verified_poi_search_builds_fixed_city_limited_request() -> None:
    transport = FakeTransport(
        {
            "status": "1",
            "infocode": "10000",
            "pois": [
                {
                    "id": "food-1",
                    "name": "南京小吃店",
                    "type": "餐饮服务;中餐厅",
                    "cityname": "南京市",
                    "adcode": "320102",
                    "location": "118.796877,32.060255",
                }
            ],
        }
    )
    client = AmapWebClient(api_key="test-key", transport=transport)

    result = client.search_verified_pois(city="南京", kind="food")

    assert [poi["id"] for poi in result["pois"]] == ["food-1"]
    assert transport.calls[0][1] == {
        "key": "test-key",
        "output": "json",
        "keywords": "美食",
        "city": "南京",
        "citylimit": "true",
        "page": "1",
        "offset": "10",
        "extensions": "base",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"city": "", "kind": "food"},
        {"city": "南京|苏州", "kind": "food"},
        {"city": "118.8,32.0", "kind": "food"},
        {"city": "火星市", "kind": "food"},
        {"city": "南京", "kind": "place"},
        {"city": "南京", "kind": "place", "place_name": " "},
        {"city": "南京", "kind": "route"},
    ],
)
def test_verified_poi_search_rejects_invalid_input_before_network(arguments: dict) -> None:
    transport = FakeTransport()
    client = AmapWebClient(api_key="test-key", transport=transport)
    with pytest.raises(ValueError):
        client.search_verified_pois(**arguments)
    assert transport.calls == []


def test_verified_poi_search_filters_wrong_city_category_bad_location_and_duplicates() -> None:
    base = {
        "id": "p1",
        "name": "中山陵",
        "type": "风景名胜;风景名胜",
        "cityname": "南京市",
        "adcode": "320102",
        "location": "118.858000,32.058000",
    }
    transport = FakeTransport(
        {
            "status": "1",
            "pois": [
                {**base, "id": "wrong-city", "cityname": "上海市", "adcode": "310101"},
                {**base, "id": "food", "type": "餐饮服务"},
                {**base, "id": "bad-coords", "location": "999,999"},
                base,
                base,
            ],
        }
    )
    result = AmapWebClient(api_key="test-key", transport=transport).search_verified_pois(
        city="南京", kind="attraction"
    )
    assert [poi["id"] for poi in result["pois"]] == ["p1"]


def test_verified_poi_search_accepts_exact_city_when_base_response_omits_adcode() -> None:
    base = {
        "name": "中山陵", "type": "风景名胜", "cityname": "南京市",
        "location": "118.858000,32.058000",
    }
    transport = FakeTransport({
        "status": "1", "infocode": "10000", "pois": [
            {**base, "id": "correct"},
            {**base, "id": "other-city", "cityname": "上海市"},
            {**base, "id": "bad-adcode", "adcode": "invalid"},
            {**base, "id": "missing-city", "cityname": ""},
        ],
    })
    result = AmapWebClient(api_key="test-key", transport=transport).search_verified_pois(
        city="南京", kind="attraction"
    )
    assert [poi["id"] for poi in result["pois"]] == ["correct"]


@pytest.mark.parametrize(
    "response",
    [
        {"status": "1", "infocode": "30001", "pois": []},
        {"status": "1", "pois": {}},
        {"status": "0", "info": "INVALID_PARAMS"},
    ],
)
def test_verified_poi_search_rejects_provider_errors_and_bad_shape(response: dict) -> None:
    client = AmapWebClient(api_key="test-key", transport=FakeTransport(response))
    with pytest.raises(AmapApiError):
        client.search_verified_pois(city="南京", kind="attraction")


def test_verified_poi_search_matches_county_city_by_adname() -> None:
    transport = FakeTransport(
        {
            "status": "1",
            "pois": [{
                "id": "p1", "name": "亭林园", "type": "风景名胜",
                "cityname": "苏州市", "adname": "昆山市", "adcode": "320583",
                "location": "120.956000,31.380000",
            }],
        }
    )
    result = AmapWebClient(api_key="test-key", transport=transport).search_verified_pois(
        city="昆山", kind="attraction"
    )
    assert result["pois"][0]["id"] == "p1"


def test_verified_poi_place_search_keeps_only_exact_name_candidates() -> None:
    base = {
        "type": "风景名胜", "cityname": "南京市", "adcode": "320102",
        "location": "118.858000,32.058000",
    }
    transport = FakeTransport({
        "status": "1",
        "pois": [
            {**base, "id": "other", "name": "中山陵停车场"},
            {**base, "id": "alias", "name": "中山陵景区"},
            {**base, "id": "match", "name": "中山陵"},
        ],
    })
    result = AmapWebClient(api_key="test-key", transport=transport).search_verified_pois(
        city="南京", kind="place", place_name="中山陵"
    )
    assert [poi["id"] for poi in result["pois"]] == ["match"]
    assert transport.calls[0][1]["keywords"] == "中山陵"


def test_verified_poi_place_search_accepts_one_exact_scenic_area_suffix() -> None:
    transport = FakeTransport({
        "status": "1", "pois": [{
            "id": "scenic", "name": "中山陵景区", "type": "风景名胜",
            "cityname": "南京市", "location": "118.854097,32.054508",
        }, {
            "id": "parking", "name": "中山陵停车场", "type": "交通设施服务",
            "cityname": "南京市", "location": "118.851346,32.048217",
        }],
    })
    result = AmapWebClient(api_key="test-key", transport=transport).search_verified_pois(
        city="南京", kind="place", place_name="中山陵"
    )
    assert [poi["id"] for poi in result["pois"]] == ["scenic"]


def test_verified_poi_tool_rejects_extra_provider_parameters_without_network() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-key", transport=transport))
    result = layer.execute(
        "keyword_search", city="南京", kind="food", offset=100, types="050000"
    )
    assert result.error_code == "invalid_tool_arguments"
    assert transport.calls == []


def test_verified_poi_tool_normalizes_valid_search() -> None:
    transport = FakeTransport({
        "status": "1",
        "pois": [{
            "id": "food-1", "name": "南京小吃店", "type": "餐饮服务",
            "cityname": "南京市", "adcode": "320102",
            "location": "118.796877,32.060255",
        }],
    })
    result = amap_layer(AmapWebClient(api_key="test-key", transport=transport)).execute(
        "keyword_search", city="南京", kind="food"
    )
    assert result.status == "completed"
    assert result.data["pois"][0]["id"] == "food-1"


def test_district_lookup_returns_exact_county_level_adcode() -> None:
    transport = FakeTransport({
        "status": "1", "infocode": "10000",
        "districts": [
            {"name": "昆山市", "level": "district", "adcode": "320583"},
            {"name": "昆明市", "level": "city", "adcode": "530100"},
        ],
    })
    code = AmapWebClient(api_key="test-key", transport=transport).resolve_adcode("昆山")
    assert code == "320583"
    assert transport.calls[0][1] == {
        "key": "test-key", "output": "json", "keywords": "昆山",
        "subdistrict": "0", "extensions": "base", "page": "1", "offset": "20",
    }


@pytest.mark.parametrize("city", ["", "火星市", "南京|苏州"])
def test_district_lookup_rejects_invalid_city_before_network(city: str) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        AmapWebClient(api_key="test-key", transport=transport).resolve_adcode(city)
    assert transport.calls == []


def test_district_lookup_rejects_ambiguous_or_malformed_response() -> None:
    response = {
        "status": "1",
        "districts": [
            {"name": "南京市", "level": "city", "adcode": "320100"},
            {"name": "南京市", "level": "city", "adcode": "999999"},
        ],
    }
    with pytest.raises(AmapApiError):
        AmapWebClient(api_key="test-key", transport=FakeTransport(response)).resolve_adcode(
            "南京"
        )


def test_distance_coordinates_sends_only_validated_coordinates_and_mode() -> None:
    transport = FakeTransport({
        "status": "1", "results": [{"distance": "18200"}]
    })
    client = AmapWebClient(api_key="test-key", transport=transport)
    assert client.measure_distance(
        "118.858000,32.058000", "118.805000,32.065000", mode=0
    ) == 18200
    assert transport.calls[0][1] == {
        "key": "test-key", "output": "json",
        "origins": "118.858000,32.058000",
        "destination": "118.805000,32.065000", "type": "0",
    }


@pytest.mark.parametrize(
    "origin,destination,mode",
    [
        ("中山陵", "118.805000,32.065000", 0),
        ("181,32", "118.805000,32.065000", 0),
        ("118.8580001,32", "118.805000,32.065000", 0),
        ("118.858000,32", "118.805000,32.065000", 2),
    ],
)
def test_distance_coordinates_rejects_invalid_arguments_without_network(
    origin: str, destination: str, mode: int
) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        AmapWebClient(api_key="test-key", transport=transport).measure_distance(
            origin, destination, mode=mode
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    "result",
    [{"distance": "-1"}, {"info": "UNKNOWN_ERROR"}, {"distance": "abc"}],
)
def test_distance_coordinates_rejects_bad_result(result: dict) -> None:
    transport = FakeTransport({"status": "1", "results": [result]})
    with pytest.raises(AmapApiError):
        AmapWebClient(api_key="test-key", transport=transport).measure_distance(
            "118.858000,32.058000", "118.805000,32.065000", mode=0
        )


def test_weather_adcode_rejects_city_name_before_network() -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        AmapWebClient(api_key="test-key", transport=transport).weather_adcode(
            "南京", forecast=True
        )
    assert transport.calls == []


def test_around_search_uses_agent_coordinates_and_maps_to_provider_location() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-amap-key", transport=transport))

    result = layer.execute(
        "around_search", coordinates="118.796877,32.060255", keywords="美食"
    )

    assert result.status == "completed"
    assert transport.calls[0][1]["location"] == "118.796877,32.060255"
    assert "coordinates" not in transport.calls[0][1]


def test_around_search_rejects_legacy_location_argument() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-amap-key", transport=transport))

    result = layer.execute("around_search", location="南京")

    assert result.error_code == "invalid_tool_arguments"
    assert transport.calls == []


def test_around_search_rejects_out_of_range_coordinates() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-amap-key", transport=transport))

    result = layer.execute("around_search", coordinates="181,91")

    assert result.error_code == "invalid_tool_arguments"
    assert result.details["invalid_fields"] == ["coordinates"]
    assert transport.calls == []


def test_weather_rejects_coordinates_in_city_field() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-amap-key", transport=transport))

    result = layer.execute("weather", city="118.796877,32.060255")

    assert result.error_code == "invalid_tool_arguments"
    assert transport.calls == []


def test_transit_route_requires_city_before_provider_call() -> None:
    transport = FakeTransport()
    layer = amap_layer(AmapWebClient(api_key="test-amap-key", transport=transport))

    result = layer.execute(
        "transit_route", origin="中山陵", destination="夫子庙"
    )

    assert result.error_code == "invalid_tool_arguments"
    assert result.details["missing_fields"] == ["city"]
    assert transport.calls == []


def test_agent_amap_schema_uses_canonical_fields_and_examples() -> None:
    layer = amap_layer(AmapWebClient(api_key="test-amap-key"))
    definition = layer.definition("around_search")
    schema = definition.input_model.model_json_schema()

    assert schema["additionalProperties"] is False
    assert "coordinates" in schema["required"]
    assert "location" not in schema["properties"]
    assert definition.examples == (
        {"coordinates": "118.796877,32.060255", "keywords": "美食"},
    )
    assert "geocode" not in {item.name for item in layer.definitions()}


def test_route_geocodes_place_names_before_calling_direction_api() -> None:
    calls: list[tuple[str, dict[str, str], float]] = []
    locations = iter(["118.796877,32.060255", "118.805000,32.065000"])

    def transport(
        url: str,
        params: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        calls.append((url, params, timeout))
        if url.endswith("/v3/geocode/geo"):
            return {
                "status": "1",
                "geocodes": [{"location": next(locations)}],
            }
        return {
            "status": "1",
            "route": {"paths": [{"distance": "1000", "duration": "600"}]},
        }

    client = AmapWebClient(api_key="test-amap-key", transport=transport)

    client.route("walking", "中山陵", "夫子庙", city="Nanjing")

    assert [call[0] for call in calls] == [
        "https://restapi.amap.com/v3/geocode/geo",
        "https://restapi.amap.com/v3/geocode/geo",
        "https://restapi.amap.com/v3/direction/walking",
    ]
    assert calls[-1][1]["origin"] == "118.796877,32.060255"
    assert calls[-1][1]["destination"] == "118.805000,32.065000"


def test_route_without_city_prefers_pois_in_the_same_area() -> None:
    calls: list[tuple[str, dict[str, str], float]] = []

    def transport(
        url: str,
        params: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        calls.append((url, params, timeout))
        if url.endswith("/v3/place/text"):
            if params["keywords"] == "中山陵":
                pois = [
                    {"location": "121.000000,31.000000", "adcode": "310000"},
                    {"location": "118.858000,32.058000", "adcode": "320100"},
                ]
            else:
                pois = [{"location": "118.805000,32.065000", "adcode": "320100"}]
            return {"status": "1", "pois": pois}
        if url.endswith("/v3/direction/driving"):
            return {
                "status": "1",
                "route": {"paths": [{"distance": "3000", "duration": "900"}]},
            }
        raise AssertionError(f"Unexpected AMap URL: {url}")

    client = AmapWebClient(api_key="test-amap-key", transport=transport)

    result = client.route("driving", "中山陵", "夫子庙")

    assert result["route"]["paths"][0]["distance"] == "3000"
    assert calls[-1][1]["origin"] == "118.858000,32.058000"
    assert calls[-1][1]["destination"] == "118.805000,32.065000"


def test_route_retries_with_poi_locations_after_engine_response_error() -> None:
    calls: list[tuple[str, dict[str, str], float]] = []
    route_attempts = 0

    def transport(
        url: str,
        params: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        nonlocal route_attempts
        calls.append((url, params, timeout))
        if url.endswith("/v3/geocode/geo"):
            location = (
                "118.796877,32.060255"
                if params["address"] == "origin"
                else "118.805000,32.065000"
            )
            return {"status": "1", "geocodes": [{"location": location}]}
        if url.endswith("/v3/direction/driving"):
            route_attempts += 1
            if route_attempts == 1:
                return {"status": "0", "info": "ENGINE_RESPONSE_DATA_ERROR"}
            return {
                "status": "1",
                "route": {"paths": [{"distance": "1000", "duration": "600"}]},
            }
        if url.endswith("/v3/place/text"):
            location = (
                "118.796877,32.060255"
                if params["keywords"] == "origin"
                else "118.805000,32.065000"
            )
            return {"status": "1", "pois": [{"location": location}]}
        raise AssertionError(f"Unexpected AMap URL: {url}")

    client = AmapWebClient(api_key="test-amap-key", transport=transport)

    result = client.route("driving", "origin", "destination", city="Nanjing")

    assert result["route"]["paths"][0]["distance"] == "1000"
    assert [call[0] for call in calls] == [
        "https://restapi.amap.com/v3/geocode/geo",
        "https://restapi.amap.com/v3/geocode/geo",
        "https://restapi.amap.com/v3/direction/driving",
        "https://restapi.amap.com/v3/place/text",
        "https://restapi.amap.com/v3/place/text",
        "https://restapi.amap.com/v3/direction/driving",
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


def test_amap_timeout_has_an_explicit_tool_error_code() -> None:
    def timeout_transport(
        _url: str,
        _params: dict[str, str],
        _timeout: float,
    ) -> dict[str, Any]:
        raise TimeoutError("upstream timed out")

    result = amap_layer(
        AmapWebClient(api_key="test-key", transport=timeout_transport)
    ).execute("weather", city="320100")

    assert result.status == "unavailable"
    assert result.error_code == "tool_timeout"
    assert result.message == "AMap Web API request timed out"


def test_amap_api_error_is_converted_to_failed_result() -> None:
    transport = FakeTransport({"status": "0", "info": "INVALID_USER_KEY"})

    result = amap_layer(
        AmapWebClient(api_key="test-key", transport=transport)
    ).execute("weather", city="320100")

    assert result.status == "failed"
    assert result.error_code == "tool_provider_error"
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
        if tool.information_need is not None:
            registry.register(tool)
    return ToolLayer(registry)
