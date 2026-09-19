from typing import Any

import pytest

from app.agent.collector import (
    ReActContext,
    ReActDecision,
    ToolCall,
    ToolDescriptor,
)
from app.agent.llm import LLMInvalidResponseError, LLMReActDecisionClient
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
            destination="南京",
        ),
        information_status=InformationStatus(
            weather=InfoRequirement(status="pending", critical=True),
        ),
        collected_info=CollectedInfo(),
        available_tools=[ToolDescriptor(name=tool_name, description="查询天气")],
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
