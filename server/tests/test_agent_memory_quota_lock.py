import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.agent.memory import ConversationSummaryOutput, ToolRunSnapshot
from app.agent.models import TravelRequirement
from app.agent.quota import TokenQuota
from app.agent.runtime import AgentRuntime
from app.core.config import Settings
from app.database import Base
from app.models import ChatConversation, ChatMessage, User


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
@pytest.mark.parametrize("compress", [False, True])
def test_tool_memory_releases_sqlite_writer_before_next_llm(tmp_path, monkeypatch, journal_mode, compress, request):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.sqlite'}", connect_args={"timeout": 0.05})
    request.addfinalizer(engine.dispose)
    with engine.connect() as connection:
        connection.execute(text(f"PRAGMA journal_mode={journal_mode}"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    quota = TokenQuota(sessions, default_limit=50000)
    with sessions() as db:
        user = User(username="lock-test", password_hash="unused")
        db.add(user)
        db.flush()
        conversation = ChatConversation(id="lock-test", user_id=user.id)
        db.add(conversation)
        db.flush()
        if compress:
            for index in range(20):
                db.add(ChatMessage(conversation_id=conversation.id, role="user",
                                   content=f"{index}南京旅行要求" * 500, status="completed"))
                db.add(ChatMessage(conversation_id=conversation.id, role="assistant",
                                   content="南京行程建议" * 500, status="completed"))
            db.flush()
        message = ChatMessage(conversation_id=conversation.id, role="user", content="南京一日游", status="pending")
        db.add(message)
        db.commit()

        def build_graph(**components):
            class Graph:
                def invoke(self, initial):
                    first = quota.reserve(user.id, 100)
                    quota.settle(first, input_tokens=10, output_tokens=10)
                    components["tool_run_recorder"](ToolRunSnapshot(
                        tool_name="keyword_search", executed_arguments={"city": "南京"},
                        status="completed", summary_text="南京景点", result_json={"pois": []},
                    ))
                    # The real LLM transport reserves tokens in a separate transaction.
                    reservation = quota.reserve(user.id, 100)
                    quota.settle(reservation, input_tokens=10, output_tokens=10)
                    return {"final_response": "完成", "requirement": TravelRequirement(intent="trip_planning", city="南京")}
            return Graph()

        monkeypatch.setattr("app.agent.runtime.build_agent_graph", build_graph)
        class Client:
            def complete_structured(self, **kwargs):
                reservation = quota.reserve(user.id, 100)
                quota.settle(reservation, input_tokens=10, output_tokens=10)
                return ConversationSummaryOutput(summary="用户计划南京旅行")

        result = AgentRuntime(settings=Settings(token_secret="test-only-secret"), llm_client=Client()).run(
            message.content, user.id, db, conversation_id=conversation.id, user_message_id=message.id,
        )
        assert result.answer == "完成"
        assert quota.balance(user.id)["reserved"] == 0
    engine.dispose()
