"""Offline component benchmark. Gold lives in a separate, frozen JSON file.

No LLM judge or fuzzy answer correctness claims: explicit contradictions fail,
explicit contracts pass, everything else needs review. Production code is used
for retrieval, schema validation, normalization, execution and routing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import socket
from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def detection_metrics(gold, predicted):
    if len(gold) != len(predicted):
        raise ValueError("Gold/prediction lengths differ")
    tp = sum(g and p for g, p in zip(gold, predicted))
    fp = sum(not g and p for g, p in zip(gold, predicted))
    fn = sum(g and not p for g, p in zip(gold, predicted))
    tn = sum(not g and not p for g, p in zip(gold, predicted))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def retrieval_metrics(actual, relevant, *, k=5):
    if k <= 0:
        raise ValueError("k must be positive")
    ranked = list(dict.fromkeys(actual))[:k]
    relevant = set(relevant)
    hits = [i + 1 for i, entry_id in enumerate(ranked) if entry_id in relevant]
    dcg = sum(1 / math.log2(rank + 1) for rank in hits)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return {"precision_at_k": len(hits) / k if relevant else None,
            "precision_returned": len(hits) / len(ranked) if ranked else None,
            "recall_at_k": len(hits) / len(relevant) if relevant else None,
            "mrr": 1 / hits[0] if hits else (0 if relevant else None),
            "ndcg_at_k": dcg / ideal if ideal else None,
            "empty_query_correct": not ranked if not relevant else None}


def score_answer(answer, contract):
    if any(re.search(pattern, answer) for pattern in contract.get("forbidden", [])):
        return "fail"
    required = contract.get("required", [])
    if required and all(re.search(pattern, answer) for pattern in required):
        return "pass"
    return "review"


def _database(notes=()):
    from app.database import Base
    from app.models import KnowledgeEntry, User
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all([User(id=i, username=f"offline-{i}", password_hash="unused") for i in (1, 2)])
    db.flush()
    for note in notes:
        db.add(KnowledgeEntry(**note, city_name={"320100": "南京", "310000": "上海"}.get(note["city_code"], "测试城市")))
    db.commit()
    return engine, db


def _evaluate(case, data):
    from app.agent import normalizer
    from app.agent.collector import ToolCall, _normalize_tool_arguments
    from app.agent.graph import _collection_route, _validation_route, make_initial_state
    from app.agent.knowledge import search_knowledge
    from app.agent.memory import ConversationMemoryService
    from app.agent.models import CollectedInfo, InformationStatus, Itinerary, TravelRequirement, ValidationResult
    from app.agent.runtime import AgentRuntime
    from app.agent.tools.amap import KeywordSearchInput, VerifiedPoiSearchInput
    from app.agent.validator import ItineraryValidator
    from app.models import ChatConversation, ChatMessage

    kind, source, gold = case["module"], case["input"], case["gold"]
    if kind.startswith("knowledge"):
        notes = data["notes"] + case.get("extra_notes", [])
        engine, db = _database(notes)
        try:
            if kind == "knowledge_runtime":
                rows = AgentRuntime._search_knowledge(db, source["user_id"], source["city"], source["keywords"], kind=source.get("kind"))
            else:
                rows = search_knowledge(db, source["user_id"], source["city_code"],
                                        category=source.get("category"), keywords=source["keywords"], district_code=source.get("district_code"))
            prediction = [row.id for row in rows]
            by_id = {note["id"]: note for note in notes}
            wrong_owner = [i for i in prediction if by_id[i]["user_id"] != source["user_id"]]
            wrong_city = [i for i in prediction if by_id[i]["city_code"] != source["city_code"]]
            wrong_category = [i for i in prediction if source.get("category") and by_id[i]["category"] != source["category"]]
            relevant = gold["relevant_ids"]
            supported = [row.id for row in rows if row.id in relevant and
                         all(text in row.excerpt for text in gold.get("excerpt_facts", {}).get(str(row.id), []))]
            metrics = retrieval_metrics(prediction, relevant)
            metrics.update(owner_violations=len(wrong_owner), city_violations=len(wrong_city),
                           category_violations=len(wrong_category),
                           excerpt_fact_recall=(sum(i in supported for i in map(int, gold["excerpt_facts"])) / len(gold["excerpt_facts"])
                                                if gold.get("excerpt_facts") else None))
            passed = (set(prediction) == set(relevant) and not wrong_owner and not wrong_city
                      and all(int(i) in supported for i in gold.get("excerpt_facts", {})))
            return {"prediction": prediction, "excerpts": [{"id": row.id, "text": row.excerpt} for row in rows],
                    "metrics": metrics, "status": "pass" if passed else "fail"}
        finally:
            db.close()
            engine.dispose()
    if kind == "memory":
        engine, db = _database()
        try:
            db.add_all([ChatConversation(id="own", user_id=1), ChatConversation(id="other", user_id=2)])
            db.flush()
            db.add_all([ChatMessage(**row) for row in data["messages"]])
            db.commit()
            try:
                context = ConversationMemoryService(db, source["user_id"], source["conversation_id"], 1000).build_context(source["query"])
                prediction = context.retrieved_message_ids
                return {"prediction": prediction, "context": context.prompt_context,
                        "metrics": retrieval_metrics(prediction, gold["relevant_ids"], k=3),
                        "status": "pass" if set(prediction) == set(gold["relevant_ids"]) else "fail"}
            except ValueError as error:
                return {"prediction": "rejected", "error": str(error),
                        "status": "pass" if gold.get("rejected") else "fail"}
        finally:
            db.close()
            engine.dispose()
    if kind in {"memory_state", "memory_compression"}:
        from app.agent.memory import CONVERSATION_MEMORY_TOKEN_BUDGET
        from app.models import AgentConversationMemory, AgentConversationSummary
        from sqlalchemy import select
        engine, db = _database()
        try:
            db.add(ChatConversation(id="own", user_id=1))
            db.flush()
            service = ConversationMemoryService(db, 1, "own", 1000)
            if kind == "memory_state":
                state = None
                for index, turn in enumerate(source["turns"], 1):
                    state = service.save_requirement(index, turn["message"],
                                                     TravelRequirement.model_validate(turn["requirement"]))
                prediction = {name: getattr(state, name) for name in gold}
                passed = prediction == gold
            else:
                db.add_all([ChatMessage(id=i, conversation_id="own", role="user", content="原始内容" * 100, status="completed")
                            for i in range(1, 41)])
                db.commit()
                calls = []
                def summarize(text):
                    calls.append(text)
                    if source.get("summary_failure"):
                        raise ValueError("Injected summary failure")
                    return "固定摘要用于验证落盘，不评估语义压缩质量。"
                context = service.build_context("继续", summarize=summarize)
                summaries = db.scalars(select(AgentConversationSummary)).all()
                memory = db.scalar(select(AgentConversationMemory))
                messages = db.scalars(select(ChatMessage)).all()
                prediction = {"compressed": context.compression_triggered,
                              "within_budget": context.token_estimate <= CONVERSATION_MEMORY_TOKEN_BUDGET,
                              "raw_preserved": len(messages) == 40 and all(row.content == "原始内容" * 100 for row in messages),
                              "valid_pointers": bool(summaries) and all(1 <= row.first_message_id <= row.last_message_id < 25 for row in summaries)
                                                and memory.summary_cursor_message_id == max(row.last_message_id for row in summaries)}
                passed = prediction == gold
            return {"prediction": prediction, "status": "pass" if passed else "fail"}
        finally:
            db.close()
            engine.dispose()
    if kind == "parameters":
        models = {"requirement": TravelRequirement, "poi": VerifiedPoiSearchInput, "keyword": KeywordSearchInput}
        try:
            arguments = dict(source["arguments"])
            if arguments.get("budget") == "__NaN__":
                arguments["budget"] = float("nan")
            value = models[source["model"]].model_validate(arguments)
            prediction = {"rejected": False, "value": value.model_dump(mode="json")}
        except ValidationError as error:
            prediction = {"rejected": True, "error": str(error)}
        return {"prediction": prediction, "status": "pass" if prediction["rejected"] == gold["rejected"] else "fail"}
    if kind == "parameter_repair":
        result = _normalize_tool_arguments(ToolCall.model_validate(source["call"]),
                                           TravelRequirement.model_validate(source["requirement"]))
        return {"prediction": result, "status": "pass" if result == gold["arguments"] else "fail"}
    if kind == "normalizer":
        try:
            result = normalizer.normalize_distance(source["raw"], origin_id="A", destination_id="B")
            prediction = {"rejected": False, "distance": result.distance_meters}
        except (normalizer.NormalizerError, ValidationError) as error:
            prediction = {"rejected": True, "error": str(error)}
        passed = prediction["rejected"] == gold["rejected"] and (gold["rejected"] or prediction["distance"] == gold["distance"])
        return {"prediction": prediction, "status": "pass" if passed else "fail"}
    if kind == "validator":
        result = ItineraryValidator().validate(TravelRequirement.model_validate(source["requirement"]),
                                               Itinerary.model_validate(source["itinerary"]),
                                               CollectedInfo.model_validate(source["collected_info"]))
        rejected = not result.valid
        return {"prediction": {"rejected": rejected, "issues": result.model_dump(mode="json")["issues"]},
                "status": "pass" if rejected == gold["rejected"] else "fail"}
    if kind == "routing":
        state = make_initial_state("离线固定状态")
        state["requirement"] = TravelRequirement.model_validate(source["requirement"])
        state["information_status"] = InformationStatus.model_validate(source.get("information_status", {}))
        state["react_round"] = source.get("round", 0)
        state["validation_round"] = source.get("round", 0)
        state["react_action"] = source.get("action", "none")
        if source["route"] == "collection":
            prediction = _collection_route(state, 4)
        else:
            state["validation"] = ValidationResult.model_validate(source["validation"])
            prediction = _validation_route(state, 2)
        return {"prediction": prediction, "status": "pass" if prediction == gold["route"] else "fail"}
    if kind == "answer_grader":
        prediction = score_answer(source["answer"], source["contract"])
        return {"prediction": prediction, "status": "pass" if prediction == gold["status"] else "fail"}
    if kind == "tool_execution":
        from app.agent.tools.layer import EmptyToolInput, ToolLayer, ToolRegistry, ToolResult, ToolUnavailableError

        class InjectedTool:
            name = "probe"
            description = "Fixed offline response, not a real provider"
            input_model = EmptyToolInput
            information_need = "pois"

            def run(self, **arguments):
                if source["behavior"] == "exception":
                    raise RuntimeError("Injected failure")
                if source["behavior"] == "unavailable":
                    raise ToolUnavailableError("Injected unavailable")
                if source["behavior"] == "invalid_result":
                    return {"data": []}
                return ToolResult.completed([])

        registry = ToolRegistry()
        registry.register(InjectedTool())
        result = ToolLayer(registry).execute(source.get("tool_name", "probe"), **source.get("arguments", {}))
        prediction = {"status": result.status, "error_code": result.error_code}
        return {"prediction": prediction, "status": "pass" if prediction == gold else "fail"}
    if kind == "output":
        from app.agent.response import FinalResponseGenerator
        answer = FinalResponseGenerator().generate(
            TravelRequirement.model_validate(source["requirement"]),
            CollectedInfo.model_validate(source["collected_info"]), InformationStatus(),
            Itinerary.model_validate(source["itinerary"]) if source.get("itinerary") else None,
            ValidationResult(valid=True),
        )
        passed = all(text in answer for text in gold["required"]) and not any(text in answer for text in gold["forbidden"])
        return {"prediction": answer, "status": "pass" if passed else "fail"}
    raise ValueError(f"Unknown module: {kind}")


def run(dataset: Path, output: Path):
    if output.exists():
        raise ValueError("Output already exists; use a fresh directory")
    frozen = dataset.read_bytes()
    data = json.loads(frozen)
    cases = data["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    network_attempts = []
    llm_attempts = []

    def blocked(*args, **kwargs):
        network_attempts.append("socket connection attempted")
        raise RuntimeError("Offline benchmark forbids network connections")

    def blocked_llm(*args, **kwargs):
        llm_attempts.append("Unexpected LLM call")
        raise RuntimeError("Offline benchmark forbids LLM calls")

    results = []
    from app.agent.llm import StructuredLLMClient
    with patch.object(socket.socket, "connect", blocked), patch.object(socket.socket, "connect_ex", blocked), patch.object(socket, "create_connection", blocked), patch.object(StructuredLLMClient, "complete_structured", blocked_llm), patch.object(StructuredLLMClient, "complete_structured_stream", blocked_llm):
        for case in cases:
            started = perf_counter()
            try:
                result = _evaluate(case, data)
            except Exception as error:
                result = {"status": "error", "error": f"{type(error).__name__}: {error}"}
            results.append({**case, **result, "duration_ms": (perf_counter() - started) * 1000})
    if dataset.read_bytes() != frozen:
        raise ValueError("Gold changed while running")
    groups = defaultdict(list)
    for row in results:
        if row["split"] == "evaluation":
            groups[row["module"]].append(row)
    report = {}
    for module, rows in groups.items():
        summary = {"n": len(rows), "status_counts": {status: sum(row["status"] == status for row in rows)
                                                   for status in ("pass", "fail", "error")}}
        if module.startswith("knowledge") or module == "memory":
            for metric in ("precision_at_k", "precision_returned", "recall_at_k", "mrr", "ndcg_at_k", "excerpt_fact_recall"):
                values = [row["metrics"][metric] for row in rows if row.get("metrics", {}).get(metric) is not None]
                summary[metric] = {"macro_mean": mean(values) if values else None, "denominator_queries": len(values)}
            summary["empty_queries"] = {"n": sum(not row["gold"].get("relevant_ids") for row in rows if "metrics" in row),
                                        "correct": sum(row.get("metrics", {}).get("empty_query_correct") is True for row in rows)}
            summary["returned_documents"] = sum(len(row["prediction"]) for row in rows if "metrics" in row)
            summary["relevant_returned_documents"] = sum(len(set(row["prediction"]) & set(row["gold"]["relevant_ids"]))
                                                         for row in rows if "metrics" in row)
            summary["micro_precision_returned"] = (summary["relevant_returned_documents"] / summary["returned_documents"]
                                                    if summary["returned_documents"] else None)
            if module.startswith("knowledge"):
                for violation in ("owner_violations", "city_violations", "category_violations"):
                    summary[violation] = sum(row.get("metrics", {}).get(violation, 0) for row in rows)
        if module in {"parameters", "normalizer", "validator"}:
            scored = [row for row in rows if row["status"] != "error"]
            summary["error_detection"] = detection_metrics([row["gold"]["rejected"] for row in scored],
                                                          [row["prediction"]["rejected"] for row in scored])
        if module == "answer_grader":
            summary["contradiction_detection"] = detection_metrics(
                [row["gold"]["status"] == "fail" for row in rows], [row["prediction"] == "fail" for row in rows])
            summary["abstentions"] = sum(row["prediction"] == "review" for row in rows)
        report[module] = summary
    output.mkdir(parents=True)
    payload = {"dataset_sha256": hashlib.sha256(frozen).hexdigest(), "real_llm_calls": 0,
               "network_attempts": len(network_attempts), "llm_attempts": len(llm_attempts), "annotation": data["annotation"],
               "total_cases": len(results), "development_cases": sum(row["split"] == "dev" for row in results),
               "limits": "Hand-authored component challenge set; not blind holdout or model/end-to-end accuracy.",
               "modules": report}
    payload["valid_offline_run"] = not network_attempts and not llm_attempts
    source_root = Path(__file__).resolve().parents[1]
    payload["source_sha256"] = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in (
        "app/agent/knowledge.py", "app/agent/runtime.py", "app/agent/memory.py", "app/agent/validator.py",
        "app/agent/normalizer.py", "app/agent/tools/amap.py", "app/agent/tools/layer.py",
        "app/agent/collector.py", "app/agent/graph.py", "app/agent/response.py", "app/agent/models.py",
        "evaluation/offline_evaluation.py",
    )}
    (output / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "frozen_cases.json").write_bytes(frozen)
    lines = ["# 零Token评测逐条证据", "", f"Gold SHA256：`{payload['dataset_sha256']}`", "",
             "Gold由Codex根据用户需求手工编写，尚非用户确认或独立专家标注。合成笔记/店名仅用于检索评测。", ""]
    for row in results:
        lines.extend([f"## {row['id']} · {row['module']} · {row['status']}", "", row["rationale"], "",
                      "```json", json.dumps(row, ensure_ascii=False, indent=2), "```", ""])
    (output / "cases.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("offline_cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output), ensure_ascii=False, indent=2))
