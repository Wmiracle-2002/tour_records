"""Minimal workflow for non-itinerary Agent requests."""

from __future__ import annotations

from time import monotonic
from uuid import uuid4

from app.agent.analyzer import RequirementAnalyzer
from app.agent.collector import ReActCollector
from app.agent.information import initialize_information_status
from app.agent.models import CollectedInfo
from app.agent.observability import AgentObserver, emit_event
from app.agent.response import FinalResponseGenerator
from app.agent.state import TravelAgentState


class TravelAgentWorkflow:
    """按固定顺序运行需求分析、信息收集和最终回答节点。"""

    def __init__(
        self,
        analyzer: RequirementAnalyzer,
        collector: ReActCollector,
        response_generator: FinalResponseGenerator,
        observer: AgentObserver | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._collector = collector
        self._response_generator = response_generator
        self._observer = observer

    def run(self, user_query: str) -> TravelAgentState:
        requirement = self._analyzer.analyze(user_query)
        request_id = str(uuid4())
        started_at = monotonic()
        state: TravelAgentState = {
            "messages": [user_query],
            "request_id": request_id,
            "run_started_at": started_at,
            "requirement": requirement,
            "information_status": initialize_information_status(requirement),
            "collected_info": CollectedInfo(),
            "itinerary": None,
            "validation": None,
            "react_round": 0,
            "react_action": "none",
            "validation_round": 0,
            "final_response": None,
        }
        emit_event(
            self._observer,
            event="requirement_ready",
            request_id=request_id,
            intent=requirement.intent,
            node_name="requirement_analyzer",
        )
        state = self._collector.collect(state)
        state["final_response"] = self._response_generator.generate(
            state["requirement"],
            state["collected_info"],
            state["information_status"],
        )
        emit_event(
            self._observer,
            event="final_response_ready",
            request_id=request_id,
            intent=requirement.intent,
            node_name="final_response",
            total_duration_ms=(monotonic() - started_at) * 1000,
        )
        return state
