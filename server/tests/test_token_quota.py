from datetime import datetime, timezone
import json

import pytest
import httpx
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app.agent.quota import QuotaExceeded, TokenQuota
from app.agent.quota import quota_user
from app.agent.llm import OpenAICompatibleTransport
from app.core.config import Settings
from pydantic import BaseModel


@pytest.fixture
def quota():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(username="a", password_hash="unused", monthly_token_limit=100))
        db.commit()
    yield TokenQuota(factory)
    engine.dispose()


def test_reserve_settle_and_month_reset(quota):
    september = datetime(2026, 9, 30, 15, tzinfo=timezone.utc)
    october = datetime(2026, 9, 30, 16, tzinfo=timezone.utc)
    first = quota.reserve(1, 60, now=september)
    with pytest.raises(QuotaExceeded):
        quota.reserve(1, 41, now=september)
    quota.settle(first, input_tokens=20, output_tokens=10)
    quota.settle(first, input_tokens=20, output_tokens=10)
    assert quota.balance(1, now=september)["remaining"] == 70
    assert quota.balance(1, now=october)["remaining"] == 100


def test_missing_provider_usage_charges_reservation(quota):
    reservation = quota.reserve(1, 60)
    quota.settle(reservation, input_tokens=None, output_tokens=None)
    assert quota.balance(1)["used"] == 60
    with pytest.raises(QuotaExceeded):
        quota.reserve(1, 41)


def test_unsent_provider_request_releases_reservation(quota):
    reservation = quota.reserve(1, 60)
    quota.release(reservation)
    quota.release(reservation)
    assert quota.balance(1)["remaining"] == 100
    assert quota.balance(1)["used"] == 0


class SmallAnswer(BaseModel):
    answer: str


def test_json_provider_usage_is_charged_once(tmp_path: Path):
    path = tmp_path / "quota.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(User(username="a", password_hash="unused", monthly_token_limit=1000))
        db.commit()
    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{path}", token_quota_enabled=True,
        llm_base_url="https://llm.example/v1", llm_api_key="test", llm_model="test",
        llm_max_output_tokens=100,
    )
    transport = OpenAICompatibleTransport(settings, http_transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json={
            "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4},
        }),
    ))
    with quota_user(1):
        assert transport.complete_json(
            system_prompt="Answer", user_prompt="Hello", output_model=SmallAnswer,
        ) == {"answer": "ok"}
    quota = TokenQuota(sessionmaker(bind=engine))
    assert quota.balance(1)["used"] == 12
    assert quota.balance(1)["reserved"] == 0
    transport.close()
    engine.dispose()


def test_stream_tail_usage_is_charged(tmp_path: Path):
    path = tmp_path / "stream-quota.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(User(username="a", password_hash="unused", monthly_token_limit=1000))
        db.commit()
    settings = Settings(
        _env_file=None, database_url=f"sqlite:///{path}", token_quota_enabled=True,
        llm_base_url="https://llm.example/v1", llm_api_key="test", llm_model="test",
        llm_max_output_tokens=100,
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"{\\"answer\\":\\"ok\\"}"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":5}}\n\n'
            'data: [DONE]\n\n'
        ))

    transport = OpenAICompatibleTransport(settings, http_transport=httpx.MockTransport(handler))
    with quota_user(1):
        assert transport.complete_json_stream(
            system_prompt="Answer", user_prompt="Hello", output_model=SmallAnswer,
            on_delta=lambda _value: None,
        ) == {"answer": "ok"}
    assert json.loads(requests[0].content)["stream_options"]["include_usage"] is True
    assert TokenQuota(sessionmaker(bind=engine)).balance(1)["used"] == 14
    transport.close()
    engine.dispose()
