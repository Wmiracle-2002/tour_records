import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

import pytest


@pytest.fixture
def tmp_path():
    # Python 3.14 / Windows denies access to pytest's mode=0700 directories here.
    path = Path(tempfile.gettempdir()) / ("metrics-v2-" + uuid.uuid4().hex)
    path.mkdir(mode=0o777)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def reporter():
    # A missing reporter is a feature failure rather than a collection error.
    assert importlib.util.find_spec("metrics_v2") is not None, "v2 reporter is not implemented"
    return importlib.import_module("metrics_v2")


def case(case_id="A", suite="normal", steps=1):
    return {"id": case_id, "suite": suite, "category": "history", "steps": [
        {"action": "message", "required": [{"rule": "requirement_fields", "value": {"city": "南京"}}],
         "forbidden": ["不得编造"]} for _ in range(steps)]}


def row(case_id="A", repeat=1, step=1):
    return {"case_id": case_id, "repeat": repeat, "step": step, "suite": "normal",
            "answer": "南京", "requirements": [{"city": "南京"}], "state": {}, "database": {},
            "final_event": "completed", "events": [{"event": "completed", "data": {}}],
            "tool_runs": [], "llm_http_calls": 2, "completion_ms": 10,
            "usage_delta": {"input_tokens": 10, "output_tokens": 5, "fallback_tokens": 0},
            "grade": {"automatic_status": "pass", "human_status": "pass", "checks": [
                {"rule": "requirement_fields", "status": "pass"}]}}


def review(value, goal="pass", forbidden="pass"):
    return {"case_id": value["case_id"], "repeat": value["repeat"], "step": value["step"],
            "goal_status": goal, "forbidden_status": forbidden,
            "reason": "核对最终答案及数据库", "answer_evidence": "answer", "state_evidence": "database"}


def test_fields_and_legacy_human_flag_do_not_prove_goal():
    m = reporter().build_report([row()], [case()], {"repetitions": 1})
    s = m["suites"]["normal"]
    assert s["auto_candidate"]["passed"] == 1
    assert s["success"] == {"expected": 1, "pass": 0, "fail": 0, "pending": 1,
                            "lower": 0, "upper": 1, "rate": None}
    assert m["steps"][0]["forbidden_status"] == "pending"
    assert m["tool_call_accuracy"]["rate"] is None
    assert m["rag_faithfulness"]["rate"] is None


def test_manual_goal_needs_independent_forbidden_confirmation():
    r = row()
    m = reporter().build_report([r], [case()], {"repetitions": 1}, reviews=[review(r, forbidden="pending")])
    assert m["suites"]["normal"]["success"]["pending"] == 1
    m = reporter().build_report([r], [case()], {"repetitions": 1}, reviews=[review(r)])
    assert m["suites"]["normal"]["success"]["rate"] == 1


def test_diagnostic_failure_does_not_override_reviewed_goal():
    r = row()
    r["grade"]["checks"][0]["status"] = "fail"
    m = reporter().build_report([r], [case()], {"repetitions": 1}, reviews=[review(r)])
    assert m["suites"]["normal"]["auto_candidate"]["passed"] == 0
    assert m["suites"]["normal"]["success"]["pass"] == 1


def test_multistep_missing_repeat_and_suite_denominators():
    cases = [case(steps=2), case("F", "fault")]
    rows = [row(step=1), row(step=2), row(repeat=2, step=1)]
    m = reporter().build_report(rows, cases, {"repetitions": 3})
    assert m["expected_steps"] == 9
    assert m["missing_steps"] == 6
    assert m["suites"]["normal"]["auto_candidate"] == {"passed": 1, "expected": 3, "rate": 1 / 3}
    assert m["suites"]["normal"]["success"]["fail"] == 2
    assert m["suites"]["fault"]["success"]["expected"] == 3
    assert m["suites"]["normal"]["observed_all_3_auto"]["passed"] == 0


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "suite", "order", "empty_task", "bad_review"])
def test_invalid_inputs_are_not_silently_deduplicated_or_passed(kind):
    rows, cases, manifest, reviews = [row()], [case()], {"repetitions": 1}, []
    if kind == "duplicate":
        rows.append(row())
    elif kind == "unknown":
        rows[0]["case_id"] = "missing"
    elif kind == "suite":
        rows[0]["suite"] = "fault"
    elif kind == "order":
        manifest.update(repetitions=3, order=[[1, "A"]])
    elif kind == "empty_task":
        cases[0]["steps"] = []
    else:
        reviews = [review(rows[0])]
        reviews[0].pop("state_evidence")
    with pytest.raises(ValueError):
        reporter().build_report(rows, cases, manifest, reviews=reviews)


def test_empty_checks_and_missing_usage_are_not_vacuous_success_or_zero():
    r = row()
    r["grade"]["checks"] = []
    r.pop("usage_delta")
    r.pop("llm_http_calls")
    m = reporter().build_report([r], [case()], {"repetitions": 1})
    assert m["suites"]["normal"]["auto_candidate"]["passed"] == 0
    assert m["efficiency"]["actual_tokens"]["observed"] == 0
    assert m["efficiency"]["actual_tokens"]["total"] is None
    assert m["efficiency"]["llm_http_calls"]["total"] is None
    assert m["suites"]["normal"]["observed_all_3_auto"]["rate"] is None


def test_reference_tools_match_arguments_and_allow_equivalent_paths():
    c, r = case(), row()
    c["steps"][0]["reference_tool_paths"] = [
        [{"tool_name": "lookup", "arguments": {"city": "南京"}}],
        [{"tool_name": "search", "arguments": {"city": "南京"}}]]
    r["tool_runs"] = [{"tool_name": "search", "arguments_json": {"city": "南京"}}]
    assert reporter().build_report([r], [c], {"repetitions": 1})["tool_call_accuracy"]["rate"] == 1
    r["tool_runs"][0]["arguments_json"]["city"] = "上海"
    assert reporter().build_report([r], [c], {"repetitions": 1})["tool_call_accuracy"]["rate"] == 0


def test_termination_and_safe_degradation_do_not_imply_success():
    c, r = case("F", "fault"), row("F")
    c["steps"][0]["required"] = [{"rule": "safe_tool_failure", "value": True}]
    r["suite"] = "fault"
    r["grade"]["checks"] = [{"rule": "safe_tool_failure", "status": "pass"}]
    m = reporter().build_report([r], [c], {"repetitions": 1})
    assert m["termination"]["rate"] == 1
    assert m["safe_degradation"]["auto_proxy"]["rate"] == 1
    assert m["safe_degradation"]["confirmed"]["pending"] == 1
    r["events"].append({"event": "completed", "data": {}})
    assert reporter().build_report([r], [c], {"repetitions": 1})["termination"]["rate"] == 0


def test_export_recomputes_proxy_preserves_sources_and_binds_hashes(tmp_path):
    mod = reporter()
    source = tmp_path / "source"
    source.mkdir()
    content = {"results.json": [row()], "cases.json": {"cases": [case()]},
               "fixtures.json": {"tool_snapshots": {"pois": []}},
               "manifest.json": {"repetitions": 1, "model": "old", "source_sha256": {"app.py": "old-hash"}}}
    for name, value in content.items():
        (source / name).write_text(json.dumps(value), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    output = tmp_path / "v2"
    mod.export(source, output)
    result = json.loads((output / "metrics_v2.json").read_text(encoding="utf-8"))
    assert result["provenance"]["inputs_sha256"]["results.json"] == hashlib.sha256(before["results.json"]).hexdigest()
    assert result["provenance"]["source_sha256"] == {"app.py": "old-hash"}
    assert result["suites"]["normal"]["auto_candidate"]["passed"] == 1
    assert "Task Success Rate" in (output / "metrics_v2.md").read_text(encoding="utf-8")
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(ValueError):
        mod.export(source, output)
    content["manifest.json"]["case_sha256"] = "wrong"
    (source / "manifest.json").write_text(json.dumps(content["manifest.json"]), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        mod.export(source, tmp_path / "mismatch")


def test_review_file_cannot_be_reused_for_different_results(tmp_path):
    # Hash binding is checked before any adjudication is consumed.
    mod = reporter()
    for name, value in {"results.json": [row()], "cases.json": {"cases": [case()]},
                        "fixtures.json": {"tool_snapshots": {"pois": []}},
                        "manifest.json": {"repetitions": 1}}.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"results_sha256": "wrong", "reviews": [review(row())]}), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        mod.export(tmp_path, tmp_path / "v2", reviews)


def test_all_three_requires_all_repeats_and_final_reviews():
    rows = [row(repeat=i) for i in (1, 2, 3)]
    m = reporter().build_report(rows, [case()], {"repetitions": 3}, reviews=[review(rows[0])])
    assert m["suites"]["normal"]["observed_all_3_auto"]["rate"] == 1
    assert m["suites"]["normal"]["observed_all_3_success"]["pending"] == 1
    m = reporter().build_report(rows, [case()], {"repetitions": 3}, reviews=[review(r) for r in rows])
    assert m["suites"]["normal"]["observed_all_3_success"]["rate"] == 1


def test_recompute_does_not_trust_stored_pass_and_does_not_mutate_rows():
    r = row()
    r["requirements"] = [{"city": "上海"}]
    before = json.dumps(r, sort_keys=True)
    m = reporter().build_report([r], [case()], {"repetitions": 1},
                                fixtures={"tool_snapshots": {"pois": []}})
    assert m["suites"]["normal"]["auto_candidate"]["rate"] == 0
    assert m["diagnostics"]["requirement_fields"] == {"fail": 1}
    assert json.dumps(r, sort_keys=True) == before


@pytest.mark.parametrize("goal,forbidden", [("fail", "pass"), ("pass", "fail")])
def test_automatic_pass_cannot_override_negative_goal_or_safety_review(goal, forbidden):
    r = row()
    m = reporter().build_report([r], [case()], {"repetitions": 1}, reviews=[review(r, goal, forbidden)])
    assert m["suites"]["normal"]["auto_candidate"]["rate"] == 1
    assert m["suites"]["normal"]["success"]["upper"] == 0


def test_manifest_selection_and_non_message_step_indices():
    a, b = case(), case("B")
    a["steps"].insert(0, {"action": "new_conversation"})
    m = reporter().build_report([row(step=2)], [a, b], {"repetitions": 1, "order": [[1, "A"]]})
    assert m["expected_steps"] == 1
    assert m["suites"]["normal"]["success"]["expected"] == 1


def test_module_intent_slots_null_city_and_unannotated_extras():
    c, r = case(), row()
    c["steps"][0]["required"][0]["value"] = {"intent": "history", "city": "南京市", "destination": None}
    r["requirements"] = [{"intent": "history", "city": "南京", "unannotated": "extra"}]
    m = reporter().build_report([r], [c], {"repetitions": 1})
    assert m["modules"]["requirement_understanding"]["intent_accuracy"]["rate"] == 1
    assert m["modules"]["requirement_understanding"]["slot_exact_accuracy"]["rate"] == 1
    assert m["modules"]["requirement_understanding"]["slot_f1"]["rate"] is None
    r["requirements"][0]["destination"] = "上海"
    m = reporter().build_report([r], [c], {"repetitions": 1})
    assert m["modules"]["requirement_understanding"]["slot_exact_accuracy"]["rate"] == .5


def test_task_efficiency_excludes_incomplete_tasks_and_sums_all_turns():
    rows = [row(), row(step=2), row(repeat=2)]
    m = reporter().build_report(rows, [case(steps=2)], {"repetitions": 2})
    assert m["efficiency"]["tokens_per_task"] == {"observed": 1, "expected": 2, "total": 30, "p50": 30, "p95": 30}
    assert m["efficiency"]["calls_per_task"]["p50"] == 4


def test_cli_accepts_external_frozen_snapshots_and_emits_both_reports(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    for name, value in {"cases.json": {"cases": [case()]}, "fixtures.json": {"tool_snapshots": {"pois": []}}}.items():
        (snapshots / name).write_text(json.dumps(value), encoding="utf-8")
    manifest = {"repetitions": 1,
                "case_sha256": hashlib.sha256((snapshots / "cases.json").read_bytes()).hexdigest(),
                "fixture_sha256": hashlib.sha256((snapshots / "fixtures.json").read_bytes()).hexdigest()}
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "results.json").write_text(json.dumps([row()]), encoding="utf-8")
    output = tmp_path / "v2"
    command = [sys.executable, "-B", str(Path(__file__).with_name("metrics_v2.py")), str(source),
               "--cases", str(snapshots / "cases.json"), "--fixtures", str(snapshots / "fixtures.json"),
               "--output", str(output)]
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["validity"] == "valid"
    assert set(p.name for p in output.iterdir()) == {"metrics_v2.json", "metrics_v2.md"}
    again = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert again.returncode == 2
