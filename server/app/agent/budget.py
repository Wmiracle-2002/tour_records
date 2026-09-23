"""Shared time budget for one synchronous Agent request."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Iterator


_LLM_DEADLINE: ContextVar[tuple[float, Callable[[], float]] | None] = ContextVar(
    "agent_llm_timeout_seconds", default=None
)


class AgentTimeoutError(TimeoutError):
    """The current Agent request or stage has exhausted its time budget."""


def current_llm_timeout_seconds() -> float | None:
    """Return the remaining timeout for the current structured LLM call."""
    deadline = _LLM_DEADLINE.get()
    if deadline is None:
        return None
    deadline_at, clock = deadline
    return max(0.001, deadline_at - clock())


@dataclass
class AgentBudget:
    """Track total and cumulative per-stage time for one Agent run."""

    total_timeout_seconds: float
    stage_timeout_seconds: float
    clock: Callable[[], float] = monotonic
    _started_at: float = field(init=False)
    _stage_elapsed: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if self.stage_timeout_seconds <= 0:
            raise ValueError("stage_timeout_seconds must be positive")
        self._started_at = self.clock()

    @contextmanager
    def stage(self, stage_name: str) -> Iterator[None]:
        """Reserve remaining budget for one stage and expose it to HTTPX."""
        self._check(stage_name)
        stage_started_at = self.clock()
        timeout_seconds = min(
            self.total_timeout_seconds - self._total_elapsed(),
            self.stage_timeout_seconds - self._stage_elapsed.get(stage_name, 0.0),
        )
        token = _LLM_DEADLINE.set(
            (self.clock() + timeout_seconds, self.clock)
        )
        try:
            yield
        finally:
            elapsed = max(0.0, self.clock() - stage_started_at)
            self._stage_elapsed[stage_name] = (
                self._stage_elapsed.get(stage_name, 0.0) + elapsed
            )
            _LLM_DEADLINE.reset(token)
        self._check(stage_name)

    def _check(self, stage_name: str) -> None:
        if self._total_elapsed() >= self.total_timeout_seconds:
            raise AgentTimeoutError(
                f"Agent total timeout exceeded before {stage_name}"
            )
        if self._stage_elapsed.get(stage_name, 0.0) >= self.stage_timeout_seconds:
            raise AgentTimeoutError(
                f"{stage_name} stage timeout exceeded"
            )

    def _total_elapsed(self) -> float:
        return max(0.0, self.clock() - self._started_at)
