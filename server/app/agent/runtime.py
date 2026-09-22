"""Production assembly for one isolated Travel Agent run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.analyzer import RequirementAnalyzer
from app.agent.collector import TOOL_INFORMATION_NEEDS, ReActCollector
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
    current_request_id,
    request_context,
)
from app.agent.reviser import LocalItineraryReviser
from app.agent.response import FinalResponseGenerator
from app.agent.tools.amap import AmapTransport, create_amap_tools_from_settings
from app.agent.tools.budget import create_budget_tools
from app.agent.tools.internal import create_internal_db_tools
from app.agent.tools.layer import ToolLayer, ToolRegistry
from app.agent.validator import ItineraryValidator
from app.core.config import Settings, get_settings


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

    def run(self, message: str, user_id: int, db: Session) -> AgentRunResult:
        """为当前用户组装工具并执行完整 LangGraph。"""
        registry = ToolRegistry()
        for tool in create_internal_db_tools(db, user_id):
            registry.register(tool)
        for tool in create_budget_tools():
            registry.register(tool)
        for tool in create_amap_tools_from_settings(
            self._settings,
            transport=self._amap_transport,
        ):
            if tool.name in TOOL_INFORMATION_NEEDS:
                registry.register(tool)

        analyzer = RequirementAnalyzer(self._llm_client)
        collector = ReActCollector(
            ToolLayer(registry),
            LLMReActDecisionClient(self._llm_client),
            observer=self._observer,
        )
        graph = build_agent_graph(
            analyzer=analyzer,
            collector=collector,
            itinerary_generator=StructuredItineraryGenerator(self._llm_client),
            validator=ItineraryValidator(),
            reviser=LocalItineraryReviser(self._llm_client),
            response_generator=FinalResponseGenerator(),
            observer=self._observer,
        )

        request_id = current_request_id() or str(uuid4())
        initial = make_initial_state(
            message,
            request_id=request_id,
            user_id=user_id,
        )
        with request_context(request_id):
            result = graph.invoke(initial)
        answer = result.get("final_response")
        if not isinstance(answer, str):
            raise ValueError("Agent graph did not produce a final response")
        return AgentRunResult(request_id=initial["request_id"], answer=answer)
