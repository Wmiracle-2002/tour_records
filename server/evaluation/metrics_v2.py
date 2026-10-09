"""Read-only sidecar: goal review, hard-rule proxies and process diagnostics."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from grading import grade_step, percentile


def ratio(passed, expected):
    return {"passed": passed, "expected": expected, "rate": passed / expected if expected else None}


def bounds(statuses):
    counts = Counter(statuses)
    n = len(statuses)
    return {"expected": n, **{s: counts[s] for s in ("pass", "fail", "pending")},
            "lower": counts["pass"] / n if n else None,
            "upper": (counts["pass"] + counts["pending"]) / n if n else None,
            "rate": counts["pass"] / n if n and not counts["pending"] else None}


def all_status(statuses):
    return "fail" if "fail" in statuses else "pending" if "pending" in statuses else "pass"


def key(row):
    return row["case_id"], row["repeat"], row["step"]


def terminated(row):
    events = row.get("events") or []
    terminals = [event for event in events if event.get("event") in {"completed", "error"}]
    valid = (len(terminals) == 1 and events[-1] == terminals[0]
             and row.get("final_event") == terminals[0]["event"])
    if row.get("request_id"):
        valid &= all(event.get("data", {}).get("request_id") == row["request_id"] for event in events)
    return valid


def distribution(values, expected):
    values = [v for v in values if v is not None]
    return {"observed": len(values), "expected": expected,
            "total": sum(values) if values else None,
            "p50": percentile(values, .5), "p95": percentile(values, .95)}


def build_report(rows, cases, manifest, fixtures=None, reviews=()):
    repetitions = manifest.get("repetitions")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("invalid repetitions")
    lookup = {case["id"]: case for case in cases}
    if len(lookup) != len(cases) or not cases:
        raise ValueError("invalid case ids")
    if "order" in manifest:
        order = [tuple(item) for item in manifest["order"]]
        selected = {case_id for _, case_id in order}
        wanted = {(case_id, repeat) for case_id in selected for repeat in range(1, repetitions + 1)}
        if not selected or not selected <= lookup.keys() or len(order) != len(set(order)) or {
                (case_id, repeat) for repeat, case_id in order} != wanted:
            raise ValueError("invalid manifest order")
        cases = [case for case in cases if case["id"] in selected]
    expected = {}
    for case in cases:
        messages = [(i, step) for i, step in enumerate(case["steps"], 1) if step["action"] == "message"]
        if not messages or case["suite"] not in {"normal", "fault"}:
            raise ValueError("invalid task/suite")
        for repeat in range(1, repetitions + 1):
            for i, step in messages:
                expected[case["id"], repeat, i] = (case, step)
    observed = {}
    for row in rows:
        k = key(row)
        if k not in expected or k in observed or row.get("suite") != expected[k][0]["suite"]:
            raise ValueError("invalid result key/suite or duplicate")
        observed[k] = row
    adjudications = {}
    for review in reviews:
        k = key(review)
        if k not in observed or k in adjudications:
            raise ValueError("invalid review key or duplicate")
        for field in ("goal_status", "forbidden_status"):
            if review.get(field) not in {"pass", "fail", "pending"}:
                raise ValueError("invalid review status")
        if any(review[field] != "pending" for field in ("goal_status", "forbidden_status")):
            if not all(isinstance(review.get(field), str) and review[field].strip()
                       for field in ("reason", "answer_evidence", "state_evidence")):
                raise ValueError("review requires answer and business-state evidence")
        adjudications[k] = review

    steps, diagnostics, tools = [], defaultdict(Counter), []
    intents, slots, constraints = [], [], []
    grouped = defaultdict(list)
    for k, (case, step) in expected.items():
        row = observed.get(k)
        review = adjudications.get(k, {})
        checks = (grade_step(step, row, fixtures) if fixtures is not None and row else
                  (row or {}).get("grade", {})).get("checks", [])
        required = {item["rule"] for item in step.get("required", [])}
        requirement = ((row or {}).get("requirements") or [{}])[-1]
        for rule in step.get("required", []):
            if rule["rule"] != "requirement_fields":
                continue
            for field, gold in rule["value"].items():
                actual = requirement.get(field)
                if field == "city":
                    gold = gold.removesuffix("市") if isinstance(gold, str) else gold
                    actual = actual.removesuffix("市") if isinstance(actual, str) else actual
                matched = bool(row and row.get("requirements") and actual == gold)
                (intents if field == "intent" else slots).append(matched)
        seen = {check["rule"] for check in checks}
        candidate = bool(row and checks and required <= seen and all(c["status"] == "pass" for c in checks))
        for check in checks:
            diagnostics[check["rule"]][check["status"]] += 1
        for rule in required - seen:
            diagnostics[rule]["missing"] += 1
        if "itinerary_constraints" in required:
            constraints.append(any(c["rule"] == "itinerary_constraints" and c["status"] == "pass" for c in checks))
        goal = review.get("goal_status", "pending") if row else "fail"
        forbidden = review.get("forbidden_status", "pending") if step.get("forbidden") else "pass"
        status = all_status([goal, forbidden]) if row else "fail"
        item = {"case_id": k[0], "repeat": k[1], "step": k[2], "suite": case["suite"], "category": case["category"],
                "request_id": (row or {}).get("request_id"), "missing": row is None,
                "auto_candidate": candidate, "goal_status": goal, "forbidden_status": forbidden,
                "success_status": status, "terminated": bool(row and terminated(row)),
                "safe_degradation_applicable": "safe_tool_failure" in required,
                "safe_degradation_auto": any(c["rule"] == "safe_tool_failure" and c["status"] == "pass" for c in checks),
                "diagnostics": checks, "review": review}
        steps.append(item)
        grouped[k[:2]].append(item)
        paths = step.get("reference_tool_paths")
        if paths is not None:
            if not isinstance(paths, list) or not paths or not all(isinstance(p, list) for p in paths):
                raise ValueError("invalid reference_tool_paths")
            actual = [{"tool_name": run.get("tool_name"),
                       "arguments": run.get("arguments_json", run.get("arguments"))}
                      for run in (row or {}).get("tool_runs", [])]
            tools.append(bool(row is not None and "tool_runs" in row and actual in paths))
    tasks = [{"case_id": k[0], "repeat": k[1], "suite": items[0]["suite"], "category": items[0]["category"],
              "auto_candidate": all(item["auto_candidate"] for item in items),
              "success_status": all_status([item["success_status"] for item in items])}
             for k, items in grouped.items()]
    suites = {}
    for suite in ("normal", "fault"):
        selected = [task for task in tasks if task["suite"] == suite]
        case_ids = {task["case_id"] for task in selected}
        all3 = sum(all(task["auto_candidate"] for task in selected if task["case_id"] == cid) for cid in case_ids)
        suites[suite] = {"success": bounds([task["success_status"] for task in selected]),
                         "auto_candidate": ratio(sum(task["auto_candidate"] for task in selected), len(selected)),
                         "observed_all_3_auto": ratio(all3, len(case_ids)) if repetitions == 3 else ratio(0, 0),
                         "observed_all_3_success": bounds([
                             all_status([task["success_status"] for task in selected if task["case_id"] == cid])
                             for cid in sorted(case_ids)]) if repetitions == 3 else bounds([])}
    degraded = [step for step in steps if step["safe_degradation_applicable"]]
    n = len(expected)
    efficiency = {}
    for field in ("llm_http_calls", "completion_ms", "first_body_ms", "termination_ms"):
        efficiency[field] = distribution([row.get(field) for row in rows], n)
    efficiency["tool_calls"] = distribution([len(row["tool_runs"]) if "tool_runs" in row else None for row in rows], n)
    tokens = []
    fallback = []
    for row in rows:
        usage = row.get("usage_delta") or {}
        tokens.append(usage["input_tokens"] + usage["output_tokens"]
                      if all(usage.get(f) is not None for f in ("input_tokens", "output_tokens")) else None)
        fallback.append(usage.get("fallback_tokens"))
    efficiency["actual_tokens"] = distribution(tokens, n)
    efficiency["fallback_tokens"] = distribution(fallback, n)
    for name, field in (("tokens_per_task", "tokens"), ("calls_per_task", "llm_http_calls"),
                        ("tool_calls_per_task", "tool_calls")):
        totals = []
        for task_key, items in grouped.items():
            values = []
            for item in items:
                row = observed.get((task_key[0], task_key[1], item["step"]), {})
                usage = row.get("usage_delta") or {}
                if field == "tokens":
                    value = (usage["input_tokens"] + usage["output_tokens"]
                             if all(usage.get(f) is not None for f in ("input_tokens", "output_tokens")) else None)
                elif field == "tool_calls":
                    value = len(row["tool_runs"]) if "tool_runs" in row else None
                else:
                    value = row.get(field)
                values.append(value)
            totals.append(sum(values) if all(v is not None for v in values) else None)
        efficiency[name] = distribution(totals, len(tasks))
    unavailable = lambda reason: {"rate": None, "reason": reason}
    tool_accuracy = {**ratio(sum(tools), len(tools)), "eligible_steps": n,
                     "definition": "参考工具及参数的完整有序轨迹匹配；接受显式列出的等价流程；非参数合法率"}
    faithfulness = unavailable("缺少逐事实支持标注")
    context_precision = unavailable("缺少排序检索结果的相关性标注")
    modules = {"requirement_understanding": {
        "intent_accuracy": ratio(sum(intents), len(intents)),
        "slot_exact_accuracy": ratio(sum(slots), len(slots)),
        "slot_precision": unavailable("未标注全部gold槽位及多余字段false positive规则"),
        "slot_recall": unavailable("未标注完整gold槽位集合"),
        "slot_f1": unavailable("只对显式标注字段计Slot Exact Accuracy，不伪造F1")},
        "tool_use": {"tool_call_accuracy": tool_accuracy},
        "planning": {"constraint_satisfaction_rate": {**ratio(sum(constraints), len(constraints)),
            "unit": "每个itinerary_constraints规则包全满足计1，不是逐时段覆盖率"},
            "human_reasonableness": unavailable("尚无独立人工合理性标注")},
        "memory": {"fact_exact_match": unavailable("缺少独立完整gold事实与答案事实抽取标注"),
                   "fact_f1": unavailable("缺少gold/predicted事实集合"),
                   "recall_at_k": unavailable("缺少相关记忆标注与固定K")},
        "knowledge_base": {"context_precision": context_precision,
                           "context_recall": unavailable("缺少参考答案与检索覆盖事实标注"),
                           "faithfulness": faithfulness,
                           "answer_relevancy": unavailable("未执行独立相关性评测")}}
    for category in sorted({case["category"] for case in cases}):
        modules.setdefault(category, {})["task_success_rate"] = bounds([
            task["success_status"] for task in tasks if task["category"] == category])
    return {"version": "metrics-v2", "validity": "unverified_in_memory", "expected_steps": n,
            "observed_steps": len(rows), "missing_steps": n - len(rows), "suites": suites,
            "termination": ratio(sum(s["terminated"] for s in steps), n),
            "safe_degradation": {"auto_proxy": ratio(sum(s["safe_degradation_auto"] for s in degraded), len(degraded)),
                                 "confirmed": bounds([s["success_status"] for s in degraded])},
            "modules": modules, "tool_call_accuracy": tool_accuracy,
            "rag_faithfulness": faithfulness, "rag_context_precision": context_precision,
            "efficiency": efficiency, "diagnostics": {k: dict(v) for k, v in sorted(diagnostics.items())},
            "tasks": tasks, "steps": steps,
            "proxy_basis": "recomputed_current_grading" if fixtures is not None else "stored_checks_only"}


def markdown(report):
    def display(value):
        return "N/A" if value is None else f"{value:.1%}"

    lines = ["# Agent 评测指标 v2", "", "主指标 Task Success Rate / goal achievement：核对最终答案与业务状态证据。",
             "人工未复核与禁止行为未确认均保留 pending；上下界表示未知裁决范围，不是置信区间。", "",
             "| 轨道 | 任务分母 | 确认成功/失败/pending | 最终成功率 | 下界～上界 | 自动硬规则候选 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for suite, value in report["suites"].items():
        s, a = value["success"], value["auto_candidate"]
        lines.append(f"| {suite} | {s['expected']} | {s['pass']}/{s['fail']}/{s['pending']} | {display(s['rate'])} | "
                     f"{display(s['lower'])}～{display(s['upper'])} | {a['passed']}/{a['expected']} ({display(a['rate'])}) |")
    lines.extend(["", f"消息覆盖：{report['observed_steps']}/{report['expected_steps']}；缺测 {report['missing_steps']}（计失败）。",
                  f"完整终止率（包括显式error，不表示正确）：{display(report['termination']['rate'])}。",
                  f"安全降级自动代理：{display(report['safe_degradation']['auto_proxy']['rate'])}；确认情况："
                  + json.dumps(report["safe_degradation"]["confirmed"], ensure_ascii=False), ""])
    for suite, value in report["suites"].items():
        a = value["observed_all_3_auto"]
        lines.append(f"{suite} observed all-3 自动通过：{a['passed']}/{a['expected']} ({display(a['rate'])})。")
        final = value["observed_all_3_success"]
        lines.append(f"最终裁决三轮全成功：{display(final['rate'])}；下界～上界 "
                     f"{display(final['lower'])}～{display(final['upper'])}，pending={final['pending']}。")
    lines.extend(["这是实测同题三轮全通过比例；不是通用 τ-bench pass^k 估计，也不是最终质量通过率。", "",
                  f"工具调用准确性（参考完整轨迹精确匹配）：{display(report['tool_call_accuracy']['rate'])}；"
                  f"有参考分母 {report['tool_call_accuracy']['expected']}/{report['tool_call_accuracy']['eligible_steps']}。",
                  "RAG faithfulness / context precision：N/A；未提供逐事实及检索相关性标注。", "",
                  "## 各模块指标", "", "| 模块 | 常见指标 | 结果 | 分母/限制 |", "| --- | --- | --- | --- |"])
    for module, metrics in report["modules"].items():
        for name, value in metrics.items():
            detail = value.get("reason") or value.get("unit") or f"n={value.get('expected', 0)}"
            if "pending" in value:
                detail += f"；pending={value['pending']}；下界～上界 {display(value['lower'])}～{display(value['upper'])}"
            lines.append(f"| {module} | {name} | {display(value['rate'])} | {detail} |")
    lines.extend(["", "Slot Exact Accuracy仅计显式gold；null与省略同为无值，仅city规范化末尾市；未标注额外字段不判对错，故不输出Slot F1。", "",
                  "## 过程效率（独立于质量）", "", "普通指标单位为消息；*_per_task按整个多轮任务累计，缺任一步值则该任务无统计值。total为已知部分，不将未知填0。", "",
                  "| 指标 | 有值/预期 | 已知总量 | P50 | P95 |", "| --- | --- | --- | --- | --- |"])
    for name, value in report["efficiency"].items():
        lines.append(f"| {name} | {value['observed']}/{value['expected']} | {value['total']} | {value['p50']} | {value['p95']} |")
    lines.extend(["", "## 子规则诊断（不作为目标成功证据）", "", "```json",
                  json.dumps(report["diagnostics"], ensure_ascii=False, indent=2), "```", "",
                  "## 来源与复算", "", "```json", json.dumps(report.get("provenance", {}), ensure_ascii=False, indent=2), "```", "",
                  "模型与业务代码同时改变时，只能说明联合变更表现，不能归因于单一因素。",
                  "新旧批次需使用相同题库、快照及同一判分器哈希在新目录复算；原报告继续保留。"])
    return "\n".join(lines) + "\n"


def export(directory, output, reviews_path=None, cases_path=None, fixtures_path=None):
    directory, output = Path(directory), Path(output)
    names = ("results.json", "cases.json", "fixtures.json", "manifest.json")
    paths = {name: directory / name for name in names}
    paths["cases.json"] = Path(cases_path) if cases_path else paths["cases.json"]
    paths["fixtures.json"] = Path(fixtures_path) if fixtures_path else paths["fixtures.json"]
    raw = {name: path.read_bytes() for name, path in paths.items()}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    data = {name: json.loads(value.decode("utf-8-sig")) for name, value in raw.items()}
    manifest = data["manifest.json"]
    for field, name in (("case_sha256", "cases.json"), ("fixture_sha256", "fixtures.json")):
        if manifest.get(field) and manifest[field] != hashes[name]:
            raise ValueError(f"input hash mismatch: {name}")
    reviews = []
    if reviews_path:
        review_raw = Path(reviews_path).read_bytes()
        annotations = json.loads(review_raw.decode("utf-8-sig"))
        if annotations.get("results_sha256") != hashes["results.json"]:
            raise ValueError("review results hash mismatch")
        hashes["reviews.json"] = hashlib.sha256(review_raw).hexdigest()
        reviews = annotations["reviews"]
    report = build_report(data["results.json"], data["cases.json"]["cases"], manifest,
                          fixtures=data["fixtures.json"], reviews=reviews)
    report["validity"] = "valid"
    report["provenance"] = {"inputs_sha256": hashes, "model": manifest.get("model"),
                            "track": manifest.get("track"), "phase": manifest.get("phase"),
                            "code_commit": manifest.get("code_commit"),
                            "source_sha256": manifest.get("source_sha256", {}),
                            "resource_sha256": manifest.get("resource_sha256", {}),
                            "original_evaluation_sha256": manifest.get("evaluation_sha256", {}),
                            "scorer_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                              for name in ("metrics_v2.py", "grading.py", "validate_cases.py")},
                            "source_note": "运行源码哈希由原manifest记录，未宣称等于当前共享工作区"}
    targets = [output / "metrics_v2.json", output / "metrics_v2.md"]
    protected = {path.resolve() for path in paths.values()}
    if reviews_path:
        protected.add(Path(reviews_path).resolve())
    if any(target.exists() or target.resolve() in protected for target in targets):
        raise ValueError("output exists or aliases input; use a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    for target, content in zip(targets, (json.dumps(report, ensure_ascii=False, indent=2), markdown(report))):
        with target.open("x", encoding="utf-8") as file:
            file.write(content)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="包含results/cases/fixtures/manifest.json的只读证据目录")
    parser.add_argument("--output", required=True, type=Path, help="新报告目录；已有输出不会覆盖")
    parser.add_argument("--reviews", type=Path, help="绑定results_sha256的独立人工裁决JSON")
    parser.add_argument("--cases", type=Path, help="另存的冻结题库，仍核对manifest哈希")
    parser.add_argument("--fixtures", type=Path, help="另存的冻结工具/数据快照，仍核对manifest哈希")
    args = parser.parse_args()
    try:
        report = export(args.directory, args.output, args.reviews, args.cases, args.fixtures)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"invalid: {error}\n")
    print(json.dumps({"validity": report["validity"], "expected_steps": report["expected_steps"],
                      "missing_steps": report["missing_steps"], "suites": report["suites"]}, ensure_ascii=False, indent=2))
