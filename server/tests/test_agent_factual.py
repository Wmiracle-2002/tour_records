from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.factual import FactualAnswerer
from app.agent.models import TravelRequirement
from app.agent.tools.amap import AmapWebClient


class FakeTransport:
    def __init__(self, pois: dict[str, list[dict]] | None = None) -> None:
        self.pois = pois or {}
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.weather_payload: dict[str, Any] = {}

    def __call__(self, url: str, params: dict[str, str], _timeout: float) -> dict:
        self.calls.append((url, params))
        if url.endswith("/v3/place/text"):
            return {"status": "1", "pois": self.pois.get(params["keywords"], [])}
        if url.endswith("/v3/distance"):
            return {"status": "1", "results": [{"distance": "18200"}]}
        if url.endswith("/v3/config/district"):
            return {
                "status": "1",
                "districts": [{
                    "name": "昆山市" if params["keywords"] == "昆山" else "南京市",
                    "level": "district" if params["keywords"] == "昆山" else "city",
                    "adcode": "320583" if params["keywords"] == "昆山" else "320100",
                }],
            }
        if url.endswith("/v3/weather/weatherInfo"):
            return self.weather_payload
        raise AssertionError(url)


def poi(poi_id: str, name: str, location: str) -> dict:
    return {
        "id": poi_id,
        "name": name,
        "type": "风景名胜",
        "cityname": "南京市",
        "adcode": "320102",
        "location": location,
    }


def answerer(transport: FakeTransport) -> FactualAnswerer:
    return FactualAnswerer(
        AmapWebClient(api_key="test-key", transport=transport),
        today_provider=lambda: date(2026, 9, 25),
    )


def test_distance_question_uses_two_verified_pois_and_straight_distance() -> None:
    transport = FakeTransport({
        "中山陵": [poi("p1", "中山陵", "118.858000,32.058000")],
        "夫子庙": [poi("p2", "夫子庙", "118.805000,32.065000")],
    })
    result = answerer(transport).answer(TravelRequirement(
        intent="distance_query", city="南京", origin="中山陵", destination="夫子庙"
    ))
    assert "直线距离" in result
    assert "18.2" in result
    assert [url.rsplit("/", 1)[-1] for url, _ in transport.calls] == [
        "text", "text", "distance"
    ]
    assert transport.calls[-1][1]["type"] == "0"


def test_distance_ambiguous_poi_does_not_measure() -> None:
    transport = FakeTransport({
        "中山陵": [
            poi("p1", "中山陵", "118.858000,32.058000"),
            poi("p2", "中山陵", "118.859000,32.058000"),
        ]
    })
    result = answerer(transport).answer(TravelRequirement(
        intent="distance_query", city="南京", origin="中山陵", destination="夫子庙"
    ))
    assert "不唯一" in result
    assert all(not url.endswith("/v3/distance") for url, _ in transport.calls)


def test_distance_missing_city_does_not_call_provider() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="distance_query", origin="中山陵", destination="夫子庙"
    ))
    assert "城市" in result
    assert transport.calls == []


def test_walking_distance_outside_supported_range_falls_back_to_labeled_straight_distance() -> None:
    transport = FakeTransport({
        "中山陵": [poi("p1", "中山陵", "118.858000,32.058000")],
        "夫子庙": [poi("p2", "夫子庙", "118.805000,32.065000")],
    })
    result = answerer(transport).answer(TravelRequirement(
        intent="distance_query", city="南京", origin="中山陵", destination="夫子庙",
        distance_mode="walking",
    ))
    assert "步行测距仅支持" in result
    assert "直线距离" in result
    assert transport.calls[-1][1]["type"] == "0"


def test_driving_distance_uses_driving_type() -> None:
    transport = FakeTransport({
        "中山陵": [poi("p1", "中山陵", "118.858000,32.058000")],
        "夫子庙": [poi("p2", "夫子庙", "118.805000,32.065000")],
    })
    result = answerer(transport).answer(TravelRequirement(
        intent="distance_query", city="南京", origin="中山陵", destination="夫子庙",
        distance_mode="driving",
    ))
    assert "驾车距离" in result
    assert transport.calls[-1][1]["type"] == "1"


def test_weather_forecast_matches_requested_date_not_first_cast() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1",
        "forecasts": [{
            "adcode": "320100", "city": "南京市", "reporttime": "2026-09-25 08:00:00",
            "casts": [
                {"date": "2026-09-25", "dayweather": "晴", "nightweather": "晴"},
                {"date": "2026-09-26", "dayweather": "雨", "nightweather": "阴"},
            ],
        }],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="明天",
        start_date="2026-09-26", weather_time_kind="forecast_date"
    ))
    assert "2026-09-26" in result
    assert "雨" in result
    assert "2026-09-25" not in result
    assert transport.calls[-1][1]["city"] == "320100"
    assert transport.calls[-1][1]["extensions"] == "all"


def test_weather_realtime_and_county_adcode() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1",
        "lives": [{
            "adcode": "320583", "city": "昆山市", "weather": "多云",
            "temperature": "24", "reporttime": "2026-09-25 10:00:00",
        }],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="昆山", weather_time_kind="realtime"
    ))
    assert "当前实况" in result
    assert "多云" in result
    assert transport.calls[-1][1]["city"] == "320583"
    assert transport.calls[-1][1]["extensions"] == "base"


def test_weather_tonight_uses_night_cast_not_realtime() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1",
        "forecasts": [{
            "adcode": "320100",
            "casts": [{
                "date": "2026-09-25",
                "dayweather": "晴", "nightweather": "雨",
            }],
        }],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="今晚",
        start_date="2026-09-25", weather_time_kind="forecast_date",
    ))
    assert "夜间：雨" in result
    assert "白天晴" not in result
    assert transport.calls[-1][1]["extensions"] == "all"


def test_weather_range_requires_every_returned_date() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1",
        "forecasts": [{
            "adcode": "320100",
            "casts": [{
                "date": "2026-09-25",
                "dayweather": "晴", "nightweather": "晴",
            }],
        }],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="从现在到明天",
        start_date="2026-09-25", end_date="2026-09-26",
        weather_time_kind="forecast_range",
    ))
    assert "不包含所问日期" in result
    assert "晴" not in result
    assert transport.calls[-1][1]["extensions"] == "all"


def test_weather_unknown_holiday_date_does_not_call_provider() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="中秋",
        weather_time_kind="forecast_date"
    ))
    assert "具体日期" in result
    assert transport.calls == []


def test_weather_future_word_cannot_be_mislabeled_realtime() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="明天",
        weather_time_kind="realtime",
    ))
    assert "具体日期" in result
    assert transport.calls == []


def test_weather_now_to_tomorrow_cannot_be_mislabeled_realtime() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="从现在到明天",
        start_date="2026-09-25", end_date="2026-09-26",
        weather_time_kind="realtime",
    ))
    assert "范围" in result or "日期" in result
    assert transport.calls == []


def test_weather_holiday_cannot_be_mislabeled_realtime() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="中秋",
        start_date="2026-09-25", weather_time_kind="realtime",
    ))
    assert "当前实况" not in result
    assert all(not url.endswith("/v3/weather/weatherInfo") for url, _ in transport.calls)


def test_weather_tomorrow_uses_server_date_when_model_date_is_wrong() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1",
        "forecasts": [{"adcode": "320100", "casts": [
            {"date": "2026-09-25", "dayweather": "晴", "nightweather": "晴"},
            {"date": "2026-09-26", "dayweather": "雨", "nightweather": "阴"},
        ]}],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="明天",
        start_date="2026-09-25", weather_time_kind="forecast_date",
    ))
    assert "2026-09-26" in result
    assert "雨" in result
    assert "2026-09-25" not in result


def test_weather_today_forecast_without_model_date() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1", "forecasts": [{"adcode": "320100", "casts": [
            {"date": "2026-09-25", "dayweather": "晴", "nightweather": "阴"},
        ]}],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="今天",
        weather_time_kind="forecast_date",
    ))
    assert "2026-09-25" in result
    assert transport.calls[-1][1]["extensions"] == "all"


def test_weather_now_to_tomorrow_range_uses_server_dates() -> None:
    transport = FakeTransport()
    transport.weather_payload = {
        "status": "1", "forecasts": [{"adcode": "320100", "casts": [
            {"date": "2026-09-25", "dayweather": "晴", "nightweather": "晴"},
            {"date": "2026-09-26", "dayweather": "雨", "nightweather": "阴"},
        ]}],
    }
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="从现在到明天",
        weather_time_kind="forecast_range",
    ))
    assert "2026-09-25" in result
    assert "2026-09-26" in result
    assert transport.calls[-1][1]["extensions"] == "all"


def test_weather_outside_forecast_range_does_not_call_provider() -> None:
    transport = FakeTransport()
    result = answerer(transport).answer(TravelRequirement(
        intent="weather_query", city="南京", date_expression="国庆",
        start_date="2026-10-01", weather_time_kind="forecast_date"
    ))
    assert "预报范围" in result
    assert transport.calls == []
