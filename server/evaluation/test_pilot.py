"""Pilot collection checks without live model requests."""

import json
from pathlib import Path
from time import monotonic

import pytest

from run_pilot import SnapshotProvider, read_sse


class Response:
    def __init__(self, frames):
        self.frames = frames

    def iter_lines(self):
        for name, payload in self.frames:
            yield f"event: {name}"
            yield "data: " + json.dumps(payload)
            yield ""


def test_stages_do_not_count_as_body_or_completion():
    result = read_sse(Response([("stage", {"message": "正在规划"})]), monotonic())
    assert result["first_body_ms"] is None
    assert result["completion_ms"] is None
    assert result["final_event"] is None


def test_preview_does_not_duplicate_final_answer():
    result = read_sse(Response([
        ("stage", {"message": "正在规划"}),
        ("preview", {"text": "旧预览"}),
        ("content", {"text": "最终正文"}),
        ("completed", {"answer": "最终正文"}),
    ]), monotonic())
    assert result["answer"] == "最终正文"
    assert result["first_body_ms"] <= result["completion_ms"]
    assert result["final_event"] == "completed"


def test_stream_error_never_becomes_successful_completion():
    result = read_sse(Response([
        ("preview", {"text": "部分行程"}),
        ("error", {"code": 504, "message": "超时"}),
    ]), monotonic())
    assert result["first_body_ms"] is not None
    assert result["completion_ms"] is None
    assert result["answer"] is None
    assert result["final_event"] == "error"


def test_snapshot_rejects_wrong_distance_endpoints_and_removes_key():
    fixtures = json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))
    provider = SnapshotProvider(fixtures)
    with pytest.raises(ValueError, match="wrong distance origin"):
        provider("https://restapi.amap.com/v3/distance", {
            "key": "test-secret", "origins": "121.48,31.23", "destination": "118.805000,32.042000", "type": "0"
        }, 10)
    assert "key" not in provider.calls[0]["parameters"]
