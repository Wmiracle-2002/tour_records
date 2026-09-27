from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.preferences import parse_preference_command
from app.models import AgentToolRun, UserPreference
from app.security import hash_password
from app.models import User


def test_preference_command_requires_explicit_self_directed_memory_request() -> None:
    assert parse_preference_command("记住我不吃辣") == (
        "save", "food_restriction", "不吃辣"
    )
    assert parse_preference_command("这次不吃辣") is None
    assert parse_preference_command("我朋友不吃辣") is None
    assert parse_preference_command("记住我朋友不吃辣") is None


def test_preference_command_can_forget_a_category_value() -> None:
    assert parse_preference_command("忘记我不吃辣") == (
        "delete", "food_restriction", "不吃辣"
    )


def test_preference_command_does_not_write_a_third_party_or_multi_category_request() -> None:
    assert parse_preference_command("请记住我朋友不吃辣") is None
    assert parse_preference_command("记住我不吃辣，也喜欢博物馆") is None


def test_preferences_are_upserted_listed_and_deleted_independently(
    client: TestClient,
    db_session: Session,
) -> None:
    first = client.put(
        "/api/v1/agent/preferences/food_restriction",
        json={"content": "不吃辣"},
    )
    updated = client.put(
        "/api/v1/agent/preferences/food_restriction",
        json={"content": "不吃辣，也不吃香菜"},
    )
    listed = client.get("/api/v1/agent/preferences")

    assert first.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["content"] == "不吃辣，也不吃香菜"
    assert len(listed.json()) == 1
    owner_authorization = client.headers["Authorization"]

    db_session.add(
        User(username="preference-other", password_hash=hash_password("other-password"))
    )
    db_session.commit()
    tokens = client.post(
        "/api/v1/auth/login",
        json={"username": "preference-other", "password": "other-password"},
    ).json()
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    assert client.get("/api/v1/agent/preferences").json() == []

    client.headers["Authorization"] = owner_authorization
    removed = client.delete("/api/v1/agent/preferences/food_restriction")
    assert removed.status_code == 204
    assert db_session.query(UserPreference).count() == 0


def test_explicit_chat_command_saves_preference_and_survives_conversation_delete(
    client: TestClient,
    db_session: Session,
) -> None:
    class RuntimeMustNotRun:
        def run(self, *_args, **_kwargs):
            raise AssertionError("preference command should not call the Agent")

    client.app.state.agent_runtime = RuntimeMustNotRun()
    conversation = client.post("/api/v1/agent/conversations").json()
    response = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "记住我不吃辣",
            "conversation_id": conversation["id"],
            "client_message_id": "remember-spicy",
        },
    )

    assert response.status_code == 200
    assert "已记住" in response.json()["answer"]
    assert client.get("/api/v1/agent/preferences").json()[0]["content"] == "不吃辣"
    assert client.delete(
        f"/api/v1/agent/conversations/{conversation['id']}"
    ).status_code == 204
    assert client.get("/api/v1/agent/preferences").json()[0]["content"] == "不吃辣"
    assert db_session.query(AgentToolRun).count() == 0


def test_non_memory_command_is_processed_by_agent(client: TestClient) -> None:
    class CountingRuntime:
        calls = 0

        def run(self, message, _user_id, _db, **_kwargs):
            self.calls += 1
            from app.agent.runtime import AgentRunResult

            return AgentRunResult(request_id="normal-request", answer=f"回应：{message}")

    runtime = CountingRuntime()
    client.app.state.agent_runtime = runtime
    conversation = client.post("/api/v1/agent/conversations").json()
    response = client.post(
        "/api/v1/agent/chat",
        json={
            "message": "这次不吃辣",
            "conversation_id": conversation["id"],
        },
    )
    assert response.status_code == 200
    assert runtime.calls == 1
    assert client.get("/api/v1/agent/preferences").json() == []


def test_forget_command_removes_only_the_matching_saved_preference(client: TestClient) -> None:
    class RuntimeMustNotRun:
        def run(self, *_args, **_kwargs):
            raise AssertionError("preference command should not call the Agent")

    client.app.state.agent_runtime = RuntimeMustNotRun()
    client.post(
        "/api/v1/agent/chat",
        json={"message": "记住我不吃辣"},
    )
    forgotten = client.post(
        "/api/v1/agent/chat",
        json={"message": "忘记我不吃辣"},
    )
    assert forgotten.status_code == 200
    assert "已删除" in forgotten.json()["answer"]
    assert client.get("/api/v1/agent/preferences").json() == []


def test_preference_api_rejects_unknown_categories_and_blank_or_oversized_content(
    client: TestClient,
) -> None:
    unknown = client.put(
        "/api/v1/agent/preferences/other", json={"content": "test"}
    )
    blank = client.put(
        "/api/v1/agent/preferences/food_restriction", json={"content": "   "}
    )
    too_long = client.put(
        "/api/v1/agent/preferences/food_restriction",
        json={"content": "不" * 241},
    )
    assert unknown.status_code == blank.status_code == too_long.status_code == 422
