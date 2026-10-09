"""Request identity shared by HTTP middleware and Agent execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return _request_id_context.get()


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token = _request_id_context.set(request_id)
    try:
        yield
    finally:
        _request_id_context.reset(token)
