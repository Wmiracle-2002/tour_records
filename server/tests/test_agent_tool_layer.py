from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.tools.layer import (
    DuplicateToolError,
    ToolLayer,
    ToolRegistry,
    ToolResult,
    ToolUnavailableError,
)


class EchoTool:
    name = "echo"
    description = "返回传入的值"

    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None

    def run(self, **arguments: Any) -> ToolResult[str]:
        self.arguments = arguments
        return ToolResult.completed(arguments["value"])


class UnavailableTool:
    name = "weather"
    description = "查询天气"

    def run(self, **_arguments: Any) -> ToolResult[Any]:
        raise ToolUnavailableError("天气服务暂不可用")


class BrokenTool:
    name = "broken"
    description = "模拟异常工具"

    def run(self, **_arguments: Any) -> ToolResult[Any]:
        raise RuntimeError("内部细节不应直接暴露")


def test_tool_result_has_unified_status_and_payload() -> None:
    completed = ToolResult.completed({"count": 1})
    unavailable = ToolResult.unavailable("服务暂不可用", error_code="provider_down")
    failed = ToolResult.failed("执行失败", error_code="execution_error")

    assert completed.status == "completed"
    assert completed.data == {"count": 1}
    assert unavailable.status == "unavailable"
    assert unavailable.error_code == "provider_down"
    assert failed.status == "failed"
    assert failed.error_code == "execution_error"


def test_invalid_tool_result_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolResult(status="unknown")


def test_registry_registers_tools_and_rejects_duplicates() -> None:
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)

    assert registry.get("echo") is tool
    assert registry.names() == ("echo",)
    with pytest.raises(DuplicateToolError):
        registry.register(EchoTool())


def test_tool_layer_forwards_arguments_and_returns_completed_result() -> None:
    tool = EchoTool()
    registry = ToolRegistry()
    registry.register(tool)

    result = ToolLayer(registry).execute("echo", value="南京")

    assert result.status == "completed"
    assert result.data == "南京"
    assert tool.arguments == {"value": "南京"}


def test_tool_layer_maps_unavailable_exception() -> None:
    registry = ToolRegistry()
    registry.register(UnavailableTool())

    result = ToolLayer(registry).execute("weather", location="南京")

    assert result.status == "unavailable"
    assert result.message == "天气服务暂不可用"


def test_tool_layer_maps_unexpected_exception_without_leaking_details() -> None:
    registry = ToolRegistry()
    registry.register(BrokenTool())

    result = ToolLayer(registry).execute("broken")

    assert result.status == "failed"
    assert result.error_code == "tool_execution_failed"
    assert result.message == "Tool execution failed"
    assert "内部细节" not in result.message


def test_unknown_tool_returns_failed_result() -> None:
    result = ToolLayer(ToolRegistry()).execute("missing")

    assert result.status == "failed"
    assert result.error_code == "tool_not_found"

\n