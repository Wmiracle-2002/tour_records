import json
from pathlib import Path

import pytest

from fixtures_support import FullSnapshotProvider, seed_case
from grading import grade_step, summarize, percentile


ROOT = Path(__file__).parent
FIXTURES = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    import app.models
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def case(case_id):
    return next(case for case in CASES if case["id"] == case_id)


def row(case_id="H01", **updates):
    value = {"case_id": case_id, "repeat": 1, "step": 1, "suite": "normal", "category": "history",
             "final_event": "completed", "answer": "去过的城市：南京市、上海市、苏州市。",
             "requirements": [{"intent": "history_query", "city": None}],
             "tool_runs": [], "provider_calls": [], "state": {}, "database": {},
             "http_status": 200, "usage_delta": {"input_tokens": 10, "output_tokens": 5, "fallback_tokens": 0, "used": 15},
             "first_body_ms": 10, "completion_ms": 20, "model_outputs": []}
    value.update(updates)
    return value


def grade(value):
    return grade_step(case(value["case_id"])["steps"][value["step"]-1], value, FIXTURES)


def test_wrong_city_set_and_extra_food_fail_h01():
    assert grade(row())["automatic_status"] == "pass"
    assert grade(row(answer="去过的城市：南京市、哈尔滨市。"))["automatic_status"] == "fail"
    assert grade(row(answer="去过的城市：南京市、上海市、苏州市。鸭血粉丝汤。"))["automatic_status"] == "fail"


def test_unknown_rule_is_not_silently_accepted():
    with pytest.raises(ValueError, match="Unknown"):
        grade_step({"required": [{"rule": "invented", "value": True}], "forbidden": []}, row(), FIXTURES)


def test_missing_usage_does_not_become_zero_actual_tokens():
    result = summarize([row(usage_delta=None)], [case("H01")], repetitions=1)
    assert result["usage"]["missing_steps"] == 1
    assert result["usage"]["actual_tokens"] == 0


def test_incomplete_run_preserves_expected_denominator():
    result = summarize([], [case("H01"), case("H08")], repetitions=3)
    assert result["expected_steps"] == 6
    assert result["missing_steps"] == 6
    assert result["normal_tasks"]["expected"] == 6
    assert result["normal_tasks"]["auto_passed"] == 0


def test_nearest_rank_percentiles_and_failed_timing_excluded():
    assert percentile([10, 20, 30, 40], .50) == 20
    assert percentile([10, 20, 30, 40], .95) == 40
    assert percentile([], .95) is None
    result = summarize([row(), row(final_event="error", completion_ms=1, repeat=2)], [case("H01")], repetitions=2)
    assert result["performance"]["history"]["n"] == 1


def test_empty_or_wrong_city_itinerary_fails():
    value = row("P01", category="planning", answer="行程安排", requirements=[{"intent": "trip_planning", "city": "南京", "duration_days": 1}])
    assert grade(value)["automatic_status"] == "fail"
    value["state"] = {"itinerary": {"days": [{"day_number": 1, "items": [
        {"poi_id": "EVAL_X2", "poi_name": "上海餐饮反例", "period": "lunch", "activity_type": "FOOD"}
    ]}]}, "collected_info": {"pois": [{"poi_id": "EVAL_X2"}]}}
    assert grade(value)["automatic_status"] == "fail"


def test_forecast_date_and_distance_mode_must_match():
    value = row("W03", category="weather", answer="南京2026-10-08多云23℃", requirements=[{
        "intent": "weather_query", "start_date": "2026-10-09"}])
    assert grade(value)["automatic_status"] == "fail"
    value = row("D02", category="distance", answer="直线距离约5.2公里", requirements=[{
        "intent": "distance_query", "distance_mode": "walking"}])
    assert grade(value)["automatic_status"] == "fail"


def test_timeout_provider_records_failure_without_calling_network():
    provider = FullSnapshotProvider(FIXTURES)
    provider.configure({"fault": "poi_timeout"})
    with pytest.raises(TimeoutError):
        provider("https://restapi.amap.com/v3/place/text", {"key": "secret", "keywords": "美食", "city": "南京"}, 10)
    assert len(provider.calls) == 1
    assert provider.calls[0]["fault"] == "poi_timeout"
    assert "secret" not in json.dumps(provider.calls)


def test_district_and_wrong_city_candidates_reach_real_filter():
    provider = FullSnapshotProvider(FIXTURES)
    provider.configure({"poi_pool": ["C1", "C2", "X1"]})
    result = provider("https://restapi.amap.com/v3/place/text", {"city": "福州长乐", "keywords": "景点"}, 10)
    assert len(result["pois"]) == 3
    assert {poi["adcode"] for poi in result["pois"]} == {"350112", "350102"}


def test_account_setup_restores_notes_preferences_and_raw_messages(db_session):
    users, refs, conversations = seed_case(db_session, FIXTURES, case("P05"), "test-case", "unused", 400000)
    from app.models import KnowledgeEntry, UserPreference, ChatMessage
    from sqlalchemy import select
    assert db_session.get(KnowledgeEntry, refs["K1"]).user_id == users["alice"]
    assert db_session.get(KnowledgeEntry, refs["K2"]).user_id == users["bob"]
    users2, _, conversations2 = seed_case(db_session, FIXTURES, case("M05"), "test-long", "unused", 400000)
    messages = db_session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversations2["long"])).all()
    assert len(messages) == 26
    assert "2000" in messages[0].content
    assert users2["alice"] != users["alice"]
    users3, _, _ = seed_case(db_session, FIXTURES, case("R06"), "test-pref", "unused", 400000)
    preference = db_session.scalar(select(UserPreference).where(UserPreference.user_id == users3["alice"]))
    assert preference.content == "不吃辣"


def test_invalid_dates_prices_and_unknown_evidence_require_review():
    value = row("P06", category="planning", answer="中山陵门票999元，全天开放。")
    result = grade(value)
    assert result["automatic_status"] == "fail"
    assert result["manual_review"]


def test_quota_http_200_error_is_not_completed_and_upstream_calls_are_checked():
    value = row("E02", suite="fault", category="robustness", final_event="error", answer=None,
                events=[{"event": "error", "data": {"code": 429}}], llm_http_calls=0,
                database={"assistant_messages": []})
    assert grade(value)["automatic_status"] == "pass"
    value["llm_http_calls"] = 1
    assert grade(value)["automatic_status"] == "fail"


def test_all_declared_rules_are_exercised_and_missing_evidence_never_crashes():
    from validate_cases import RULES
    seen = set()
    for item in CASES:
        for index, step in enumerate(item["steps"], 1):
            if step["action"] != "message":
                continue
            result = grade_step(step, row(item["id"], step=index, suite=item["suite"], category=item["category"]), FIXTURES)
            assert result["automatic_status"] in {"pass", "fail"}
            seen.update(rule["rule"] for rule in step["required"])
    assert seen == RULES


def test_schedule_is_reproducible_and_keeps_every_repetition():
    from run_full import schedule
    first = [(repeat, case["id"]) for repeat, case in schedule(CASES, 3)]
    assert first == [(repeat, case["id"]) for repeat, case in schedule(CASES, 3)]
    assert len(set(first)) == 120


def test_overlong_itinerary_is_a_failure_instead_of_grader_exception():
    value = row("P02", state={"itinerary": {"days": [{"date": "2026-10-09", "items": []}] * 3}})
    assert grade(value)["automatic_status"] == "fail"


def test_snapshot_candidates_pass_through_actual_city_and_district_filter():
    from app.agent.tools.amap import AmapWebClient
    provider = FullSnapshotProvider(FIXTURES)
    provider.configure({"poi_pool": ["C1", "C2", "X1"]})
    result = AmapWebClient("unused", transport=provider).search_verified_pois("福州长乐", "attraction")
    assert {poi["id"] for poi in result["pois"]} == {"EVAL_C1", "EVAL_C2"}
    provider.configure({"poi_pool": ["F1", "F2", "X2"]})
    result = AmapWebClient("unused", transport=provider).search_verified_pois("南京", "food")
    assert {poi["id"] for poi in result["pois"]} == {"EVAL_F1", "EVAL_F2"}


def test_missing_planning_results_still_count_all_requested_slots():
    from report_full import metrics
    result = metrics([], [case("P02")], 3, FIXTURES)
    assert result["required_period_coverage"] == {"required": 36, "valid": 0}
    assert result["stable_auto_passed"] == 0


def test_global_budget_accounts_for_reservations_and_fallback():
    from run_full import batch_reservation_allowed
    usage = {"input_tokens": 100, "output_tokens": 20, "fallback_tokens": 30, "reserved_tokens": 50}
    assert batch_reservation_allowed(usage, 100, 300)
    assert not batch_reservation_allowed(usage, 101, 300)
    assert not batch_reservation_allowed(usage, 1, 199)


def test_zero_people_budget_answer_is_not_a_valid_input_rejection():
    value = row("B03", answer="人民币粗略估算：1人、3天，约1000元，实际价格请核实。")
    result = grade(value)
    assert next(check for check in result["checks"] if check["rule"] == "invalid_request_handled")["status"] == "fail"


def test_tool_retry_does_not_make_first_attempt_successful():
    from report_full import metrics
    value = row(tool_runs=[{"tool_name": "keyword_search", "arguments_json": {"kind": "food"}, "status": "completed", "result_json": {"pois": [{"id": "EVAL_F1"}]}}] * 2,
                stage_events=[{"event": "tool_started", "tool_name": "keyword_search"}, {"event": "tool_argument_retry_started", "tool_name": "keyword_search"}])
    value["grade"] = grade(value)
    result = metrics([value], [case("H01")], 1, FIXTURES)
    assert result["first_tools"]["llm_decision"]["attempts"] == 1
    assert result["first_tools"]["llm_decision"]["legal"] == 0
    assert result["first_tools"]["llm_decision"]["effective"] == 0


def test_sse_unknown_events_and_mismatched_request_ids_are_not_ignored():
    value = row(request_id="same", events=[{"event": "completed", "data": {"request_id": "same"}}])
    assert grade(value)["automatic_status"] == "pass"
    value["events"][0]["data"]["request_id"] = "other"
    assert grade(value)["automatic_status"] == "fail"
    value["events"] = [{"event": "unexpected", "data": {"request_id": "same"}}, {"event": "completed", "data": {"request_id": "same"}}]
    assert grade(value)["automatic_status"] == "fail"
