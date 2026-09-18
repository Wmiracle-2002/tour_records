"""Requirement Analyzer boundary for structured LLM output."""

from typing import Any, Protocol

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


class RequirementAnalyzer:
    """调用结构化输出客户端，把用户请求转换为旅行需求。"""

    def __init__(self, client: StructuredOutputClient) -> None:
        self._client = client

    def analyze(self, user_query: str) -> TravelRequirement:
        """分析用户请求；缺失字段由结构化模型保留为空。"""
        query = user_query.strip()
        if not query:
            raise ValueError("User query must not be blank")

        output = self._client.complete_structured(
            system_prompt=REQUIREMENT_ANALYZER_SYSTEM_PROMPT,
            user_prompt=query,
            output_model=TravelRequirement,
        )
        return TravelRequirement.model_validate(output)

\n