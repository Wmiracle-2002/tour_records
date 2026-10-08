"""Production assembly for one isolated Travel Agent run."""

from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.budget import AgentBudget, current_cancellation
from app.agent.analyzer import RequirementAnalyzer
from app.agent.collector import ReActCollector
from app.agent.factual import FactualAnswerer
from app.agent.generator import StructuredItineraryGenerator
from app.agent.graph import build_agent_graph, make_initial_state
from app.agent.llm import (
    LLMReActDecisionClient,
    OpenAICompatibleTransport,
    StructuredLLMClient,
)
from app.agent.observability import (
    AgentObserver,
    StructuredLoggingObserver,
    StreamingAgentObserver,
    current_preview_sink,
    current_stream_event_sink,
    current_request_id,
    request_context,
)
from app.agent.memory import (
    ConversationMemoryService,
    ConversationSummaryOutput,
    ToolRunSnapshot,
)
from app.agent.knowledge import resolve_city_code, search_knowledge
from app.agent.models import KnowledgeInfo
from app.agent.reviser import LocalItineraryReviser
from app.agent.response import FinalResponseGenerator
from app.agent.tools.amap import AmapTransport, AmapWebClient, create_amap_tools_from_settings
from app.agent.tools.budget import create_budget_tools
from app.agent.tools.internal import create_internal_db_tools
from app.agent.tools.layer import ToolLayer, ToolRegistry
from app.agent.validator import ItineraryValidator
from app.core.config import Settings, get_settings
from app.models import UserPreference


logger = logging.getLogger("footmarks.agent.memory")


class _RecordingAmapClient:
    """Record the normalized results of AMap calls made outside ReAct tools."""

    def __init__(self, client: AmapWebClient, record) -> None:
        self._client = client
        self._record = record

    def search_verified_pois(self, city, kind, place_name=None):
        arguments = {"city": city.strip(), "kind": kind}
        if place_name is not None:
            arguments["place_name"] = place_name.strip()
        return self._run(
            "keyword_search",
            arguments,
            lambda: self._client.search_verified_pois(city, kind, place_name),
        )

    def resolve_adcode(self, city):
        return self._run(
            "administrative_division_lookup",
            {"city": city.strip()},
            lambda: self._client.resolve_adcode(city),
        )

    def weather_adcode(self, adcode, *, forecast):
        return self._run(
            "weather",
            {"adcode": adcode, "forecast": forecast},
            lambda: self._client.weather_adcode(adcode, forecast=forecast),
        )

    def measure_distance(self, origin, destination, *, mode):
        return self._run(
            "distance",
            {"origin": origin, "destination": destination, "mode": mode},
            lambda: self._client.measure_distance(origin, destination, mode=mode),
        )

    def _run(self, name, arguments, operation):
        started_at = monotonic()
        try:
            result = operation()
        except Exception as error:
            self._record(ToolRunSnapshot(
                tool_name=name,
                executed_arguments=arguments,
                status="failed",
                summary_text=str(error)[:2000],
                result_json={"error": str(error)[:2000]},
                error_code=type(error).__name__,
                duration_ms=(monotonic() - started_at) * 1000,
            ))
            raise
        data = result if isinstance(result, (dict, list)) else (
            {"meters": result} if name == "distance" else {"value": result}
        )
        self._record(ToolRunSnapshot(
            tool_name=name,
            executed_arguments=arguments,
            status="completed",
            summary_text=_direct_tool_summary(data),
            result_json=data,
            duration_ms=(monotonic() - started_at) * 1000,
        ))
        return result


def _direct_tool_summary(data: Any) -> str:
    allowed_keys = {
        "city", "adcode", "date", "name", "weather", "temperature",
        "dayweather", "nightweather", "distance", "meters", "count",
    }
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in allowed_keys and isinstance(item, (str, int, float)):
                    values.append(f"{key}={str(item)[:100]}")
                elif key == "pois" and isinstance(item, list):
                    names = [poi.get("name") for poi in item[:5] if isinstance(poi, dict)]
                    values.extend(f"name={name[:100]}" for name in names if isinstance(name, str))
                    values.append(f"count={len(item)}")
                elif isinstance(item, (dict, list)):
                    collect(item)
        elif isinstance(value, list):
            for item in value[:10]:
                collect(item)

    collect(data)
    return "；".join(dict.fromkeys(values))[:2000] or json.dumps(
        data, ensure_ascii=False, separators=(",", ":")
    )[:2000]


class AgentRunResult(BaseModel):
    """一次 Agent 运行对外返回的最小结果。"""

    request_id: str
    answer: str


class AgentRuntime:
    """组装并执行一轮带用户数据隔离的 Travel Agent。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm_client: Any | None = None,
        observer: AgentObserver | None = None,
        amap_transport: AmapTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._observer = observer or StructuredLoggingObserver()
        self._llm_client = llm_client or StructuredLLMClient(
            OpenAICompatibleTransport(self._settings)
        )
        self._amap_transport = amap_transport

    def run(
        self,
        message: str,
        user_id: int,
        db: Session,
        *,
        conversation_id: str | None = None,
        user_message_id: int | None = None,
    ) -> AgentRunResult:
        """为当前用户组装工具并执行完整 LangGraph。"""
        budget = AgentBudget(
            total_timeout_seconds=self._settings.agent_total_timeout_seconds,
            stage_timeout_seconds=self._settings.agent_stage_timeout_seconds,
            cancellation=current_cancellation(),
        )
        memory_service = None
        memory_context = None
        if conversation_id is not None and user_message_id is not None:
            memory_service = ConversationMemoryService(
                db, user_id, conversation_id, user_message_id
            )
            memory_context = memory_service.build_context(
                message,
                summarize=lambda source: self._summarize_memory(source, budget),
            )
        long_term_preferences = [
            {"category": preference.category, "content": preference.content}
            for preference in db.scalars(
                select(UserPreference)
                .where(UserPreference.user_id == user_id)
                .order_by(UserPreference.category)
            ).all()
        ]

        def record_tool_run(snapshot: ToolRunSnapshot) -> None:
            if memory_service is None or user_message_id is None:
                return
            try:
                memory_service.record_tool_run(user_message_id, snapshot)
            except Exception:
                db.rollback()
                logger.exception("Could not persist Agent tool run")

        registry = ToolRegistry()
        observer = (
            StreamingAgentObserver(self._observer)
            if current_stream_event_sink() is not None
            else self._observer
        )
        for tool in create_internal_db_tools(db, user_id):
            registry.register(tool)
        for tool in create_budget_tools():
            registry.register(tool)
        for tool in create_amap_tools_from_settings(
            self._settings,
            transport=self._amap_transport,
        ):
            if tool.name == "keyword_search":
                registry.register(tool)

        analyzer = RequirementAnalyzer(self._llm_client, budget=budget)
        collector = ReActCollector(
            ToolLayer(registry),
            LLMReActDecisionClient(self._llm_client),
            observer=observer,
            budget=budget,
            tool_run_recorder=record_tool_run,
        )
        amap_client = _RecordingAmapClient(AmapWebClient(
            self._settings.amap_web_key,
            base_url=self._settings.amap_base_url,
            timeout_seconds=self._settings.amap_timeout_seconds,
            transport=self._amap_transport,
        ), record_tool_run)
        graph = build_agent_graph(
            analyzer=analyzer,
            collector=collector,
            itinerary_generator=StructuredItineraryGenerator(
                self._llm_client, budget=budget,
                on_preview=current_preview_sink(),
            ),
            validator=ItineraryValidator(),
            reviser=LocalItineraryReviser(self._llm_client, budget=budget),
            response_generator=FinalResponseGenerator(),
            observer=observer,
            factual_answerer=FactualAnswerer(
                amap_client, tool_run_recorder=record_tool_run
            ),
            planning_poi_client=amap_client,
            tool_run_recorder=record_tool_run,
            knowledge_searcher=lambda city, preferences: self._search_knowledge(
                db, user_id, city, preferences
            ),
        )

        request_id = current_request_id() or str(uuid4())
        initial = make_initial_state(
            message,
            request_id=request_id,
            user_id=user_id,
            conversation_context=(
                memory_context.prompt_context if memory_context is not None else None
            ),
            session_memory_state=(
                memory_context.session_state.model_dump(exclude_none=True)
                if memory_context is not None
                else None
            ),
            long_term_preferences=long_term_preferences,
        )
        with request_context(request_id):
            result = graph.invoke(initial)
        answer = result.get("final_response")
        if not isinstance(answer, str):
            raise ValueError("Agent graph did not produce a final response")
        if memory_service is not None and user_message_id is not None:
            memory_service.save_requirement(
                user_message_id,
                message,
                result["requirement"],
            )
        return AgentRunResult(request_id=initial["request_id"], answer=answer)

    @staticmethod
    def _search_knowledge(
        db: Session, user_id: int, city: str, preferences: list[str],
    ) -> list[KnowledgeInfo]:
        city_code = resolve_city_code(city)
        if city_code is None:
            return []
        rows = search_knowledge(db, user_id, city_code, keywords=preferences)
        if not rows and preferences:
            rows = search_knowledge(db, user_id, city_code)
        return [KnowledgeInfo.model_validate(row.__dict__) for row in rows]

    def _summarize_memory(self, source: str, budget: AgentBudget) -> str:
        with budget.stage("conversation_memory_summary"):
            summary = self._llm_client.complete_structured(
                system_prompt=(
                    "你负责压缩同一旅行对话中的早期原文。只保留用户明确确认的主题、城市、日期、天数、"
                    "预算、偏好、限制和更正；不要编造，不要保留过期工具数据为当前事实。"
                    "完整原文仍可按 message_id 回查。只返回简短的结构化摘要。"
                ),
                user_prompt=source,
                output_model=ConversationSummaryOutput,
            )
        return summary.summary
