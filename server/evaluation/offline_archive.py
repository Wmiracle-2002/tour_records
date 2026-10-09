"""Re-score existing model traces; never invoke a model or alter source logs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from grading import percentile


def analyze(directory):
    result_path = directory / "results.json"
    source = result_path.read_bytes()
    rows = json.loads(source)
    cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))["cases"]
    lookup = {case["id"]: case for case in cases}
    intents, slots, evidence, stages = [], [], [], {}
    for row in rows:
        step = lookup[row["case_id"]]["steps"][row["step"] - 1]
        outputs = [item["output"] for item in row.get("model_outputs", []) if item["model"] == "TravelRequirement"]
        actual = outputs[0] if outputs else {}
        for rule in step.get("required", []):
            if rule["rule"] != "requirement_fields":
                continue
            for field, gold in rule["value"].items():
                prediction = actual.get(field)
                if field == "city":
                    gold = gold.removesuffix("市") if isinstance(gold, str) else gold
                    prediction = prediction.removesuffix("市") if isinstance(prediction, str) else prediction
                item = {"case_id": row["case_id"], "repeat": row["repeat"], "step": row["step"],
                        "field": field, "gold": gold, "prediction": prediction, "match": gold == prediction}
                evidence.append(item)
                (intents if field == "intent" else slots).append(item)
        for event in row.get("stage_events", []):
            if event.get("event") != "stage_completed":
                continue
            name = event.get("stage_name")
            stages.setdefault(name, []).append(event)
    labels = sorted({item["gold"] for item in intents})
    per_class = {}
    for label in labels:
        tp = sum(item["gold"] == label and item["prediction"] == label for item in intents)
        fp = sum(item["gold"] != label and item["prediction"] == label for item in intents)
        fn = sum(item["gold"] == label and item["prediction"] != label for item in intents)
        per_class[label] = {"support": sum(item["gold"] == label for item in intents),
                            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0}
    matches = sum(item["match"] for item in slots)
    summary = {
        "source_sha256": hashlib.sha256(source).hexdigest(), "real_llm_calls": 0,
        "scope": "Historical known regression cases, partial gold; structured outputs captured after parsing/validation. Not current model generalization.",
        "intent": {"n": len(intents), "unique_steps": len({(item['case_id'], item['step']) for item in intents}),
                   "accuracy": sum(item["match"] for item in intents) / len(intents) if intents else None,
                   "macro_f1": sum(item["f1"] for item in per_class.values()) / len(per_class) if per_class else None,
                   "per_class": per_class},
        "annotated_slot_subset": {"n": len(slots), "unique_field_checks": len({(item['case_id'], item['step'], item['field']) for item in slots}),
                                  "field_value_em": matches / len(slots) if slots else None,
                                  "micro_f1": matches / len(slots) if slots else None,
                                  "missing_full_slot_gold": True},
        "stages": {name: {"n": len(events), "status_counts": dict(Counter(event.get("stage_status") for event in events)),
                          "p50_ms": percentile([event["stage_duration_ms"] for event in events], .5),
                          "p95_ms": percentile([event["stage_duration_ms"] for event in events], .95)}
                   for name, events in stages.items()},
        "not_measured": ["Full-slot F1", "Tool-choice accuracy/F1 (missing exhaustive reference traces)",
                         "Answer faithfulness (missing independent atomic claim labels)",
                         "Current model end-to-end TSR", "Summary semantic fact F1"],
    }
    if result_path.read_bytes() != source:
        raise ValueError("Source result changed")
    return summary, evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a fresh output directory")
    summary, evidence = analyze(args.source)
    args.output.mkdir(parents=True)
    for name, value in (("report.json", summary), ("evidence.json", evidence)):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
