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

_DISTANCE_QUESTION_PATTERN = re.compile(r"多远|距离|相距|(?:多少|几)(?:公里|千米|米)")
_CURRENT_WEATHER_WORDS = ("现在", "当前", "此刻", "目前", "实时")


def _current_weather_word(query: str) -> str | None:
    if any(word in query for word in ("明天", "后天", "今晚", "未来", "中秋", "国庆", "到", "至")):
        return None
    if re.search(r"\d{4}[-年/]\d{1,2}|\d{1,2}月\d{1,2}日", query):
        return None
    return next((word for word in _CURRENT_WEATHER_WORDS if word in query), None)


def _explicit_poi_kind(query: str) -> str | None:
    food = any(word in query for word in ("美食", "餐厅", "餐馆", "饭店", "小吃", "吃什么"))
    attraction = any(word in query for word in ("景点", "风景", "游玩", "好玩", "景区"))
    if food and attraction:
        return "both"
    if food:
        return "food"
    if attraction:
        return "attraction"
    return None


def _infer_history_city(user_query: str) -> str | None:
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
        if requirement.intent == "route_query" and _DISTANCE_QUESTION_PATTERN.search(query):
            requirement = requirement.model_copy(update={"intent": "distance_query"})
        if requirement.intent == "poi_recommendation":
            kind = _explicit_poi_kind(query)
            if kind is not None:
                requirement = requirement.model_copy(update={"poi_kind": kind})
        if requirement.intent == "weather_query":
            current_word = _current_weather_word(query)
            if current_word is not None:
                requirement = requirement.model_copy(update={
                    "weather_time_kind": "realtime",
                    "date_expression": current_word,
                    "start_date": None,
                    "end_date": None,
                })
        if requirement.intent == "history_query" and not requirement.city:
            city = _infer_history_city(query)
            if city:
                requirement = requirement.model_copy(update={"city": city})
        return requirement
