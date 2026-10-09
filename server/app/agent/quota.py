"""Atomic monthly LLM token reservations and settlement."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.models import MonthlyTokenUsage, TokenQuotaPolicy, TokenUsageCall, User


_quota_user: ContextVar[int | None] = ContextVar("quota_user", default=None)


@contextmanager
def quota_user(user_id: int):
    token = _quota_user.set(user_id)
    try:
        yield
    finally:
        _quota_user.reset(token)


def current_quota_user() -> int | None:
    return _quota_user.get()


class QuotaExceeded(RuntimeError):
    pass


class TokenQuota:
    def __init__(self, sessions: sessionmaker[Session], default_limit: int = 0) -> None:
        self.sessions = sessions
        self.default_limit = default_limit

    @staticmethod
    def period(now: datetime | None = None) -> str:
        return (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m")

    def _limit(self, db: Session, user: User) -> int:
        if user.monthly_token_limit is not None:
            return user.monthly_token_limit
        policy = db.get(TokenQuotaPolicy, 1)
        return policy.default_limit if policy is not None else self.default_limit

    def balance(self, user_id: int, *, now: datetime | None = None) -> dict[str, int | str]:
        period = self.period(now)
        with self.sessions() as db:
            user = db.get(User, user_id)
            if user is None:
                raise ValueError("User not found")
            usage = db.scalar(select(MonthlyTokenUsage).where(
                MonthlyTokenUsage.user_id == user_id, MonthlyTokenUsage.period == period,
            ))
            limit = self._limit(db, user)
            used = usage.input_tokens + usage.output_tokens + usage.fallback_tokens if usage else 0
            return {
                "period": period, "limit": limit, "used": used,
                "reserved": usage.reserved_tokens if usage else 0,
                "remaining": max(0, limit - used - (usage.reserved_tokens if usage else 0)),
                "input_tokens": usage.input_tokens if usage else 0,
                "output_tokens": usage.output_tokens if usage else 0,
                "fallback_tokens": usage.fallback_tokens if usage else 0,
            }

    def reserve(self, user_id: int, amount: int, *, now: datetime | None = None) -> str:
        if amount <= 0:
            raise ValueError("Reservation must be positive")
        period = self.period(now)
        with self.sessions() as db:
            user = db.get(User, user_id)
            if user is None or user.status != "active":
                raise QuotaExceeded("Account is not active")
            limit = self._limit(db, user)
            db.execute(sqlite_insert(MonthlyTokenUsage).values(
                user_id=user_id, period=period, input_tokens=0,
                output_tokens=0, fallback_tokens=0, reserved_tokens=0,
            ).on_conflict_do_nothing(index_elements=["user_id", "period"]))
            changed = db.execute(
                update(MonthlyTokenUsage)
                .where(MonthlyTokenUsage.user_id == user_id, MonthlyTokenUsage.period == period)
                .where(
                    MonthlyTokenUsage.input_tokens + MonthlyTokenUsage.output_tokens
                    + MonthlyTokenUsage.fallback_tokens + MonthlyTokenUsage.reserved_tokens + amount <= limit
                )
                .values(reserved_tokens=MonthlyTokenUsage.reserved_tokens + amount)
            )
            if changed.rowcount != 1:
                db.rollback()
                raise QuotaExceeded("Monthly token limit reached")
            call_id = str(uuid4())
            db.add(TokenUsageCall(
                id=call_id, user_id=user_id, period=period, reserved_tokens=amount,
            ))
            db.commit()
            return call_id

    def settle(
        self, call_id: str, *, input_tokens: int | None, output_tokens: int | None,
    ) -> None:
        actual = (
            input_tokens is not None and output_tokens is not None
            and input_tokens >= 0 and output_tokens >= 0
        )
        with self.sessions() as db:
            changed = db.execute(
                update(TokenUsageCall)
                .where(TokenUsageCall.id == call_id, TokenUsageCall.status == "reserved")
                .values(status="settling")
            )
            if changed.rowcount != 1:
                db.rollback()
                return
            call = db.get(TokenUsageCall, call_id)
            usage = db.scalar(select(MonthlyTokenUsage).where(
                MonthlyTokenUsage.user_id == call.user_id,
                MonthlyTokenUsage.period == call.period,
            ))
            if usage is None:
                raise RuntimeError("Token usage row missing")
            usage.reserved_tokens -= call.reserved_tokens
            if actual:
                usage.input_tokens += input_tokens
                usage.output_tokens += output_tokens
                call.input_tokens = input_tokens
                call.output_tokens = output_tokens
                call.status = "actual"
            else:
                usage.fallback_tokens += call.reserved_tokens
                call.status = "fallback"
            db.commit()

    def release(self, call_id: str) -> None:
        """Release a reservation when the provider was never connected."""
        with self.sessions() as db:
            changed = db.execute(
                update(TokenUsageCall)
                .where(TokenUsageCall.id == call_id, TokenUsageCall.status == "reserved")
                .values(status="released")
            )
            if changed.rowcount != 1:
                db.rollback()
                return
            call = db.get(TokenUsageCall, call_id)
            usage = db.scalar(select(MonthlyTokenUsage).where(
                MonthlyTokenUsage.user_id == call.user_id,
                MonthlyTokenUsage.period == call.period,
            ))
            usage.reserved_tokens -= call.reserved_tokens
            db.commit()
