"""Validate evaluation assets offline; this does not grade the Agent."""

import csv
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXPECTED_COUNTS = {
    "history": 8, "recommendation": 7, "weather": 5, "distance": 4,
    "budget": 3, "planning": 6, "memory": 5, "robustness": 2,
}
RULES = {
    "requirement_fields", "tool_scope", "answer_facts", "answer_includes_entities",
    "explicit_no_history", "no_rating_not_zero", "poi_answer", "clarification",
    "no_arbitrary_city_search", "preference_applied", "excluded_poi_refs",
    "weather_answer", "forecast_unavailable_explained", "distance_answer",
    "no_arbitrary_destination", "budget_consistency", "invalid_request_handled",
    "no_invalid_budget_call", "itinerary_constraints", "knowledge_citation",
    "no_cross_account_knowledge", "unknown_facts_disclosed", "preference_saved",
    "preference_retained", "compression_observed", "safe_tool_failure",
    "no_unhandled_exception", "quota_denied", "llm_call_count",
    "no_partial_assistant_saved",
}
EVIDENCE = {
    "answer", "requirement", "tool_trace", "answer_and_database",
    "answer_and_tool_results", "answer_and_memory", "itinerary_and_tool_results",
    "answer_and_knowledge_trace", "knowledge_trace", "database", "memory_trace",
    "answer_and_tool_trace", "http_and_events", "llm_trace",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(dataset: dict, fixtures: dict, rows: list[dict]) -> dict:
    require(dataset["version"] == fixtures["version"] == "core-v1", "version mismatch")
    require(fixtures["synthetic"] is True, "fixtures must be synthetic")
    require(fixtures["timezone"] == "Asia/Shanghai", "timezone mismatch")
    require(datetime.fromisoformat(fixtures["frozen_now"]).utcoffset().total_seconds() == 28800,
            "fixture clock must use UTC+08:00")
    require(dataset["repetitions"] == 3, "expected three repetitions")
    require(dataset["category_counts"] == EXPECTED_COUNTS, "category declaration mismatch")
    cases = dataset["cases"]
    require(Counter(case["category"] for case in cases) == EXPECTED_COUNTS,
            "expected 40 cases in agreed categories")
    ids = [case["id"] for case in cases]
    require(len(ids) == len(set(ids)), "duplicate case IDs")
    require(sum(case["suite"] == "fault" for case in cases) == 2, "expected two fault cases")
    accounts = fixtures["accounts"]
    fixture_refs = []
    for account in accounts.values():
        for trip in account["trips"]:
            fixture_refs.append(trip["ref"])
            start, end = date.fromisoformat(trip["start_date"]), date.fromisoformat(trip["end_date"])
            require(start <= end, "invalid trip date range")
            for record in trip["records"]:
                fixture_refs.append(record["ref"])
                require(start <= date.fromisoformat(record["date"]) <= end, "record outside trip")
                require(record["type"] in {"ATTRACTION", "FOOD"}, "invalid record type")
    pois = fixtures["tool_snapshots"]["pois"]
    poi_refs = {poi["ref"] for poi in pois}
    require(len(poi_refs) == len(pois), "duplicate POI reference")
    require(len({poi["poi_id"] for poi in pois}) == len(pois), "duplicate POI ID")
    require(len(fixture_refs) == len(set(fixture_refs)), "duplicate history reference")
    for poi in pois:
        longitude, latitude = map(float, poi["location"].split(","))
        require(-180 <= longitude <= 180 and -90 <= latitude <= 90, "invalid coordinates")
        require(poi["poi_id"].startswith("EVAL_"), "POI must be explicitly synthetic")
        require(poi["category"] in {"ATTRACTION", "FOOD"}, "invalid POI category")
        require(len(poi["adcode"]) == 6 and poi["adcode"].isdigit(), "invalid adcode")
    for collection in (fixtures["preferences"], fixtures["knowledge"], fixtures["histories"]):
        for entry in collection.values():
            require(entry["account"] in accounts, "fixture has unknown account")
    for history in fixtures["histories"].values():
        history_messages = history["messages"]
        require(len(history_messages) % 2 == 0, "history must contain full turns")
        for index, message in enumerate(history_messages):
            require(message["role"] == ("user" if index % 2 == 0 else "assistant"),
                    "history role order mismatch")
            require(0 < len(message["content"]) <= 2000, "invalid history message size")
        estimate = sum((len(message["content"].encode("utf-8")) + 1) // 2
                       for message in history_messages)
        require(estimate > 4200, "long history must exceed compression trigger")
    distance = fixtures["tool_snapshots"]["distance"]
    require({distance["origin_ref"], distance["destination_ref"]} <= poi_refs,
            "distance endpoints missing")
    require(all(value >= 0 for value in distance["values_meters"].values()), "negative distance")
    expected_rows = set()
    message_count = 0
    for case in cases:
        label = case["id"]
        require(case["title"].strip() and case["steps"], f"{label}: empty title or steps")
        require(case["suite"] in {"normal", "fault"}, f"{label}: invalid suite")
        require(case["tracks"] == ["A"], f"{label}: core-v1 is fixed-data track A")
        setup = case["setup"]
        require(setup["account"] in accounts, f"{label}: unknown account")
        for field, collection in (("preferences", "preferences"), ("knowledge", "knowledge")):
            require(set(setup.get(field, [])) <= set(fixtures[collection]),
                    f"{label}: unknown {field} reference")
        require(set(setup.get("poi_pool", [])) <= poi_refs, f"{label}: unknown POI pool")
        require("history" not in setup or setup["history"] in fixtures["histories"],
                f"{label}: unknown history")
        require("fault" not in setup or setup["fault"] in fixtures["faults"],
                f"{label}: unknown fault")
        require((case["suite"] == "fault") == ("fault" in setup), f"{label}: fault suite mismatch")
        conversations = {"main"}
        if "history" in setup:
            history = fixtures["histories"][setup["history"]]
            require(history["account"] == setup["account"], f"{label}: history owner mismatch")
            conversations.add(history["conversation"])
        for index, step in enumerate(case["steps"], start=1):
            require(step["account"] == setup["account"], f"{label}: step account mismatch")
            require(step["action"] in {"message", "new_conversation"}, f"{label}: unknown action")
            if step["action"] == "new_conversation":
                require(step["conversation"] not in conversations, f"{label}: conversation reused")
                conversations.add(step["conversation"])
                continue
            message_count += 1
            require(step["conversation"] in conversations, f"{label}: conversation not created")
            require(0 < len(step["message"].strip()) <= 2000, f"{label}: invalid message length")
            require(step["required"] and step["forbidden"], f"{label}: missing grading conditions")
            require(all(isinstance(item, str) and item.strip() for item in step["forbidden"]),
                    f"{label}: invalid forbidden behavior")
            for rule in step["required"]:
                require(rule["rule"] in RULES and "value" in rule, f"{label}: unknown rule")
                require(rule["evidence"] in EVIDENCE, f"{label}: unknown evidence")
                if rule["rule"] == "knowledge_citation":
                    require(rule["value"]["ref"] in fixtures["knowledge"], f"{label}: missing note")
                if rule["rule"] == "itinerary_constraints":
                    require(rule["value"]["days"] > 0, f"{label}: invalid itinerary days")
                    require(set(rule["value"].get("lunch_poi_refs", [])) <= poi_refs,
                            f"{label}: invalid lunch POI")
            for repeat in range(1, dataset["repetitions"] + 1):
                expected_rows.add(("A", label, str(repeat), str(index), case["category"],
                                   case["suite"], step["account"], step["conversation"]))
    identity = ("track", "case_id", "repeat", "step_index", "category", "suite", "account", "conversation")
    actual_rows = [tuple(row[key] for key in identity) for row in rows]
    require(len(actual_rows) == len(set(actual_rows)), "duplicate result template rows")
    require(set(actual_rows) == expected_rows, "result template does not match cases")
    require(all(row["status"] == "pending" for row in rows), "template must not contain grades")
    require(all(not value for row in rows for key, value in row.items()
                if key not in {*identity, "status"}), "template contains invented results")
    return {"cases": len(cases), "message_steps": message_count, "template_rows": len(rows)}


if __name__ == "__main__":
    dataset = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    fixtures = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    with (ROOT / "results-template.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    print(json.dumps(validate(dataset, fixtures, rows), ensure_ascii=False))
