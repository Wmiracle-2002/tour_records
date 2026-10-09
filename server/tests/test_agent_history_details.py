from datetime import date
from decimal import Decimal

import pytest

from app.agent.models import CollectedInfo, InformationStatus, TravelRequirement
from app.agent.normalizer import normalize_history, normalize_records
from app.agent.response import FinalResponseGenerator
from app.agent.tools.internal import RecordSearchItem, TripInfo


def answer(history, **fields):
    return FinalResponseGenerator().generate(
        TravelRequirement(intent="history_query", **fields),
        CollectedInfo(history=history), InformationStatus(),
    )


def test_h06_counts_trips_and_keeps_original_ranges_not_record_dates():
    history = normalize_history([
        {"city_name": "南京市", "start_date": "2026-08-01", "end_date": "2026-08-02",
         "records": [{"name": "中山陵", "date": "2026-08-01"}, {"name": "夫子庙"}]},
        {"city_name": "南京市", "start_date": "2026-09-20", "end_date": "2026-09-20",
         "records": []},
        {"city_name": "上海市", "start_date": "2026-09-01", "end_date": "2026-09-04"},
    ])
    text = answer(history, city="南京", history_view="trips")
    assert "2次" in text
    for value in ("2026-08-01", "2026-08-02", "2026-09-20"):
        assert value in text
    assert "上海" not in text and "2026-09-04" not in text
    assert history.trip_count == 3


def test_history_accepts_tool_models_with_date_and_decimal_values():
    record = RecordSearchItem(
        record_id=1, trip_id=1, city_name="南京市", category="ATTRACTION",
        name="夫子庙", date=date(2026, 8, 2), rating=Decimal("4.5"),
    )
    history = normalize_history([TripInfo(
        trip_id=1, city_code="320100", city_name="南京市",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), records=[record],
    )])
    assert history.trip_periods_by_city == {"南京市": [("2026-08-01", "2026-08-02")]}
    assert history.ratings_by_city == {"南京市": {"夫子庙": [4.5]}}
    assert normalize_records([record]).ratings_by_city == history.ratings_by_city


@pytest.mark.parametrize("normalizer", [normalize_history, normalize_records])
def test_h07_null_rating_is_explicit_and_only_exact_name_is_answered(normalizer):
    records = [
        {"city_name": "南京市", "name": "夫子庙", "category": "ATTRACTION", "rating": None},
        {"city_name": "南京市", "name": "夫子庙小吃", "category": "FOOD", "rating": 5},
        {"city_name": "南京市", "name": "中山陵", "category": "ATTRACTION", "rating": 4.5},
    ]
    raw = [{"city_name": "南京市", "records": records}] if normalizer is normalize_history else records
    text = answer(normalizer(raw), history_view="ratings", history_record_name="夫子庙")
    assert "夫子庙" in text and "未评分" in text
    assert all(value not in text for value in ("0分", "5分", "4.5", "中山陵", "夫子庙小吃"))


@pytest.mark.parametrize("normalizer", [normalize_history, normalize_records])
def test_repeated_ratings_are_kept_in_order_and_isolated_by_city(normalizer):
    records = [
        {"city_name": "南京市", "name": "同名店", "rating": rating}
        for rating in (Decimal("4.5"), None, Decimal("4.5"), "", 0)
    ] + [{"city_name": "苏州市", "name": "同名店", "rating": 2}]
    raw = [
        {"city_name": "南京市", "records": records[:-1]},
        {"city_name": "苏州市", "records": records[-1:]},
    ] if normalizer is normalize_history else {"records": records}
    history = normalizer(raw)
    assert history.ratings_by_city == {
        "南京市": {"同名店": [4.5, None, 4.5, None, 0.0]},
        "苏州市": {"同名店": [2.0]},
    }
    text = answer(history, city="南京", history_view="ratings", history_record_name="同名店")
    assert text.count("4.5分") == 2 and text.count("未评分") == 2
    assert "0分" in text
    assert "苏州" not in text and "2分" not in text


def test_identical_trip_periods_still_count_as_separate_trips():
    history = normalize_history([
        {"city_name": "南京市", "start_date": "2026-09-20", "end_date": "2026-09-20"},
        {"city_name": "南京市", "start_date": "2026-09-20", "end_date": "2026-09-20"},
    ])
    text = answer(history, history_view="trips")
    assert "2次" in text and text.count("2026-09-20") == 4


def test_missing_trip_dates_are_not_invented_or_counted_as_zero():
    text = answer(normalize_history([{"city_name": "南京市"}]), history_view="trips")
    assert "暂无可核实" in text and "0次" not in text


@pytest.mark.parametrize("start,end", [
    (date(2024, 2, 29), date(2024, 3, 1)),
    (date(2025, 12, 31), date(2026, 1, 1)),
    (date(2026, 9, 20), None),
])
def test_date_boundaries_and_explicit_missing_endpoint_are_preserved(start, end):
    history = normalize_history([{
        "city_name": "南京市", "start_date": start, "end_date": end,
    }])
    text = answer(history, history_view="trips")
    assert "1次" in text and start.isoformat() in text
    if end is None:
        assert "日期未知" in text
    else:
        assert end.isoformat() in text


@pytest.mark.parametrize("view", ["places", "trips", "ratings"])
def test_empty_history_does_not_fabricate_results(view):
    text = answer(normalize_history([]), history_view=view)
    assert "没有找到" in text and "0分" not in text


def test_no_exact_entity_match_does_not_answer_other_ratings():
    history = normalize_records([{"city_name": "南京市", "name": "夫子庙小吃", "rating": 5}])
    text = answer(history, history_view="ratings", history_record_name="夫子庙")
    assert "没有找到" in text and "5分" not in text


def test_missing_city_does_not_leak_rating_from_another_city():
    history = normalize_records([{"city_name": "苏州市", "name": "同名店", "rating": 2}])
    text = answer(history, city="南京", history_view="ratings", history_record_name="同名店")
    assert "没有找到" in text and "2分" not in text


def test_unspecified_entity_lists_ratings_without_dropping_nulls():
    history = normalize_records([{"city_name": "南京市", "name": "夫子庙", "rating": None}])
    text = answer(history, history_view="ratings")
    assert "夫子庙" in text and "未评分" in text


def test_places_default_preserves_city_attraction_food_groups():
    history = normalize_history([{"city_name": "南京市", "records": [
        {"category": "ATTRACTION", "name": "夫子庙"},
        {"category": "FOOD", "name": "鸭血粉丝汤"},
    ]}])
    assert answer(history, history_category="BOTH") == (
        "去过的城市1：南京市，去过的地点：夫子庙，吃过的美食：鸭血粉丝汤。"
    )


def test_memory_query_is_accepted_by_shared_requirement_contract():
    assert TravelRequirement(intent="memory_query").intent == "memory_query"
