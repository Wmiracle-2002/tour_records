from app.agent.models import (
    BudgetInfo,
    DistanceInfo,
    POIInfo,
    RouteInfo,
    TravelHistoryInfo,
    WeatherInfo,
)
from app.agent.normalizer import (
    normalize_budget,
    normalize_distance,
    normalize_history,
    normalize_poi,
    normalize_route,
    normalize_tool_result,
    normalize_weather,
)
from app.agent.tools.layer import ToolResult


def test_normalize_amap_poi_response_to_business_models() -> None:
    result = normalize_poi(
        {
            "status": "1",
            "pois": [
                {
                    "id": "B0001",
                    "name": "中山陵",
                    "address": "石象路7号",
                    "location": "118.858,32.058",
                    "type": "风景名胜;公园广场",
                    "biz_ext": {"open_time": "08:30-17:00"},
                }
            ],
        }
    )

    assert result == [
        POIInfo(
            poi_id="B0001",
            name="中山陵",
            address="石象路7号",
            location="118.858,32.058",
            category="风景名胜;公园广场",
            opening_hours="08:30-17:00",
        )
    ]


def test_normalize_weather_forecast_and_temperature_boundaries() -> None:
    result = normalize_weather(
        {
            "status": "1",
            "city": "南京市",
            "casts": [
                {
                    "date": "2026-09-18",
                    "dayweather": "晴",
                    "nightweather": "多云",
                    "daytemp": "31",
                    "nighttemp": "22",
                }
            ],
        }
    )

    assert result == [
        WeatherInfo(
            location="南京市",
            date="2026-09-18",
            description="晴 / 多云",
            temperature_min=22.0,
            temperature_max=31.0,
        )
    ]


def test_normalize_live_weather_keeps_unknown_temperature_range_unknown() -> None:
    result = normalize_weather(
        {
            "status": "1",
            "lives": [
                {
                    "city": "南京市",
                    "weather": "晴",
                    "reporttime": "2026-09-18 10:00:00",
                }
            ],
        }
    )

    assert result[0] == WeatherInfo(
        location="南京市",
        date="2026-09-18",
        description="晴",
        temperature_min=None,
        temperature_max=None,
    )


def test_normalize_route_and_distance_converts_seconds_to_minutes() -> None:
    route = normalize_route(
        {
            "status": "1",
            "route": {"paths": [{"distance": "1000", "duration": "61"}]},
        },
        mode="walking",
        origin_id="origin",
        destination_id="destination",
    )
    distance = normalize_distance(
        {"status": "1", "results": [{"distance": "0"}]},
        origin_id="origin",
        destination_id="destination",
    )

    assert route == RouteInfo(
        origin_id="origin",
        destination_id="destination",
        mode="walking",
        distance_meters=1000,
        duration_minutes=2,
    )
    assert distance == DistanceInfo(
        origin_id="origin",
        destination_id="destination",
        distance_meters=0,
    )


def test_normalize_transit_route_reads_transit_option() -> None:
    result = normalize_route(
        {"route": {"transits": [{"distance": "2500", "duration": "3600"}]}},
        mode="transit",
        origin_id="origin",
        destination_id="destination",
    )

    assert result.duration_minutes == 60
    assert result.distance_meters == 2500


def test_normalize_history_collects_unique_cities_and_pois() -> None:
    result = normalize_history(
        [
            {
                "trip_id": 1,
                "city_name": "南京市",
                "records": [{"poi_id": "B1", "name": "中山陵"}],
            },
            {
                "trip_id": 2,
                "city_name": "南京市",
                "records": [{"poi_id": "B2", "name": "夫子庙"}],
            },
        ]
    )

    assert result == TravelHistoryInfo(
        trip_count=2,
        visited_cities=["南京市"],
        visited_names=["中山陵", "夫子庙"],
        visited_poi_ids=["B1", "B2"],
    )


def test_normalizers_keep_empty_data_as_successful_empty_results() -> None:
    assert normalize_poi([]) == []
    assert normalize_weather(None) == []
    assert normalize_history([]) == TravelHistoryInfo()
    assert normalize_budget({}) is None


def test_normalize_budget_accepts_existing_business_model() -> None:
    budget = BudgetInfo(estimated_min=80, estimated_max=120)

    assert normalize_budget(budget) is budget


def test_normalize_tool_result_preserves_status_and_maps_invalid_payload() -> None:
    unavailable = ToolResult.unavailable("服务暂不可用", error_code="provider_down")
    failed = ToolResult.failed("执行失败", error_code="provider_error")
    invalid = normalize_tool_result(
        ToolResult.completed({"pois": [{"name": "缺少必要字段"}]}),
        normalize_poi,
    )

    assert normalize_tool_result(unavailable, normalize_poi) == unavailable
    assert normalize_tool_result(failed, normalize_poi) == failed
    assert invalid.status == "failed"
    assert invalid.error_code == "invalid_tool_response"
