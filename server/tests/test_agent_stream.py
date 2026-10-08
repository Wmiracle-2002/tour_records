import json
import socket
import time
from threading import Event, Thread

import httpx
import uvicorn
from sqlalchemy.orm import sessionmaker

from app.agent.runtime import AgentRunResult
from app.agent.llm import LLMTimeoutError
from app.agent.observability import AgentEvent, current_preview_sink, current_stream_event_sink
from app.database import Base, create_database_engine, get_db
from app.models import ChatMessage, User
from app.security import hash_password


def events(response):
    return [
        (line.removeprefix("event: "), json.loads(lines[index + 1].removeprefix("data: ")))
        for lines in [response.text.splitlines()]
        for index, line in enumerate(lines)
        if line.startswith("event: ")
    ]


def test_stream_emits_started_stage_content_and_completed(client, db_session):
    class Runtime:
        def run(self, *_args, **_kwargs):
            return AgentRunResult(request_id="trace-one", answer="第一段\n第二段")

    client.app.state.agent_runtime = Runtime()
    conversation = client.post("/api/v1/agent/conversations").json()
    response = client.post(
        "/api/v1/agent/chat/stream",
        json={"message": "南京怎么玩", "conversation_id": conversation["id"], "client_message_id": "one"},
        headers={"X-Request-ID": "trace-one"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Request-ID"] == "trace-one"
    received = events(response)
    assert [name for name, _ in received] == ["started", "stage", "content", "content", "completed"]
    assert all(item["request_id"] == "trace-one" for _, item in received)
    assert "".join(item["text"] for name, item in received if name == "content") == "第一段\n第二段"
    assert received[-1][1]["answer"] == "第一段\n第二段"
    assert received[-1][1]["conversation_id"] == conversation["id"]
    assert db_session.query(ChatMessage).filter_by(role="assistant").one().content == "第一段\n第二段"


def test_stream_failure_has_error_and_no_completed_message(client, db_session):
    class Runtime:
        def run(self, *_args, **_kwargs):
            raise ValueError("invalid private response")

    client.app.state.agent_runtime = Runtime()
    conversation = client.post("/api/v1/agent/conversations").json()
    response = client.post(
        "/api/v1/agent/chat/stream",
        json={"message": "规划行程", "conversation_id": conversation["id"]},
    )

    assert response.status_code == 200
    received = events(response)
    assert [name for name, _ in received] == ["started", "stage", "error"]
    assert "invalid private response" not in response.text
    assert db_session.query(ChatMessage).filter_by(role="assistant").count() == 0
    assert db_session.query(ChatMessage).filter_by(role="user").one().status == "failed"


def test_stream_timeout_uses_error_event_with_clear_message(client):
    class Runtime:
        def run(self, *_args, **_kwargs):
            raise LLMTimeoutError("upstream private timeout")

    client.app.state.agent_runtime = Runtime()
    response = client.post("/api/v1/agent/chat/stream", json={"message": "规划南京一日游"})

    assert response.status_code == 200
    final_name, final_payload = events(response)[-1]
    assert final_name == "error"
    assert final_payload["code"] == 504
    assert final_payload["message"] == "智能规划响应超时，请稍后重试"
    assert "upstream private timeout" not in response.text


def test_stream_forwards_public_agent_stage_and_deduplicates_completed_request(client, db_session):
    calls = []

    class Runtime:
        def run(self, *_args, **_kwargs):
            calls.append(1)
            sink = current_stream_event_sink()
            assert sink is not None
            sink(AgentEvent(
                event="stage_started", request_id="trace-two",
                node_name="itinerary_generator",
            ))
            return AgentRunResult(request_id="trace-two", answer="南京一日游")

    client.app.state.agent_runtime = Runtime()
    conversation = client.post("/api/v1/agent/conversations").json()
    payload = {"message": "规划南京一日游", "conversation_id": conversation["id"], "client_message_id": "same"}
    first = client.post("/api/v1/agent/chat/stream", json=payload)
    second = client.post("/api/v1/agent/chat/stream", json=payload)

    assert first.status_code == second.status_code == 200
    assert "正在规划行程" in [
        item.get("message") for name, item in events(first) if name == "stage"
    ]
    assert events(second)[-1][1]["answer"] == "南京一日游"
    assert calls == [1]
    assert db_session.query(ChatMessage).filter_by(role="assistant").count() == 1


def test_stream_sends_progress_over_http_before_agent_finishes(client, db_session):
    entered = Event()
    release = Event()

    class SlowRuntime:
        def run(self, *_args, **_kwargs):
            entered.set()
            assert release.wait(5)
            return AgentRunResult(request_id="live-stream", answer="完成")

    client.app.state.agent_runtime = SlowRuntime()
    conversation = client.post("/api/v1/agent/conversations").json()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
    server_thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    server_thread.start()
    try:
        with httpx.Client(timeout=8) as live:
            with live.stream(
                "POST", f"http://127.0.0.1:{port}/api/v1/agent/chat/stream",
                headers={"Authorization": client.headers["Authorization"], "X-Request-ID": "live-stream"},
                json={"message": "南京怎么玩", "conversation_id": conversation["id"]},
            ) as response:
                lines = response.iter_lines()
                assert response.status_code == 200
                assert next(lines) == "event: started"
                assert "live-stream" in next(lines)
                assert next(lines) == ""
                assert next(lines) == "event: stage"
                assert entered.wait(3)
                assert not release.is_set()
                release.set()
                assert any(line == "event: completed" for line in lines)
    finally:
        release.set()
        server.should_exit = True
        server_thread.join(timeout=5)


def test_stream_sends_verified_day_preview_before_agent_finishes(client):
    release = Event()

    class SlowRuntime:
        def run(self, *_args, **_kwargs):
            preview = current_preview_sink()
            assert preview is not None
            preview("行程安排（生成中）：\n第1天：中山陵")
            assert release.wait(5)
            return AgentRunResult(request_id="preview-stream", answer="完整行程")

    client.app.state.agent_runtime = SlowRuntime()
    conversation = client.post("/api/v1/agent/conversations").json()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
    server_thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    server_thread.start()
    try:
        with httpx.Client(timeout=8) as live:
            with live.stream(
                "POST", f"http://127.0.0.1:{port}/api/v1/agent/chat/stream",
                headers={"Authorization": client.headers["Authorization"]},
                json={"message": "南京两日游", "conversation_id": conversation["id"]},
            ) as response:
                lines = response.iter_lines()
                for line in lines:
                    if line == "event: preview":
                        break
                preview_data = json.loads(next(lines).removeprefix("data: "))
                assert "第1天" in preview_data["text"]
                assert not release.is_set()
                release.set()
                assert any(line == "event: completed" for line in lines)
    finally:
        release.set()
        server.should_exit = True
        server_thread.join(timeout=5)


def test_stream_disconnect_does_not_save_partial_answer(client, tmp_path):
    # A live HTTP server and the test must not share the in-memory fixture's one SQLite connection.
    engine = create_database_engine(f"sqlite:///{tmp_path / 'stream-disconnect.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as setup:
        setup.add(User(username="shared", password_hash=hash_password("test-password")))

    def separate_db():
        with sessions() as session:
            yield session

    client.app.dependency_overrides[get_db] = separate_db
    login = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"})
    assert login.status_code == 200
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    entered = Event()
    release = Event()

    class SlowRuntime:
        def run(self, *_args, **_kwargs):
            preview = current_preview_sink()
            assert preview is not None
            preview("行程安排（生成中）：\n第1天：中山陵")
            entered.set()
            release.wait(5)
            return AgentRunResult(request_id="disconnect-stream", answer="不应保存")

    client.app.state.agent_runtime = SlowRuntime()
    conversation = client.post("/api/v1/agent/conversations").json()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
    server_thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    server_thread.start()
    try:
        connection = socket.create_connection(("127.0.0.1", port), timeout=8)
        body = json.dumps({"message": "南京怎么玩", "conversation_id": conversation["id"]}).encode()
        connection.sendall(
            b"POST /api/v1/agent/chat/stream HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{port}\r\n".encode()
            + f"Authorization: {client.headers['Authorization']}\r\n".encode()
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        received = b""
        while b"event: started" not in received:
            received += connection.recv(4096)
        assert b"200 OK" in received
        assert entered.wait(5)
        connection.shutdown(socket.SHUT_RDWR)
        connection.close()
        release.set()
        for _ in range(100):
            with sessions() as observer:
                user_message = observer.query(ChatMessage).filter_by(role="user").one()
                status = user_message.status
                assistant_count = observer.query(ChatMessage).filter_by(role="assistant").count()
            if status == "failed":
                break
            time.sleep(0.1)
        assert status == "failed"
        assert assistant_count == 0
    finally:
        release.set()
        server.should_exit = True
        server_thread.join(timeout=5)
        engine.dispose()
