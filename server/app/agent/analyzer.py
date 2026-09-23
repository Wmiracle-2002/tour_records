"""Requirement Analyzer boundary for structured LLM output."""

import re
from contextlib import nullcontext
from datetime import date
from typing import Any, Callable, Protocol

from app.agent.budget import AgentBudget
from app.agent.models import TravelRequirement
from app.agent.prompts.requirement_analyzer import (
    REQUIREMENT_ANALYZER_SYSTEM_PROMPT,
)


class StructuredOutputClient(Protocol):
    """提供 Pydantic 结构化输出的 LLM 客户端接口。"""

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[TravelRequirement],
    ) -> TravelRequirement | dict[str, Any]: ...


_HISTORY_DESTINATION_PATTERN = re.compile(
    r"(?:\u53bb\u8fc7\u7684|\u6ca1\u6709\u53bb\u8fc7|\u6ca1\u53bb\u8fc7|\u53bb\u8fc7|\u5728)"
    r"\s*([\u4e00-\u9fff]{2,12}?)"
    r"(?=\s*(?:\u54ea\u4e9b|\u54ea\u51e0|\u54ea\u4e00\u4e9b|\u4ec0\u4e48|\u5417|\u5462|$))"
)


def _infer_history_destination(user_query: str) -> str | None:
    match = _HISTORY_DESTINATION_PATTERN.search(user_query)
    return match.group(1) if match else None


class RequirementAnalyzer:
    """调用结构化输出客户端，把用户请求转换为旅行需求。"""

    def __init__(
        self,
        client: StructuredOutputClient,
        budget: AgentBudget | None = None,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self._client = client
        self._budget = budget
        self._today_provider = today_provider

    def analyze(self, user_query: str) -> TravelRequirement:
        """分析用户请求；缺失字段由结构化模型保留为空。"""
        query = user_query.strip()
        if not query:
            raise ValueError("User query must not be blank")

        with (
            self._budget.stage("requirement_analyzer")
            if self._budget
            else nullcontext()
        ):
            output = self._client.complete_structured(
                system_prompt=(
                    f"{REQUIREMENT_ANALYZER_SYSTEM_PROMPT}\n\n"
                    f"当前日期：{self._today_provider().isoformat()}。"
                ),
                user_prompt=query,
                output_model=TravelRequirement,
            )
        requirement = TravelRequirement.model_validate(output)
        if requirement.intent == "history_query" and not requirement.destination:
            destination = _infer_history_destination(query)
            if destination:
                requirement = requirement.model_copy(update={"destination": destination})
        return requirement
