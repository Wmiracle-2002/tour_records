import json
from pathlib import Path

import pytest

from offline_evaluation import detection_metrics, retrieval_metrics, run, score_answer


def test_retrieval_counts_missing_slots_and_deduplicates():
    result = retrieval_metrics([1, 1, 9], [1, 2], k=5)
    assert result["precision_at_k"] == pytest.approx(1 / 5)
    assert result["recall_at_k"] == pytest.approx(1 / 2)
    assert result["precision_returned"] == pytest.approx(1 / 2)
    assert result["mrr"] == 1


def test_no_relevant_documents_is_not_perfect_recall():
    result = retrieval_metrics([], [], k=5)
    assert result["recall_at_k"] is None
    assert result["mrr"] is None
    assert result["empty_query_correct"] is True
    assert retrieval_metrics([9], [], k=5)["empty_query_correct"] is False


def test_detection_denominators_include_false_accepts_and_false_rejects():
    assert detection_metrics([True, True, False, False], [True, False, True, False]) == {
        "tp": 1, "fp": 1, "fn": 1, "tn": 1,
        "precision": 0.5, "recall": 0.5, "f1": 0.5,
    }


def test_answer_contract_handles_negation_and_uncertainty():
    contract = {"required": ["你此前说过总预算2000元"], "forbidden": ["没有说过.*2000"]}
    assert score_answer("你没有说过总预算2000元。", contract) == "fail"
    assert score_answer("你此前说过总预算2000元。", contract) == "pass"
    assert score_answer("你的预算大概两千。", contract) == "review"


def test_old_quote_is_separate_from_present_fact():
    contract = {"required": ["历史笔记", "非当前价格"], "forbidden": ["当前门票999元"]}
    assert score_answer("历史笔记原文：门票999元。非当前价格，请出行前核实。", contract) == "pass"
    assert score_answer("当前门票999元。", contract) == "fail"


def test_ndcg_and_mrr_use_original_rank_not_hit_rank():
    result = retrieval_metrics([9, 1], [1], k=5)
    assert result["mrr"] == 0.5
    assert result["ndcg_at_k"] == pytest.approx(1 / __import__("math").log2(3))


def test_metric_rejects_invalid_denominators():
    with pytest.raises(ValueError):
        retrieval_metrics([], [], k=0)
    with pytest.raises(ValueError):
        detection_metrics([True], [])


def test_frozen_asset_has_explicit_annotation_and_unique_ids():
    dataset = json.loads((Path(__file__).parents[1] / "evaluation/offline_cases.json").read_text(encoding="utf-8"))
    assert dataset["annotation"]["user_verified"] is False
    assert len({case["id"] for case in dataset["cases"]}) == len(dataset["cases"])
    assert all(case["gold"] and case["rationale"] for case in dataset["cases"])


def test_runner_preserves_gold_and_does_not_overwrite_results(tmp_path):
    dataset = tmp_path / "gold.json"
    body = json.dumps({"annotation": {"author": "test"}, "cases": [{
        "id": "X01", "module": "normalizer", "split": "evaluation", "group": "boundary",
        "input": {"raw": {"distance": -1}}, "gold": {"rejected": True}, "rationale": "Negative distance",
    }]})
    dataset.write_text(body, encoding="utf-8")
    output = tmp_path / "output"
    result = run(dataset, output)
    assert result["valid_offline_run"]
    assert result["modules"]["normalizer"]["error_detection"]["tp"] == 1
    assert dataset.read_text(encoding="utf-8") == body
    assert (output / "frozen_cases.json").read_text(encoding="utf-8") == body
    with pytest.raises(ValueError, match="already exists"):
        run(dataset, output)


def test_accidental_network_call_is_blocked_and_marks_run_invalid(tmp_path, monkeypatch):
    import socket
    import offline_evaluation

    def accidental_call(*args):
        socket.create_connection(("127.0.0.1", 1))
    monkeypatch.setattr(offline_evaluation, "_evaluate", accidental_call)
    dataset = tmp_path / "gold.json"
    dataset.write_text(json.dumps({"annotation": {}, "cases": [{
        "id": "X", "module": "normalizer", "split": "evaluation",
        "input": {}, "gold": {"rejected": False}, "rationale": "Network guard probe",
    }]}), encoding="utf-8")
    result = run(dataset, tmp_path / "output")
    assert result["network_attempts"] == 1
    assert result["valid_offline_run"] is False
    assert result["modules"]["normalizer"]["status_counts"]["error"] == 1
