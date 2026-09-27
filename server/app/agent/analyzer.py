"""Requirement Analyzer boundary for structured LLM output."""

import re
import json
from contextlib import nullcontext
from datetime import date
from typing import Any, Callable, Protocol

from app.agent.budget import AgentBudget
from app.agent.models import TravelRequirement
from app.agent.memory import ConversationSessionState, is_referential_follow_up
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

    def analyze(
        self,
        user_query: str,
        *,
        conversation_context: str | None = None,
        session_state: ConversationSessionState | dict[str, Any] | None = None,
        long_term_preferences: list[dict[str, str]] | None = None,
    ) -> TravelRequirement:
        """分析用户请求；缺失字段由结构化模型保留为空。"""
        query = user_query.strip()
        if not query:
            raise ValueError("User query must not be blank")

        structured_state = (
            ConversationSessionState.model_validate(session_state)
            if session_state is not None
            else ConversationSessionState()
        )
        prompt = query
        if conversation_context:
            prompt = (
                "【同一会话的相关记忆】\n"
                f"{conversation_context}\n\n"
                "【当前用户消息（以此为准）】\n"
                f"{query}"
            )
        if long_term_preferences:
            encoded_preferences = json.dumps(
                long_term_preferences, ensure_ascii=False, separators=(",", ":")
            )
            prompt = (
                "【用户明确保存的长期旅行偏好】\n"
                f"{encoded_preferences}\n"
                "仅用于当前请求的个性化建议；用户当前请求优先。不得把偏好当成地点、天气、费用或旅行史事实。\n\n"
                f"【当前用户消息（以此为准）】\n{prompt}"
            )

        with (
            self._budget.stage("requirement_analyzer")
            if self._budget
            else nullcontext()
        ):
            output = self._client.complete_structured(
                system_prompt=(
                    f"{REQUIREMENT_ANALYZER_SYSTEM_PROMPT}\n\n"
                    f"当前日期：{self._today_provider().isoformat()}。"
                    + (
                        "请先用相关会话状态理解省略的指代；当前用户消息明确给出的城市、日期和要求必须覆盖历史状态。"
                        "旧工具结果仅供回溯，不代表当前天气、地点或价格。"
                        if conversation_context
                        else ""
                    )
                    + (
                        "用户明确保存的长期偏好只能用于个性化建议，当前请求优先；"
                        "不得据此编造 POI、开放时间、价格或旅行史。"
                        if long_term_preferences
                        else ""
                    )
                ),
                user_prompt=prompt,
                output_model=TravelRequirement,
            )
        requirement = TravelRequirement.model_validate(output)
        if long_term_preferences:
            requirement = _apply_long_term_preferences(
                requirement, long_term_preferences, query
            )
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
        if is_referential_follow_up(query):
            inherited: dict[str, Any] = {}
            for field in ("city", "start_date", "end_date", "duration_days", "travelers", "budget"):
                value = getattr(requirement, field)
                previous = getattr(structured_state, field)
                if value is None and previous is not None:
                    if field in {"start_date", "end_date"} and requirement.date_expression:
                        continue
                    inherited[field] = previous
            if inherited:
                requirement = requirement.model_copy(update=inherited)
        return requirement


def _apply_long_term_preferences(
    requirement: TravelRequirement,
    preferences: list[dict[str, str]],
    query: str,
) -> TravelRequirement:
    add_to_preferences = list(requirement.preferences)
    add_to_constraints = list(requirement.constraints)
    category_targets = {
        "food_restriction": add_to_constraints,
        "attraction_interest": add_to_preferences,
        "travel_pace": add_to_preferences,
        "budget_tendency": add_to_preferences,
    }
    for item in preferences:
        category = item.get("category")
        content = item.get("content", "").strip()
        target = category_targets.get(category)
        if not content or target is None or _preference_is_overridden(category, query):
            continue
        if content not in target:
            target.append(content)
    return requirement.model_copy(update={
        "preferences": add_to_preferences,
        "constraints": add_to_constraints,
    })


def _preference_is_overridden(category: str, query: str) -> bool:
    if "这次" not in query and "本次" not in query:
        return False
    if category == "food_restriction":
        return any(word in query for word in ("吃", "饮食", "忌口", "过敏"))
    if category == "attraction_interest":
        return any(word in query for word in ("景点", "博物馆", "古迹", "历史", "自然"))
    if category == "travel_pace":
        return any(word in query for word in ("节奏", "紧凑", "不赶", "悠闲", "多逛"))
    if category == "budget_tendency":
        return any(word in query for word in ("预算", "省钱", "花费", "经济"))
    return False
