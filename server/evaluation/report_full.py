"""Export auditable provisional metrics and a human-readable review queue."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from grading import grade_step, percentile, summarize
from run_pilot import save


def metrics(rows, cases, repetitions, fixtures):
    summary = summarize(rows, cases, repetitions)
    checks = defaultdict(Counter)
    for row in rows:
        for check in row["grade"]["checks"]:
            checks[check["rule"]][check["status"]] += 1
    summary["rules"] = {rule: dict(counts) for rule, counts in sorted(checks.items())}
    summary["responses"] = dict(Counter(row.get("final_event", "missing") for row in rows))
    stages = defaultdict(list)
    for row in rows:
        for event in row.get("stage_events", []):
            if event.get("event") == "stage_completed" and event.get("stage_duration_ms") is not None:
                stages[(event.get("stage_name"), event.get("stage_status"))].append(event["stage_duration_ms"])
    summary["stages"] = [{"stage": key[0], "status": key[1], "n": len(values), "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95)} for key, values in sorted(stages.items())]
    summary["failed_termination_ms"] = {"n": sum(row.get("final_event") != "completed" for row in rows),
        "p50": percentile([row.get("termination_ms") for row in rows if row.get("final_event") != "completed"], .5)}
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    expected_by_case = {case["id"]: sum(step["action"] == "message" for step in case["steps"]) * repetitions for case in cases}
    summary["stable_auto_passed"] = sum(
        len(by_case[case["id"]]) == expected_by_case[case["id"]]
        and all(row["grade"]["automatic_status"] == "pass" for row in by_case[case["id"]])
        for case in cases if case["suite"] == "normal")
    summary["stable_expected"] = sum(case["suite"] == "normal" for case in cases)
    summary["categories"] = {}
    for category in sorted({case["category"] for case in cases}):
        selected = [case for case in cases if case["category"] == category]
        subset = [row for row in rows if row["category"] == category]
        summary["categories"][category] = summarize(subset, selected, repetitions)["normal_tasks" if category != "robustness" else "fault_tasks"]
    known = {poi["poi_id"]: poi for poi in fixtures["tool_snapshots"]["pois"]}
    slots = Counter(required=0, valid=0)
    for case in cases:
        for repeat in range(1, repetitions + 1):
            for index, step in enumerate(case["steps"], 1):
                rules = [rule["value"] for rule in step.get("required", []) if rule["rule"] == "itinerary_constraints"]
                if not rules:
                    continue
                value = rules[0]
                row = next((row for row in by_case[case["id"]] if row["repeat"] == repeat and row["step"] == index), {})
                state = row.get("state") or {}
                days = (state.get("itinerary") or {}).get("days", [])
                collected = json.dumps((state.get("collected_info") or {}).get("pois", []))
                for day_index in range(value["days"]):
                    for period in value["periods"]:
                        slots["required"] += 1
                        items = days[day_index].get("items", []) if day_index < len(days) else []
                        wanted = "FOOD" if period in {"breakfast", "lunch", "dinner"} else "ATTRACTION"
                        slots["valid"] += any(item.get("period") == period and item.get("poi_id") in known and item["poi_id"] in collected
                            and known[item["poi_id"]]["city_code"] == value["city_code"] and known[item["poi_id"]]["category"] == wanted for item in items)
    summary["required_period_coverage"] = dict(slots)
    task_usage = defaultdict(int)
    for row in rows:
        task_usage[(row["case_id"], row["repeat"])] += (row.get("usage_delta") or {}).get("input_tokens", 0) + (row.get("usage_delta") or {}).get("output_tokens", 0)
    summary["tokens_per_task"] = {"n": len(task_usage), "p50": percentile(list(task_usage.values()), .5),
        "note": "按场景每次重复累计全部消息的实际usage；缺测任务未剔除，fallback单列。"}
    first_tools = defaultdict(Counter)
    missing_trace = 0
    for row in rows:
        seen = set()
        retries = {event.get("tool_name") for event in row.get("stage_events", []) if event.get("event") == "tool_argument_retry_started"}
        for run in row.get("tool_runs", []):
            args = run.get("arguments_json") or {}
            name = run["tool_name"]
            key = (name, args.get("kind"), args.get("place_name"), args.get("category"))
            if key in seen:
                continue
            seen.add(key)
            source = "llm_decision" if any(event.get("event") == "tool_started" and event.get("tool_name") == name for event in row.get("stage_events", [])) else "program_query"
            counts = first_tools[source]
            counts["attempts"] += 1
            legal = name not in retries and run.get("error_code") not in {"invalid_tool_arguments", "tool_not_found", "ValueError", "ValidationError"}
            counts["legal"] += legal
            result = run.get("result_json") or {}
            data = result.get("data", result)
            empty = not data or (isinstance(data, dict) and "pois" in data and not data["pois"])
            effective = legal and run.get("status") == "completed" and not empty
            effective &= not any(check["status"] == "fail" and check["rule"] == "tool_scope" for check in row["grade"]["checks"])
            counts["effective"] += effective
            if not effective:
                counts["no_data" if empty else "failed_or_wrong_scope"] += 1
        missing_trace += row.get("llm_http_calls", 0) > 0 and not row.get("tool_runs") and row.get("final_event") != "completed"
    summary["first_tools"] = {source: dict(counts) for source, counts in first_tools.items()}
    summary["first_tools_scope"] = {"grouping": "每消息按工具名+kind/place_name/category划分逻辑需求，只取首次落盘调用，参数重试事件使首次合法性失败。",
        "missing_trace_failed_messages": missing_trace, "limitation": "尚未形成可执行工具调用的LLM格式错误另记失败消息，不把它算成工具调用合法。有效性不等于最终回答正确。"}
    summary["unsupported_fact_ratio"] = {"status": "pending_human_fact_annotation"}
    return summary


def export(directory, regrade=False):
    if (directory / "review.csv").exists() or (directory / "review.md").exists():
        raise ValueError("Review files already exist; preserve human annotations")
    rows = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    dataset = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    fixtures = json.loads((directory / "fixtures.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    current_grader = hashlib.sha256(Path(__file__).with_name("grading.py").read_bytes()).hexdigest()
    if manifest["phase"] == "formal" and manifest["evaluation_sha256"].get("grading.py") != current_grader:
        raise ValueError("Formal grader differs from frozen manifest")
    selected = {case_id for _, case_id in manifest["order"]}
    cases = [case for case in dataset["cases"] if case["id"] in selected]
    lookup = {case["id"]: case for case in cases}
    if regrade:
        if manifest["phase"] != "trial":
            raise ValueError("Formal scores are frozen; do not regrade with changed rules")
        for row in rows:
            step = lookup[row["case_id"]]["steps"][row["step"] - 1]
            row["grade"] = grade_step(step, row, fixtures)
        save(directory / "regraded-results.json", rows)
    summary = metrics(rows, cases, manifest["repetitions"], fixtures)
    ledger = json.loads((directory / "usage.json").read_text(encoding="utf-8"))
    warmup = json.loads((directory / "warmup.json").read_text(encoding="utf-8")) if (directory / "warmup.json").exists() else {}
    summary["batch_ledger"] = ledger
    summary["warmup_usage"] = warmup.get("usage_delta", {})
    summary["ledger_reconciled"] = all(
        ledger[field] == sum((row.get("usage_delta") or {}).get(field, 0) for row in rows) + summary["warmup_usage"].get(field, 0)
        for field in ("input_tokens", "output_tokens", "fallback_tokens"))
    save(directory / "report-metrics.json", summary)
    lines = ["# Agent 全量评测人工复核", "", f"阶段：{manifest['phase']}；模型：`{manifest['model']}`；轨道A，固定合成工具数据。", "",
        "自动结果是硬规则初判；完整任务正确率待复核。每条回答结合results.json中同request_id的需求、工具及数据库证据阅读。", "",
        "优先复核自动失败、规划合理性、偏好是否落实、收藏引用和无依据事实。重复答案相同也保留各自请求ID与硬规则结果。", ""]
    ordered = sorted(rows, key=lambda row: (row["grade"]["automatic_status"] == "pass", row["case_id"], row["repeat"], row["step"]))
    equivalent = defaultdict(list)
    for row in ordered:
        # These are reading aids, not automatic shared verdicts: traces may differ.
        equivalent[(row["case_id"], row["step"], row.get("answer"), row["grade"]["automatic_status"])].append(
            {"repeat": row["repeat"], "request_id": row.get("request_id")})
    save(directory / "answer-groups.json", [{"case_id": key[0], "step": key[1], "answer": key[2], "automatic_status": key[3], "requests": requests}
        for key, requests in equivalent.items()])
    for row in ordered:
        failures = [check["rule"] for check in row["grade"]["checks"] if check["status"] == "fail"]
        lines.extend([f"## {row['case_id']} / 第{row['repeat']}轮 / 消息{row['step']}", "", f"请求：`{row.get('request_id')}`；结束：{row.get('final_event')}；自动：{row['grade']['automatic_status']}。", "",
            f"问题：{row['message']}", "", "回答：", "", row.get("answer") or f"未完成，事件见results.json：{row.get('error', '')}", "",
            "未满足的硬规则：" + ("、".join(failures) or "无"), "", "复核项：" + "；".join(row["grade"]["manual_review"]), "", "人工结论：待填写（pass/fail）；依据：待填写。", ""])
    (directory / "review.md").write_text("\n".join(lines), encoding="utf-8")
    fields = ["case_id", "repeat", "step", "request_id", "automatic_status", "human_status", "human_reason", "planning_score", "verifiable_facts", "unsupported_facts"]
    with (directory / "review.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in ordered:
            writer.writerow({**{key: row.get(key) for key in ("case_id", "repeat", "step", "request_id")}, "automatic_status": row["grade"]["automatic_status"], "human_status": "pending"})
    save(directory / "report-manifest.json", {"regraded": regrade, "grading_sha256": hashlib.sha256(Path(__file__).with_name("grading.py").read_bytes()).hexdigest(),
        "report_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "results_sha256": hashlib.sha256((directory / "results.json").read_bytes()).hexdigest()})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--regrade", action="store_true")
    args = parser.parse_args()
    print(json.dumps(export(args.directory, args.regrade), ensure_ascii=False, indent=2))
