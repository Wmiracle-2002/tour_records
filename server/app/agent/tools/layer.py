"""Common tool registry, execution boundary, and result semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ToolStatus = Literal["completed", "unavailable", "failed"]
T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    """所有工具统一返回的结果。"""

    status: ToolStatus
    data: T | None = None
    message: str | None = None
    error_code: str | None = None
    details: dict[str, Any] | None = None

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
    def failed(
        cls,
        message: str,
        error_code: str = "tool_failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> ToolResult[T]:
        """创建工具执行失败结果。"""
        return cls(
            status="failed",
            message=message,
            error_code=error_code,
            details=details,
        )


class ToolUnavailableError(RuntimeError):
    """工具依赖的外部服务暂时不可用。"""


class DuplicateToolError(ValueError):
    """注册表中已经存在同名工具。"""


class ToolNotFoundError(LookupError):
    """注册表中找不到指定名称的工具。"""


class ToolInputModel(BaseModel):
    """Agent Tool 输入模型的严格基类。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyToolInput(ToolInputModel):
    """不接收参数的 Tool 输入。"""


@dataclass(frozen=True)
class ToolDefinition:
    """工具运行契约和供 LLM 使用的参数说明。"""

    name: str
    description: str
    information_need: str
    input_model: type[BaseModel]
    examples: tuple[dict[str, Any], ...] = ()


class ToolArgumentError(BaseModel):
    """向 ReAct 决策器反馈的一次安全参数错误。"""

    tool_name: str
    error_code: Literal["invalid_tool_arguments"] = "invalid_tool_arguments"
    invalid_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    expected_schema_summary: dict[str, Any]
    retryable: Literal[True] = True
    attempt: int = Field(ge=1)


class AgentTool(Protocol):
    """Agent 可以调用的最小工具接口。"""

    name: str
    description: str
    input_model: type[BaseModel]
    information_need: str
    examples: tuple[dict[str, Any], ...]

    def run(self, **arguments: Any) -> ToolResult[Any]: ...


class ToolRegistry:
    """按工具名称管理可供 Agent 使用的工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, tool: AgentTool) -> None:
        if not tool.name.strip():
            raise ValueError("Tool name must not be blank")
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool already registered: {tool.name}")
        input_model = getattr(tool, "input_model", None)
        information_need = getattr(tool, "information_need", None)
        if not isinstance(input_model, type) or not issubclass(input_model, BaseModel):
            raise ValueError(f"Tool {tool.name} must declare an input_model")
        if not isinstance(information_need, str) or not information_need:
            raise ValueError(f"Tool {tool.name} must declare an information_need")
        self._tools[tool.name] = tool
        self._definitions[tool.name] = ToolDefinition(
            name=tool.name,
            description=tool.description,
            information_need=information_need,
            input_model=input_model,
            examples=tuple(getattr(tool, "examples", ())),
        )

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"Tool not found: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return registered input contracts for the Agent decision context."""
        return tuple(self._definitions.values())

    def definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise ToolNotFoundError(f"Tool not found: {name}") from error


class ToolLayer:
    """统一查找并执行工具，将异常转换为 ToolResult。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._registry.definitions()

    def information_need(self, name: str) -> str:
        return self._registry.definition(name).information_need

    def definition(self, name: str) -> ToolDefinition:
        return self._registry.definition(name)

    def execute(self, name: str, **arguments: Any) -> ToolResult[Any]:
        try:
            tool = self._registry.get(name)
            definition = self._registry.definition(name)
        except ToolNotFoundError as error:
            return ToolResult.failed(str(error), error_code="tool_not_found")

        try:
            validated = definition.input_model.model_validate(arguments)
        except ValidationError as error:
            invalid_fields: set[str] = set()
            missing_fields: set[str] = set()
            for item in error.errors(include_input=False):
                field_path = ".".join(str(part) for part in item["loc"])
                if item["type"] == "missing":
                    missing_fields.add(field_path)
                else:
                    invalid_fields.add(field_path)
            details = {
                "tool_name": name,
                "invalid_fields": sorted(invalid_fields),
                "missing_fields": sorted(missing_fields),
            }
            fields = sorted(invalid_fields | missing_fields)
            return ToolResult.failed(
                f"Tool arguments failed validation: {', '.join(fields) or 'unknown field'}",
                error_code="invalid_tool_arguments",
                details=details,
            )

        try:
            result = tool.run(**validated.model_dump(exclude_unset=True))
        except ToolUnavailableError as error:
            return ToolResult.unavailable(str(error))
        except Exception:
            return ToolResult.failed(
                "Tool execution failed", error_code="tool_execution_error"
            )

        if not isinstance(result, ToolResult):
            return ToolResult.failed(
                "Tool returned an invalid result", error_code="invalid_tool_result"
            )
        return result
