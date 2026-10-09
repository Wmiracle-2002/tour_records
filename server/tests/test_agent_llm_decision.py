from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.collector import (
    ReActContext,
    ReActDecision,
    ToolCall,
    ToolDescriptor,
)
from app.agent.tools.amap import WeatherInput
from app.agent.llm import (
    REACT_DECISION_SYSTEM_PROMPT,
    LLMInvalidResponseError,
    LLMReActDecisionClient,
)
from app.agent.models import (
    CollectedInfo,
    InfoRequirement,
    InformationStatus,
    TravelRequirement,
)


class FakeStructuredClient:
    def __init__(self, output: ReActDecision) -> None:
        self.output = output
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None
        self.output_model: type[Any] | None = None

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Any],
    ) -> ReActDecision:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.output_model = output_model
        return self.output


def weather_context(*, tool_name: str = "weather") -> ReActContext:
    return ReActContext(
        requirement=TravelRequirement(
            intent="weather_query",
            city="南京",
        ),
        information_status=InformationStatus(
            weather=InfoRequirement(status="pending", critical=True),
        ),
        collected_info=CollectedInfo(),
        available_tools=[
            ToolDescriptor(
                name=tool_name,
                description="查询天气",
                parameters=WeatherInput.model_json_schema(),
                examples=[{"city": "南京", "forecast": True}],
            )
        ],
        react_round=1,
    )


def test_react_client_returns_one_valid_tool_call() -> None:
    structured = FakeStructuredClient(
        ReActDecision(
            tool_call=ToolCall(
                name="weather",
                arguments={"city": "320100", "forecast": True},
            ),
            reason="需要查询目标日期的天气",
        )
    )

    decision = LLMReActDecisionClient(structured).decide(weather_context())

    assert decision.tool_call is not None
    assert decision.tool_call.name == "weather"
    assert decision.tool_call.arguments == {"city": "320100", "forecast": True}
    assert structured.output_model is ReActDecision
    assert '"weather_query"' in (structured.user_prompt or "")
    assert "available_tools" in (structured.user_prompt or "")


def test_react_client_can_stop_without_tool_call() -> None:
    structured = FakeStructuredClient(ReActDecision(reason="已有足够信息"))

    decision = LLMReActDecisionClient(structured).decide(weather_context())

    assert decision.tool_call is None
    assert decision.reason == "已有足够信息"


def test_react_client_rejects_unknown_tool_name() -> None:
    structured = FakeStructuredClient(
        ReActDecision(tool_call=ToolCall(name="delete_all_records"))
    )

    with pytest.raises(LLMInvalidResponseError, match="unavailable tool"):
        LLMReActDecisionClient(structured).decide(weather_context())


def test_react_client_prompt_does_not_request_chain_of_thought() -> None:
    structured = FakeStructuredClient(ReActDecision())

    LLMReActDecisionClient(structured).decide(weather_context())

    prompt = structured.system_prompt or ""
    assert "不要输出思维链" in prompt
    assert "请详细展示思维链" not in prompt
    assert "show your chain of thought" not in prompt.lower()
    assert "最多返回一个 Tool Call" in prompt


def test_react_client_prompt_declares_exact_decision_shape() -> None:
    structured = FakeStructuredClient(ReActDecision())

    LLMReActDecisionClient(structured).decide(weather_context())

    prompt = structured.system_prompt or ""
    assert "根对象只能包含 tool_call 和 reason" in prompt
    assert "不要使用 decision 字段包裹" in prompt
    assert "arguments 必须是对象" in prompt
    assert "information_need" in prompt
    assert "critical" in prompt
    assert "Tool 的 parameters 是执行时的硬 Schema" in prompt


def test_tool_call_rejects_system_control_fields_from_llm() -> None:
    with pytest.raises(ValidationError):
        ReActDecision.model_validate(
            {
                "tool_call": {
                    "name": "weather",
                    "arguments": {"city": "南京"},
                    "information_need": "history",
                    "critical": False,
                }
            }
        )


def test_react_prompt_distinguishes_history_tools() -> None:
    assert "询问去过哪些城市、景点或美食" in REACT_DECISION_SYSTEM_PROMPT
