"""SQLite-backed, token-bounded memory for one authenticated conversation."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, load_only

from app.agent.models import TravelRequirement
from app.models import (
    AgentConversationMemory,
    AgentConversationSummary,
    AgentToolResult,
    AgentToolRun,
    ChatConversation,
    ChatMessage,
)


logger = logging.getLogger("footmarks.agent.memory")

CONVERSATION_MEMORY_TOKEN_BUDGET = 6000
MEMORY_COMPRESSION_TRIGGER = 0.70
MAX_RECENT_TURNS = 8
MAX_RETRIEVED_MESSAGES = 3
MAX_RETRIEVED_TOKEN_BUDGET = 900
MAX_RELEVANT_SUMMARIES = 4
MAX_TOOL_OVERVIEWS_PER_NAME = 2
MAX_TOOL_OVERVIEWS = 8
SUMMARY_CHUNK_TOKEN_BUDGET = 1400
SUMMARY_OUTPUT_TOKEN_BUDGET = 500
MAX_SUMMARY_CHUNKS_PER_REQUEST = 2

_RECALL_MARKERS = (
    "之前",
    "前面",
    "刚才",
    "刚刚",
    "上次",
    "那家",
    "那个",
    "那条",
    "按我说的",
    "回到",
    "之前提到",
)
_FULL_TOOL_RESULT_MARKERS = (
    "完整结果",
    "具体结果",
    "详细结果",
    "返回数据",
    "调用结果",
    "原始结果",
)
_FOLLOW_UP_MARKERS = (
    "那里",
    "然后",
    "第二天",
    "下一天",
    "美食呢",
    "景点呢",
    "天气呢",
    "预算呢",
    "附近",
    "这家",
    "那个",
    "它",
    "继续",
)
_OVERRIDES = ("这次", "改成", "换成", "不需要", "取消", "不要", "而是")
_STOP_TERMS = {
    "之前", "前面", "刚才", "刚刚", "上次", "那个", "那家", "怎么", "什么",
    "哪里", "哪些", "一下", "帮我", "推荐", "查询", "请问", "这个", "那里",
    "它们", "我们", "你们", "今天", "明天", "附近", "还有", "已经", "说的",
}


class ConversationSessionState(BaseModel):
    """Stable, structured facts for the active topic in a single conversation."""

    topic: str | None = Field(default=None, max_length=240)
    subtopic: str | None = Field(default=None, max_length=240)
    last_intent: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    duration_days: int | None = Field(default=None, ge=1, le=60)
    travelers: int | None = Field(default=None, ge=1, le=100)
    budget: float | None = Field(default=None, ge=0)
    preferences: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    source_message_id: int | None = Field(default=None, ge=1)


class ToolRunSnapshot(BaseModel):
    """A normalized tool execution captured for durable, private traceability."""

    tool_name: str = Field(min_length=1, max_length=100)
    executed_arguments: dict[str, Any] = Field(default_factory=dict)
    called_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["completed", "failed", "unavailable"]
    summary_text: str = Field(default="", max_length=2000)
    result_json: dict[str, Any] | list[Any] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    duration_ms: float | None = Field(default=None, ge=0)


class ConversationSummaryOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)


@dataclass(frozen=True)
class ConversationMemoryContext:
    prompt_context: str
    session_state: ConversationSessionState
    token_estimate: int
    compression_triggered: bool
    retrieved_message_ids: list[int]
    tool_run_ids: list[str]


def estimate_tokens(value: str) -> int:
    """Conservatively estimate tokens without requiring a provider tokenizer."""
    if not value:
        return 0
    return math.ceil(len(value.encode("utf-8")) / 2)


def is_referential_follow_up(query: str) -> bool:
    text = query.strip()
    return text.startswith(("那", "然后", "第二天", "下一天", "继续")) or any(
        marker in text for marker in _FOLLOW_UP_MARKERS
    )


class ConversationMemoryService:
    """Read and update memory only inside the supplied user's conversation."""

    def __init__(
        self,
        db: Session,
        user_id: int,
        conversation_id: str,
        current_message_id: int,
    ) -> None:
        self._db = db
        self._user_id = user_id
        self._conversation_id = conversation_id
        self._current_message_id = current_message_id

    def build_context(
        self,
        current_query: str,
        *,
        summarize: Callable[[str], str] | None = None,
    ) -> ConversationMemoryContext:
        conversation = self._db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == self._conversation_id,
                ChatConversation.user_id == self._user_id,
            )
        )
        if conversation is None:
            raise ValueError("Conversation not found")

        memory = self._memory_row()
        session_state = ConversationSessionState.model_validate(
            memory.state_json if memory is not None else {}
        )
        recent = self._recent_messages()
        recent_ids = {message.id for message in recent}
        cursor = memory.summary_cursor_message_id if memory is not None else None
        unsummarized = list(
            self._db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == self._conversation_id,
                    ChatMessage.id < self._current_message_id,
                    ChatMessage.id > (cursor or 0),
                    ChatMessage.status == "completed",
                )
                .order_by(ChatMessage.id)
            ).all()
        )
        older_unsummarized = [item for item in unsummarized if item.id not in recent_ids]
        summaries = self._summaries()
        tool_runs = self._tool_runs()
        retrieved = self._retrieve_messages(current_query, recent_ids)
        relevant_runs = self._relevant_tool_runs(
            current_query, session_state, tool_runs
        )

        pressure = sum(estimate_tokens(item.content) for item in unsummarized)
        pressure += estimate_tokens(
            session_state.model_dump_json(exclude_none=True)
        )
        pressure += sum(estimate_tokens(item.summary_text) for item in summaries[:4])
        pressure += sum(estimate_tokens(item.summary_text) for item in relevant_runs)
        compression_triggered = False
        if (
            summarize is not None
            and older_unsummarized
            and pressure >= CONVERSATION_MEMORY_TOKEN_BUDGET * MEMORY_COMPRESSION_TRIGGER
        ):
            compression_triggered = self._compress(
                older_unsummarized, memory, summarize
            )
            if compression_triggered:
                memory = self._memory_row()
                session_state = ConversationSessionState.model_validate(
                    memory.state_json if memory is not None else {}
                )
                summaries = self._summaries()

        prompt_context, included_ids, included_tool_ids = self._format_context(
            session_state,
            summaries,
            recent,
            retrieved,
            relevant_runs,
            current_query,
        )
        return ConversationMemoryContext(
            prompt_context=prompt_context,
            session_state=session_state,
            token_estimate=estimate_tokens(prompt_context),
            compression_triggered=compression_triggered,
            retrieved_message_ids=included_ids,
            tool_run_ids=included_tool_ids,
        )

    def save_requirement(
        self,
        user_message_id: int,
        user_query: str,
        requirement: TravelRequirement,
    ) -> ConversationSessionState:
        self._require_owned_conversation()
        memory = self._memory_row()
        previous = ConversationSessionState.model_validate(
            memory.state_json if memory is not None else {}
        )
        follow_up = is_referential_follow_up(user_query)
        state = previous.model_copy(
            update={
                "topic": (
                    previous.topic
                    if follow_up and previous.topic
                    else _topic_for_requirement(requirement)
                ),
                "subtopic": user_query.strip()[:240] if follow_up else None,
                "last_intent": requirement.intent,
                "city": requirement.city or (previous.city if follow_up else None),
                "start_date": requirement.start_date
                or (previous.start_date if follow_up and not requirement.date_expression else None),
                "end_date": requirement.end_date
                or (previous.end_date if follow_up and not requirement.date_expression else None),
                "duration_days": requirement.duration_days
                or (previous.duration_days if follow_up else None),
                "travelers": requirement.travelers
                or (previous.travelers if follow_up else None),
                "budget": requirement.budget
                if requirement.budget is not None
                else (previous.budget if follow_up else None),
                "preferences": requirement.preferences
                or (previous.preferences if follow_up and not any(word in user_query for word in _OVERRIDES) else []),
                "constraints": requirement.constraints
                or (previous.constraints if follow_up and not any(word in user_query for word in _OVERRIDES) else []),
                "source_message_id": user_message_id,
            }
        )
        if memory is None:
            memory = AgentConversationMemory(
                conversation_id=self._conversation_id,
                state_json=state.model_dump(mode="json", exclude_none=True),
            )
            self._db.add(memory)
        else:
            memory.state_json = state.model_dump(mode="json", exclude_none=True)
        self._db.flush()
        return state

    def record_tool_run(
        self,
        source_message_id: int,
        snapshot: ToolRunSnapshot,
    ) -> AgentToolRun:
        conversation = self._require_owned_conversation()
        source = self._db.scalar(
            select(ChatMessage).where(
                ChatMessage.id == source_message_id,
                ChatMessage.conversation_id == self._conversation_id,
                ChatMessage.role == "user",
            )
        )
        if conversation is None or source is None:
            raise ValueError("Tool execution is outside the current conversation")
        row = AgentToolRun(
            id=str(uuid4()),
            conversation_id=self._conversation_id,
            source_message_id=source_message_id,
            tool_name=snapshot.tool_name,
            arguments_json=snapshot.executed_arguments,
            called_at=snapshot.called_at,
            status=snapshot.status,
            summary_text=snapshot.summary_text,
            error_code=snapshot.error_code,
            duration_ms=snapshot.duration_ms,
        )
        self._db.add(row)
        if snapshot.result_json is not None:
            row.tool_result = AgentToolResult(result_json=snapshot.result_json)
        self._db.flush()
        return row

    def get_tool_result(self, tool_run_id: str) -> AgentToolResult | None:
        return self._db.scalar(
            select(AgentToolResult)
            .join(AgentToolRun)
            .join(ChatConversation)
            .where(
                AgentToolResult.tool_run_id == tool_run_id,
                AgentToolRun.conversation_id == self._conversation_id,
                ChatConversation.id == self._conversation_id,
                ChatConversation.user_id == self._user_id,
            )
        )

    def _memory_row(self) -> AgentConversationMemory | None:
        return self._db.scalar(
            select(AgentConversationMemory)
            .join(ChatConversation)
            .where(
                AgentConversationMemory.conversation_id == self._conversation_id,
                ChatConversation.user_id == self._user_id,
            )
        )

    def _require_owned_conversation(self) -> ChatConversation:
        conversation = self._db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == self._conversation_id,
                ChatConversation.user_id == self._user_id,
            )
        )
        if conversation is None:
            raise ValueError("Conversation not found")
        return conversation

    def _recent_messages(self) -> list[ChatMessage]:
        messages = list(
            self._db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == self._conversation_id,
                    ChatMessage.id < self._current_message_id,
                    ChatMessage.status == "completed",
                )
                .order_by(ChatMessage.id.desc())
                .limit(MAX_RECENT_TURNS * 2)
            ).all()
        )
        messages.reverse()
        return messages

    def _summaries(self) -> list[AgentConversationSummary]:
        return list(
            self._db.scalars(
                select(AgentConversationSummary)
                .where(AgentConversationSummary.conversation_id == self._conversation_id)
                .order_by(AgentConversationSummary.id.desc())
                .limit(100)
            ).all()
        )

    def _tool_runs(self) -> list[AgentToolRun]:
        return list(
            self._db.scalars(
                select(AgentToolRun)
                .where(AgentToolRun.conversation_id == self._conversation_id)
                .order_by(AgentToolRun.called_at.desc(), AgentToolRun.id.desc())
                .limit(200)
                .options(
                    load_only(
                        AgentToolRun.id,
                        AgentToolRun.conversation_id,
                        AgentToolRun.source_message_id,
                        AgentToolRun.tool_name,
                        AgentToolRun.arguments_json,
                        AgentToolRun.called_at,
                        AgentToolRun.status,
                        AgentToolRun.summary_text,
                        AgentToolRun.error_code,
                        AgentToolRun.duration_ms,
                    )
                )
            ).all()
        )

    def _retrieve_messages(
        self, query: str, recent_ids: set[int]
    ) -> list[ChatMessage]:
        if not any(marker in query for marker in _RECALL_MARKERS):
            return []
        terms = _search_terms(query)
        if not terms:
            return []
        candidates = list(
            self._db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == self._conversation_id,
                    ChatMessage.id < self._current_message_id,
                    ChatMessage.status == "completed",
                    ChatMessage.id.not_in(recent_ids) if recent_ids else True,
                    or_(*(ChatMessage.content.contains(term, autoescape=True) for term in terms)),
                )
                .order_by(ChatMessage.id.desc())
                .limit(200)
            ).all()
        )
        query_terms = set(terms)
        candidates.sort(
            key=lambda item: (
                -sum(term in item.content for term in query_terms),
                -item.id,
            )
        )
        chosen: list[ChatMessage] = []
        used_tokens = 0
        for item in candidates:
            cost = estimate_tokens(item.content)
            if len(chosen) >= MAX_RETRIEVED_MESSAGES:
                break
            if used_tokens + cost > MAX_RETRIEVED_TOKEN_BUDGET:
                continue
            chosen.append(item)
            used_tokens += cost
        return chosen

    def _relevant_tool_runs(
        self,
        query: str,
        state: ConversationSessionState,
        tool_runs: list[AgentToolRun],
    ) -> list[AgentToolRun]:
        if any(marker in query for marker in _FULL_TOOL_RESULT_MARKERS):
            # A singular request for "the full result" refers to the latest call
            # unless the query contains enough terms to disambiguate elsewhere.
            terms = set(_search_terms(query))
            if not terms or all(term not in " ".join(
                f"{run.tool_name} {run.summary_text} "
                f"{json.dumps(run.arguments_json, ensure_ascii=False)}"
                for run in tool_runs
            ) for term in terms):
                return tool_runs[:1]
        terms = set(_search_terms(query))
        if state.city:
            terms.add(state.city)
        counts: Counter[str] = Counter()
        relevant: list[AgentToolRun] = []
        for run in tool_runs:
            searchable = f"{run.tool_name} {run.summary_text} {json.dumps(run.arguments_json, ensure_ascii=False)}"
            score = sum(term in searchable for term in terms)
            if score == 0:
                continue
            if counts[run.tool_name] >= MAX_TOOL_OVERVIEWS_PER_NAME:
                continue
            relevant.append(run)
            counts[run.tool_name] += 1
            if len(relevant) >= MAX_TOOL_OVERVIEWS:
                break
        return relevant

    def _format_context(
        self,
        state: ConversationSessionState,
        summaries: list[AgentConversationSummary],
        recent: list[ChatMessage],
        retrieved: list[ChatMessage],
        tool_runs: list[AgentToolRun],
        current_query: str,
    ) -> tuple[str, list[int], list[str]]:
        header = (
            "历史只用于理解当前会话指代。当前用户消息优先于历史状态；"
            "过期天气、POI、价格等必须重新查询，不得将旧工具结果当成当前事实。"
        )
        components: list[tuple[str, int | None, str | None]] = []
        if state.model_dump(exclude_none=True):
            components.append(
                (
                    "当前结构化话题状态："
                    + state.model_dump_json(exclude_none=True),
                    None,
                    None,
                )
            )

        terms = set(_search_terms(current_query))
        ranked_summaries = sorted(
            summaries,
            key=lambda item: (
                -sum(term in item.summary_text for term in terms),
                -item.id,
            ),
        )
        if not terms and is_referential_follow_up(current_query):
            ranked_summaries = ranked_summaries[:1]
        elif terms:
            ranked_summaries = [
                item
                for item in ranked_summaries
                if any(term in item.summary_text for term in terms)
            ]
        for summary in ranked_summaries[:MAX_RELEVANT_SUMMARIES]:
            components.append(
                (
                    f"较早摘要（message_id {summary.first_message_id}-{summary.last_message_id}）：{summary.summary_text}",
                    None,
                    None,
                )
            )

        for message in retrieved:
            components.append(
                (
                    f"原文回查 message_id={message.id} role={message.role}：{message.content}",
                    message.id,
                    None,
                )
            )

        full_result_requested = any(marker in current_query for marker in _FULL_TOOL_RESULT_MARKERS)
        for run in tool_runs:
            reference = f"tool_run_id={run.id}"
            full_result = self.get_tool_result(run.id) if full_result_requested else None
            details = (
                "；完整结果：" + json.dumps(full_result.result_json, ensure_ascii=False)
                if full_result is not None
                else ""
            )
            overview = (
                f"历史工具调用 {reference}：{run.tool_name}，"
                f"参数={json.dumps(run.arguments_json, ensure_ascii=False)}，"
                f"状态={run.status}，概述={run.summary_text}{details}"
            )
            components.append((overview, None, run.id))

        # Add the newest exchanges first, then restore their chronological order.
        for message in reversed(recent):
            components.append(
                (f"近期 {message.role} message_id={message.id}：{message.content}", message.id, None)
            )

        lines = [header]
        retrieved_ids: list[int] = []
        tool_ids: list[str] = []
        for component, message_id, tool_run_id in components:
            remaining = CONVERSATION_MEMORY_TOKEN_BUDGET - estimate_tokens("\n".join(lines))
            if remaining <= 0:
                break
            if estimate_tokens(component) > remaining:
                component = _truncate_to_tokens(component, remaining)
            if not component:
                continue
            lines.append(component)
            if message_id is not None and component.startswith("原文回查"):
                retrieved_ids.append(message_id)
            if tool_run_id is not None:
                tool_ids.append(tool_run_id)
        recent_lines = [line for line in lines[1:] if line.startswith("近期 ")]
        other_lines = [line for line in lines[1:] if not line.startswith("近期 ")]
        context = _truncate_to_tokens(
            "\n".join([lines[0], *other_lines, *reversed(recent_lines)]),
            CONVERSATION_MEMORY_TOKEN_BUDGET,
        )
        return context, retrieved_ids, tool_ids

    def _compress(
        self,
        messages: list[ChatMessage],
        memory: AgentConversationMemory | None,
        summarize: Callable[[str], str],
    ) -> bool:
        chunks = _summary_chunks(messages)[:MAX_SUMMARY_CHUNKS_PER_REQUEST]
        pending: list[AgentConversationSummary] = []
        chunk_counts: Counter[tuple[int, int]] = Counter()
        latest_message_id: int | None = None
        for chunk in chunks:
            first_id = chunk[0][0]
            last_id = chunk[-1][0]
            chunk_key = (first_id, last_id)
            chunk_index = chunk_counts[chunk_key]
            chunk_counts[chunk_key] += 1
            source = "\n".join(
                f"message_id={message_id} role={role}: {content}"
                for message_id, role, content in chunk
            )
            try:
                summary_text = summarize(source).strip()
            except Exception as error:
                logger.warning("Conversation memory summary failed type=%s", type(error).__name__)
                return False
            if not summary_text:
                logger.warning("Conversation memory summary returned empty text")
                return False
            summary_text = _truncate_to_tokens(summary_text, SUMMARY_OUTPUT_TOKEN_BUDGET)
            pending.append(
                AgentConversationSummary(
                    conversation_id=self._conversation_id,
                    first_message_id=first_id,
                    last_message_id=last_id,
                    chunk_index=chunk_index,
                    summary_text=summary_text,
                    token_estimate=estimate_tokens(summary_text),
                    version=1,
                )
            )
            latest_message_id = last_id

        if not pending or latest_message_id is None:
            return False
        if memory is None:
            memory = AgentConversationMemory(
                conversation_id=self._conversation_id,
                state_json={},
            )
            self._db.add(memory)
        self._db.add_all(pending)
        memory.summary_cursor_message_id = latest_message_id
        self._db.flush()
        logger.info(
            "Conversation memory compressed conversation_id=%s message_count=%d chunks=%d",
            self._conversation_id,
            len(messages),
            len(pending),
        )
        return True


def _topic_for_requirement(requirement: TravelRequirement) -> str:
    labels = {
        "trip_planning": "旅行规划",
        "poi_recommendation": "地点推荐",
        "distance_query": "距离查询",
        "route_query": "路线咨询",
        "weather_query": "天气查询",
        "budget_query": "预算估算",
        "history_query": "旅行记录查询",
        "general_query": "旅行咨询",
    }
    parts = [part for part in (requirement.city, labels.get(requirement.intent)) if part]
    if requirement.duration_days is not None:
        parts.append(f"{requirement.duration_days}天")
    if requirement.start_date:
        date_range = requirement.start_date
        if requirement.end_date and requirement.end_date != requirement.start_date:
            date_range += f"至{requirement.end_date}"
        parts.append(date_range)
    return " · ".join(parts)[:240] or labels["general_query"]


def _search_terms(text: str) -> list[str]:
    terms: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            if len(chunk) >= 2 and chunk not in _STOP_TERMS:
                terms.append(chunk)
            terms.extend(
                pair for pair in (chunk[index : index + 2] for index in range(len(chunk) - 1))
                if pair not in _STOP_TERMS
            )
        elif len(chunk) >= 2 and chunk not in _STOP_TERMS:
            terms.append(chunk)
    return list(dict.fromkeys(terms))[:16]


def _summary_chunks(
    messages: list[ChatMessage],
) -> list[list[tuple[int, str, str]]]:
    chunks: list[list[tuple[int, str, str]]] = []
    current: list[tuple[int, str, str]] = []
    current_tokens = 0
    max_chars = SUMMARY_CHUNK_TOKEN_BUDGET // 2
    for message in messages:
        content = message.content[:max_chars]
        if len(message.content) > max_chars:
            content += "［此消息摘要只读取前段，完整内容可按该 message_id 回查］"
        record = (message.id, message.role, content)
        cost = estimate_tokens(content) + 20
        if current and current_tokens + cost > SUMMARY_CHUNK_TOKEN_BUDGET:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(record)
        current_tokens += cost
    if current:
        chunks.append(current)
    return chunks


def _truncate_to_tokens(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    max_bytes = token_budget * 2
    result = text.encode("utf-8")[:max_bytes]
    while result:
        try:
            candidate = result.decode("utf-8") + "…"
            if estimate_tokens(candidate) <= token_budget:
                return candidate
            result = result[:-1]
        except UnicodeDecodeError:
            result = result[:-1]
    return ""
