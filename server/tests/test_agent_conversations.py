from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRunResult
from app.agent.llm import LLMTimeoutError
from app.models import User
from app.security import hash_password


class CountingRuntime:
    def __init__(self) -> None:
        self.calls = 0
        self.memory_options: dict[str, Any] = {}

    def run(self, message: str, user_id: int, db: Any, **kwargs: Any) -> AgentRunResult:
        self.calls += 1
        self.memory_options = kwargs
        return AgentRunResult(request_id=f"request-{self.calls}", answer=f"回答：{message}")


class FailOnceRuntime(CountingRuntime):
    def run(self, message: str, user_id: int, db: Any, **kwargs: Any) -> AgentRunResult:
        self.calls += 1
        if self.calls == 1:
            raise LLMTimeoutError("temporary timeout")
        return AgentRunResult(request_id=f"request-{self.calls}", answer=f"回答：{message}")


def create_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/agent/conversations")
    assert response.status_code == 201
    return response.json()["id"]


def test_conversation_crud_persists_messages_and_deletes_them(
    client: TestClient,
) -> None:
    runtime = CountingRuntime()
    client.app.state.agent_runtime = runtime
    conversation_id = create_conversation(client)

    chat = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "南京有什么景点？",
            "conversation_id": conversation_id,
            "client_message_id": "message-1",
        },
    )
    listing = client.get("/api/v1/agent/conversations")
    messages = client.get(f"/api/v1/agent/conversations/{conversation_id}/messages")

    assert chat.status_code == 200
    assert chat.json()["conversation_id"] == conversation_id
    assert listing.json()[0]["message_count"] == 2
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]
    assert [item["content"] for item in messages.json()] == [
        "南京有什么景点？",
        "回答：南京有什么景点？",
    ]
    assert runtime.memory_options["conversation_id"] == conversation_id
    assert runtime.memory_options["user_message_id"] == messages.json()[0]["id"]

    deleted = client.delete(f"/api/v1/agent/conversations/{conversation_id}")
    missing = client.get(f"/api/v1/agent/conversations/{conversation_id}/messages")
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_conversation_and_messages_are_isolated_by_user(
    client: TestClient,
    db_session: Session,
) -> None:
    conversation_id = create_conversation(client)
    db_session.add(
        User(username="another-user", password_hash=hash_password("another-password"))
    )
    db_session.commit()
    tokens = client.post(
        "/api/v1/auth/login",
        json={"username": "another-user", "password": "another-password"},
    ).json()
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"

    response = client.get(
        f"/api/v1/agent/conversations/{conversation_id}/messages"
    )
    deleted = client.delete(f"/api/v1/agent/conversations/{conversation_id}")

    assert response.status_code == 404
    assert deleted.status_code == 404


def test_chat_client_message_id_prevents_duplicate_agent_calls(client: TestClient) -> None:
    runtime = CountingRuntime()
    client.app.state.agent_runtime = runtime
    conversation_id = create_conversation(client)
    payload = {
        "message": "推荐南京美食",
        "conversation_id": conversation_id,
        "client_message_id": "retry-safe-id",
    }

    first = client.post("/api/v1/agent/chat", json=payload)
    retry = client.post("/api/v1/agent/chat", json=payload)
    messages = client.get(f"/api/v1/agent/conversations/{conversation_id}/messages")

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert runtime.calls == 1
    assert len(messages.json()) == 2


def test_reused_client_message_id_with_different_text_is_rejected(
    client: TestClient,
) -> None:
    runtime = CountingRuntime()
    client.app.state.agent_runtime = runtime
    conversation_id = create_conversation(client)
    first = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "南京有什么景点？",
            "conversation_id": conversation_id,
            "client_message_id": "same-id",
        },
    )
    conflict = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "上海有什么美食？",
            "conversation_id": conversation_id,
            "client_message_id": "same-id",
        },
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert runtime.calls == 1


def test_failed_message_can_be_retried_with_same_client_message_id(
    client: TestClient,
) -> None:
    runtime = FailOnceRuntime()
    client.app.state.agent_runtime = runtime
    conversation_id = create_conversation(client)
    payload = {
        "message": "南京天气怎么样？",
        "conversation_id": conversation_id,
        "client_message_id": "retry-after-failure",
    }

    failed = client.post("/api/v1/agent/chat", json=payload)
    retried = client.post("/api/v1/agent/chat", json=payload)
    messages = client.get(f"/api/v1/agent/conversations/{conversation_id}/messages")

    assert failed.status_code == 504
    assert retried.status_code == 200
    assert runtime.calls == 2
    assert [item["status"] for item in messages.json()] == ["completed", "completed"]


def test_message_pagination_returns_older_messages_before_newer_ones(
    client: TestClient,
) -> None:
    client.app.state.agent_runtime = CountingRuntime()
    conversation_id = create_conversation(client)
    for index in range(2):
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": f"问题{index}",
                "conversation_id": conversation_id,
                "client_message_id": f"page-{index}",
            },
        )
        assert response.status_code == 200

    latest = client.get(
        f"/api/v1/agent/conversations/{conversation_id}/messages", params={"limit": 2}
    ).json()
    older = client.get(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        params={"limit": 2, "before_id": latest[0]["id"]},
    ).json()

    assert [item["content"] for item in latest] == ["问题1", "回答：问题1"]
    assert [item["content"] for item in older] == ["问题0", "回答：问题0"]


def test_conversation_endpoints_require_authentication(client: TestClient) -> None:
    client.headers.pop("Authorization", None)

    created = client.post("/api/v1/agent/conversations")
    listed = client.get("/api/v1/agent/conversations")

    assert created.status_code == 401
    assert listed.status_code == 401
