"""Evidence-based checks; subjective correctness remains a human decision."""

import math
import re
from collections import defaultdict

from validate_cases import RULES


def percentile(values, quantile):
    values = sorted(value for value in values if value is not None)
    return values[max(0, math.ceil(len(values) * quantile) - 1)] if values else None


def canonical(value):
    return value.removesuffix("市") if isinstance(value, str) else value


def serialized(value):
    import json
    return json.dumps(value, ensure_ascii=False)


def grade_step(step, row, fixtures):
    answer = row.get("answer") or ""
    requirement = (row.get("requirements") or [{}])[-1]
    state = row.get("state") or {}
    database = row.get("database") or {}
    calls = row.get("provider_calls") or []
    runs = row.get("tool_runs") or []
    pois = fixtures["tool_snapshots"]["pois"]
    known = {poi["poi_id"]: poi for poi in pois}
    refs = {poi["ref"]: poi for poi in pois}
    mentioned = [poi for poi in pois if poi["name"] in answer]
    checks = []
    review = list(step.get("forbidden", []))

    def check(rule, passed, detail=""):
        checks.append({"rule": rule, "status": "pass" if passed else "fail", "detail": detail})

    def search_calls():
        return [call for call in calls if call["path"] == "/v3/place/text"]

    def budget():
        value = (state.get("collected_info") or {}).get("budget")
        if value:
            return value
        for run in runs:
            if run.get("tool_name") == "estimate_budget":
                result = run.get("result_json") or {}
                return result.get("data", result)
        return {}

    def preference(content):
        return any(content in pref["content"] for pref in database.get("preferences", {}).get(step.get("account", "alice"), []))

    fault = row.get("suite") == "fault"
    if "events" in row:
        events = row["events"]
        allowed = {"started", "stage", "preview", "content", "completed", "error"}
        protocol_ok = all(event.get("event") in allowed for event in events)
        protocol_ok &= all(event.get("data", {}).get("request_id") == row["request_id"] for event in events) if row.get("request_id") else True
        protocol_ok &= sum(event.get("event") in {"completed", "error"} for event in events) == 1
        protocol_ok &= bool(events) and events[-1].get("event") in {"completed", "error"}
        check("sse_protocol", protocol_ok)
    if not fault:
        check("response_completed", row.get("final_event") == "completed" and bool(answer.strip()))
    for item in step.get("required", []):
        rule, value = item["rule"], item["value"]
        if rule not in RULES:
            raise ValueError(f"Unknown evaluation rule: {rule}")
        passed = False
        if rule == "requirement_fields":
            passed = bool(row.get("requirements")) and all(canonical(requirement.get(key)) == canonical(expected) for key, expected in value.items())
        elif rule == "answer_includes_entities":
            passed = all(entity in answer for entity in value)
        elif rule == "answer_facts":
            passed = True
            city_names = {trip["city"] for account in fixtures["accounts"].values() for trip in account["trips"]}
            if "cities" in value:
                actual = {city for city in city_names if canonical(city) in answer}
                passed = actual == set(value["cities"])
                # City-only questions must not silently include record lists.
                records = [record["name"] for account in fixtures["accounts"].values() for trip in account["trips"] for record in trip["records"]]
                passed &= not any(name in answer for name in records)
                passed &= not bool(re.search(r"[0-9一二三四五六七八九]+次", answer))
            if "city" in value:
                passed &= canonical(value["city"]) in answer and not any(canonical(city) in answer for city in city_names if city != value["city"])
            if "trip_count" in value:
                passed &= bool(re.search(r"(?:2|两|二)次", answer))
                for start, end in value["date_ranges"]:
                    for day in {start, end}:
                        month, number = map(int, day[5:].split("-"))
                        passed &= day in answer or f"{month}月{number}日" in answer
            if "budget" in value:
                passed &= str(value["budget"]) in answer and value["excluded"] in answer
                review.append("确认最早预算及排除条件的语义，不能仅凭关键词判定。")
        elif rule == "tool_scope":
            passed = True
            for key, expected in value.items():
                if key in {"city", "kind", "category"}:
                    arguments = [run.get("arguments_json") or run.get("arguments") or {} for run in runs]
                    arguments = [args for args in arguments if isinstance(args, dict) and key in args]
                    passed &= bool(arguments) and all(canonical(args[key]) == canonical(expected) for args in arguments)
                elif key == "adcode":
                    passed &= bool(search_calls()) and all(str(call["parameters"].get("city")) == expected for call in search_calls())
                elif key == "weather_extensions":
                    weather = [call for call in calls if call["path"] == "/v3/weather/weatherInfo"]
                    passed &= bool(weather) and all(call["parameters"].get("extensions") == expected for call in weather)
                elif key == "target_date":
                    passed &= requirement.get("start_date") == expected
                elif key in {"coordinate_endpoints", "mode"}:
                    distances = [call for call in calls if call["path"] == "/v3/distance"]
                    passed &= bool(distances)
                    if key == "mode":
                        passed &= all(str(call["parameters"].get("type")) == {"straight": "0", "driving": "1", "walking": "3"}[expected] for call in distances)
                    else:
                        passed &= all(re.fullmatch(r"-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?", str(call["parameters"].get(field, ""))) for call in distances for field in ("origins", "destination"))
                elif key == "forbid_geocode_for_poi_name":
                    passed &= not any("geocode" in call["path"] or "direction" in call["path"] for call in calls)
                else:
                    raise ValueError(f"Unknown tool scope: {key}")
        elif rule == "explicit_no_history":
            passed = bool(re.search(r"未|没有|没去|尚无|暂无", answer)) and not any(name in answer for name in ("中央大街", "中山陵", "玄武湖", "夫子庙"))
        elif rule == "no_rating_not_zero":
            passed = "评分" in answer and bool(re.search(r"未|没有|暂无|空|尚无", answer)) and not re.search(r"0\s*分|[1-5](?:\.\d)?\s*分", answer)
        elif rule == "poi_answer":
            passed = bool(mentioned) and bool(search_calls())
            kinds = value.get("kinds", [value.get("kind")])
            for kind in kinds:
                passed &= sum(poi["category"] == kind for poi in mentioned) >= value.get("min_each", value.get("min_items", 1))
            passed &= all(poi["category"] in kinds and all(poi.get(key) == value[key] for key in ("city_code", "adcode") if key in value) for poi in mentioned)
        elif rule in {"clarification", "invalid_request_handled"}:
            passed = bool(re.search(r"请|需要|补充|提供|几|哪个|不能|至少|有效|大于", answer))
            passed &= (bool(re.search(r"城市|地点|目的地|哪里|哪儿", answer)) if rule == "clarification" and value["missing"] == "city" else bool(re.search(r"终点|目的地|哪里|哪儿|到哪|人数|人", answer)))
            if rule == "invalid_request_handled":
                passed &= bool(re.search(r"人数.*(?:至少|不能|大于|有效)|(?:至少|不能|大于).*人|0\s*人.*(?:不|无效)|人数.*[？?]", answer))
            review.append("确认追问/拒绝明确且没有擅自补全输入。")
        elif rule == "no_arbitrary_city_search":
            passed = not search_calls()
        elif rule == "no_arbitrary_destination":
            passed = not any(call["path"] == "/v3/distance" for call in calls) and not requirement.get("destination")
        elif rule == "excluded_poi_refs":
            passed = not any(refs[ref]["name"] in answer for ref in value)
        elif rule == "weather_answer":
            passed = all(str(expected) in answer for key, expected in value.items() if key in {"weather", "temperature", "dayweather"})
            if "date" in value:
                month, day = map(int, value["date"][5:].split("-"))
                passed &= value["date"] in answer or f"{month}月{day}日" in answer
            weather_calls = [call for call in calls if call["path"] == "/v3/weather/weatherInfo"]
            passed &= bool(weather_calls)
            if value.get("kind") == "realtime":
                passed &= all(call["parameters"].get("extensions") == "base" for call in weather_calls)
        elif rule == "forecast_unavailable_explained":
            passed = bool(re.search(r"范围|暂|无法|不能|未覆盖|不在|超出|尚未", answer)) and not re.search(r"23\s*[℃度]|多云", answer)
        elif rule == "distance_answer":
            numbers = [(float(number) * (1000 if unit in {"公里", "千米", "km"} else 1)) for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(公里|千米|km|米)", answer)]
            passed = any(abs(number - value["meters"]) <= value["meters"] * value["relative_tolerance"] for number in numbers)
            passed &= {"straight": "直线", "walking": "步行", "driving": "驾车"}[value["mode"]] in answer or (value["mode"] == "driving" and "开车" in answer)
            passed &= any(call["path"] == "/v3/distance" and str(call["parameters"].get("type")) == {"straight": "0", "walking": "3", "driving": "1"}[value["mode"]] for call in calls)
        elif rule == "budget_consistency":
            data = budget()
            passed = bool(data) and bool(re.search(r"人民币|元", answer))
            if value.get("estimate_disclaimer"):
                passed &= bool(re.search(r"估|参考|非实时|大概|约", answer))
            if value.get("chinese_labels"):
                passed &= all(label in answer for label in ("住宿", "餐饮", "交通", "门票")) and not any(key in answer for key in ("accommodation", "poi_tickets", "transport"))
            for key in ("travelers", "days"):
                if key in value:
                    passed &= requirement.get("travelers" if key == "travelers" else "duration_days") == value[key]
            if "accommodation" in value:
                passed &= (data.get("breakdown") or {}).get("accommodation") == value["accommodation"]
        elif rule == "no_invalid_budget_call":
            passed = not any(run.get("tool_name") == "estimate_budget" for run in runs)
        elif rule == "itinerary_constraints":
            days = (state.get("itinerary") or {}).get("days", [])
            collected = serialized((state.get("collected_info") or {}).get("pois", []))
            passed = len(days) == value["days"]
            attractions = []
            for index, day in enumerate(days):
                items = day.get("items", [])
                passed &= bool(items)
                passed &= set(value.get("periods", [])) <= {item.get("period") for item in items}
                if "dates" in value:
                    passed &= index < len(value["dates"]) and day.get("date") == value["dates"][index]
                categories = []
                for entry in items:
                    poi = known.get(entry.get("poi_id"))
                    passed &= poi is not None and entry.get("poi_id", "MISSING") in collected
                    if not poi:
                        continue
                    passed &= poi["city_code"] == value["city_code"]
                    passed &= not (set(value.get("excluded_tags", [])) & set(poi.get("tags", [])))
                    categories.append(poi["category"])
                    if poi["category"] == "ATTRACTION":
                        attractions.append(poi["poi_id"])
                    if entry.get("period") == "lunch" and "lunch_poi_refs" in value:
                        passed &= poi["ref"] in value["lunch_poi_refs"]
                passed &= categories.count("FOOD") >= value.get("min_food_slots_per_day", 0)
                passed &= categories.count("ATTRACTION") >= value.get("min_attraction_slots_per_day", 0)
            if value.get("unique_attractions"):
                passed &= len(attractions) == len(set(attractions))
        elif rule in {"preference_saved", "preference_retained", "preference_applied"}:
            content = value["content"] if isinstance(value, dict) else value
            passed = preference(content)
            if rule == "preference_applied":
                passed &= content in serialized(requirement) or content in serialized(state.get("long_term_preferences", []))
                review.append("确认推荐体现不吃辣；不能把未知辣度声称为已验证。")
        elif rule == "compression_observed":
            passed = database.get("summary_count", 0) > 0 and database.get("raw_messages_retained") is True
        elif rule == "no_cross_account_knowledge":
            trace = row.get("knowledge_trace")
            passed = trace is not None and "BOB_PRIVATE" not in serialized(trace) + answer
            for trace_entry in trace or []:
                passed &= all(note.get("id") != database.get("knowledge_refs", {}).get("K2") for note in trace_entry.get("results", []))
        elif rule == "knowledge_citation":
            trace = row.get("knowledge_trace")
            passed = trace is not None
            review.append("确认采纳K1收藏时引用来源；未采纳则无需引用。")
        elif rule == "unknown_facts_disclosed":
            passed = bool(re.search(r"核实|未知|未确认|无法确认|待确认|以.*为准", answer)) and not ("999" in answer or "全天开放" in answer)
            review.append("确认票价与开放时间均没有被过时笔记当作已确认事实。")
        elif rule == "safe_tool_failure":
            passed = any(call.get("fault") == "poi_timeout" for call in calls) and len(search_calls()) <= 3 and not mentioned
            passed &= row.get("final_event") == "completed" and bool(re.search(r"失败|超时|暂|无法|未能", answer))
        elif rule == "no_unhandled_exception":
            passed = row.get("final_event") in {"completed", "error"} and "Traceback" not in answer
        elif rule == "quota_denied":
            passed = row.get("http_status") == 429 or any(str(event.get("data", {}).get("code")) == "429" for event in row.get("events", []))
        elif rule == "llm_call_count":
            passed = row.get("llm_http_calls") == value
        elif rule == "no_partial_assistant_saved":
            passed = "assistant_messages" in database and not any(message.get("status") == "completed" or message.get("content") for message in database["assistant_messages"])
        else:
            raise ValueError(f"Unknown evaluation implementation: {rule}")
        check(rule, bool(passed), f"expected={serialized(value)}")
    return {"automatic_status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
            "checks": checks, "manual_review": list(dict.fromkeys(review)), "human_status": "pending"}


def summarize(rows, cases, repetitions):
    expected = {(case["id"], repeat, index) for case in cases for repeat in range(1, repetitions + 1) for index, step in enumerate(case["steps"], 1) if step["action"] == "message"}
    observed = {(row["case_id"], row["repeat"], row["step"]): row for row in rows}
    groups = defaultdict(list)
    for row in rows:
        if row.get("final_event") == "completed" and row.get("completion_ms") is not None:
            groups[row["category"]].append(row)
    performance = {category: {"n": len(items), **{f"{field}_p{int(q*100)}": percentile([item.get(field) for item in items], q) for field in ("first_body_ms", "completion_ms") for q in (.5, .95)}} for category, items in groups.items()}
    usage = {"actual_tokens": sum((row.get("usage_delta") or {}).get("input_tokens", 0) + (row.get("usage_delta") or {}).get("output_tokens", 0) for row in rows),
             "fallback_tokens": sum((row.get("usage_delta") or {}).get("fallback_tokens", 0) for row in rows),
             "missing_steps": sum(row.get("usage_delta") is None for row in rows)}
    tasks = {}
    for suite in ("normal", "fault"):
        selected = [case for case in cases if case["suite"] == suite]
        passed = 0
        for case in selected:
            for repeat in range(1, repetitions + 1):
                keys = [(case["id"], repeat, index) for index, step in enumerate(case["steps"], 1) if step["action"] == "message"]
                passed += all(key in observed and observed[key].get("grade", {}).get("automatic_status") == "pass" for key in keys)
        tasks[f"{suite}_tasks"] = {"expected": len(selected) * repetitions, "auto_passed": passed, "human_confirmed": 0}
    return {"expected_steps": len(expected), "observed_steps": len(observed), "missing_steps": len(expected - observed.keys()),
            **tasks, "performance": performance, "usage": usage, "accuracy_status": "pending_human_review"}
