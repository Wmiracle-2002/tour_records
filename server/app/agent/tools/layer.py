"""Common tool registry, execution boundary, and result semantics."""

from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel


ToolStatus = Literal["completed", "unavailable", "failed"]
T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    """所有工具统一返回的结果。"""

    status: ToolStatus
    data: T | None = None
    message: str | None = None
    error_code: str | None = None

    @classmethod
    def completed(cls, data: T, message: str | None = None) -> ToolResult[T]:
        """创建成功结果。"""
        return cls(status="completed", data=data, message=message)

    @classmethod
    def unavailable(
        cls, message: str, error_code: str = "tool_unavailable"
    ) -> ToolResult[T]:
        """创建暂时无法获得数据的结果。"""
        return cls(status="unavailable", message=message, error_code=error_code)

    @classmethod
    def failed(cls, message: str, error_code: str = "tool_failed") -> ToolResult[T]:
        """创建工具执行失败结果。"""
        return cls(status="failed", message=message, error_code=error_code)


class ToolUnavailableError(RuntimeError):
    """工具依赖的外部服务暂时不可用。"""


class DuplicateToolError(ValueError):
    """注册表中已经存在同名工具。"""


class ToolNotFoundError(LookupError):
    """注册表中找不到指定名称的工具。"""


class AgentTool(Protocol):
    """Agent 可以调用的最小工具接口。"""

    name: str
    description: str

    def run(self, **arguments: Any) -> ToolResult[Any]: ...


class ToolRegistry:
    """按工具名称管理可供 Agent 使用的工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if not tool.name.strip():
            raise ValueError("Tool name must not be blank")
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"Tool not found: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def descriptions(self) -> tuple[tuple[str, str], ...]:
        """返回工具名称和说明，供 ReAct 决策上下文使用。"""
        return tuple(
            (name, tool.description) for name, tool in self._tools.items()
        )


class ToolLayer:
    """统一查找并执行工具，将异常转换为 ToolResult。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def descriptions(self) -> tuple[tuple[str, str], ...]:
        """返回可供 ReAct 决策使用的工具说明。"""
        return self._registry.descriptions()

    def execute(self, name: str, **arguments: Any) -> ToolResult[Any]:
        try:
            tool = self._registry.get(name)
        except ToolNotFoundError as error:
            return ToolResult.failed(str(error), error_code="tool_not_found")

        try:
            result = tool.run(**arguments)
        except ToolUnavailableError as error:
            return ToolResult.unavailable(str(error))
        except Exception:
            return ToolResult.failed(
                "Tool execution failed", error_code="tool_execution_failed"
            )

        if not isinstance(result, ToolResult):
            return ToolResult.failed(
                "Tool returned an invalid result", error_code="invalid_tool_result"
            )
        return result
