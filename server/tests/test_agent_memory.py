from sqlalchemy import func, select
from uuid import uuid4

from app.agent.memory import (
    CONVERSATION_MEMORY_TOKEN_BUDGET,
    ConversationMemoryService,
    estimate_tokens,
    ToolRunSnapshot,
)
from app.agent.graph import _analyzer_node, make_initial_state
from app.agent.models import TravelRequirement
from app.models import (
    AgentConversationMemory,
    AgentConversationSummary,
    AgentToolRun,
    AgentToolResult,
    ChatConversation,
    ChatMessage,
    User,
)


def test_conversation_memory_and_tool_results_cascade_with_conversation(db_session) -> None:
    user = User(username="memory-user", password_hash="not-used")
    db_session.add(user)
    db_session.flush()
    conversation = ChatConversation(id="memory-thread", user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    message = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="规划南京两日游",
        status="completed",
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        AgentConversationMemory(
            conversation_id=conversation.id,
            state_json={"city": "南京"},
            summary_cursor_message_id=message.id,
        )
    )
    db_session.add(
        AgentConversationSummary(
            conversation_id=conversation.id,
            first_message_id=message.id,
            last_message_id=message.id,
            chunk_index=0,
            summary_text="用户计划南京两日游。",
            token_estimate=12,
            version=1,
        )
    )
    tool_run = AgentToolRun(
        id="memory-tool-run",
        conversation_id=conversation.id,
        source_message_id=message.id,
        tool_name="keyword_search",
        arguments_json={"city": "南京", "keywords": "美食"},
        status="completed",
        summary_text="南京美食搜索返回 2 个地点。",
    )
    db_session.add(tool_run)
    db_session.add(
        AgentToolResult(
            tool_run=tool_run,
            result_json={"pois": ["秦淮小吃"]},
        )
    )
    db_session.commit()

    db_session.delete(conversation)
    db_session.commit()

    assert db_session.scalar(select(AgentConversationMemory)) is None
    assert db_session.scalar(select(AgentConversationSummary)) is None
    assert db_session.scalar(select(AgentToolRun)) is None
    assert db_session.scalar(select(AgentToolResult)) is None


def test_memory_schema_is_included_in_alembic_upgrade(tmp_path) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    database_path = tmp_path / "memory-migration.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "agent_conversation_memory",
        "agent_conversation_summaries",
        "agent_tool_runs",
        "agent_tool_results",
        "user_preferences",
    } <= tables


def _conversation(db_session, *, username="memory-context-user"):
    user = User(username=username, password_hash="not-used")
    db_session.add(user)
    db_session.flush()
    conversation = ChatConversation(id=str(uuid4()), user_id=user.id)
    db_session.add(conversation)
    db_session.flush()
    return user, conversation


def _add_exchange(db_session, conversation_id, index, text, answer=None):
    user_message = ChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=text,
        status="completed",
    )
    db_session.add(user_message)
    db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=answer or f"回答 {index}",
            status="completed",
            in_reply_to_message_id=user_message.id,
        )
    )
    db_session.flush()
    return user_message


def test_memory_context_keeps_eight_recent_turns_and_session_state(db_session) -> None:
    user, conversation = _conversation(db_session)
    for index in range(10):
        _add_exchange(db_session, conversation.id, index, f"问题 {index}")
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="美食呢？",
        status="pending",
    )
    db_session.add(current)
    db_session.flush()
    db_session.add(
        AgentConversationMemory(
            conversation_id=conversation.id,
            state_json={"city": "南京", "topic": "南京旅行"},
        )
    )
    db_session.commit()

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, current.id
    ).build_context("美食呢？")

    assert "南京" in context.prompt_context
    assert "问题 9" in context.prompt_context
    assert "问题 2" in context.prompt_context
    assert "问题 1" not in context.prompt_context
    assert "美食呢？" not in context.prompt_context


def test_memory_context_does_not_cross_conversations_for_same_user(db_session) -> None:
    user = User(username="two-thread-user", password_hash="not-used")
    db_session.add(user)
    db_session.flush()
    first = ChatConversation(id="first-thread", user_id=user.id)
    second = ChatConversation(id="second-thread", user_id=user.id)
    db_session.add_all([first, second])
    db_session.flush()
    old_message = ChatMessage(
        conversation_id=first.id,
        role="user",
        content="南京三日游",
        status="completed",
    )
    current = ChatMessage(
        conversation_id=second.id,
        role="user",
        content="美食呢？",
        status="pending",
    )
    db_session.add_all([old_message, current])
    db_session.add(
        AgentConversationMemory(
            conversation_id=first.id,
            state_json={"city": "南京", "topic": "南京三日游"},
        )
    )
    db_session.commit()

    context = ConversationMemoryService(
        db_session, user.id, second.id, current.id
    ).build_context(current.content)

    assert context.session_state.city is None
    assert "南京三日游" not in context.prompt_context


def test_memory_retrieval_finds_old_matching_message_with_source_id(db_session) -> None:
    user, conversation = _conversation(db_session)
    old_message = _add_exchange(
        db_session,
        conversation.id,
        0,
        "南京中山陵附近那家素食餐厅叫清欢",
    )
    for index in range(1, 10):
        _add_exchange(db_session, conversation.id, index, f"其他城市问题 {index}")
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="前面说的中山陵那家店叫什么？",
        status="pending",
    )
    db_session.add(current)
    db_session.commit()

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, current.id
    ).build_context(current.content)

    assert old_message.id in context.retrieved_message_ids
    assert f"message_id={old_message.id}" in context.prompt_context
    assert "清欢" in context.prompt_context


def test_memory_summary_triggers_at_seventy_percent_and_preserves_transcript(db_session) -> None:
    user, conversation = _conversation(db_session)
    for index in range(20):
        _add_exchange(
            db_session,
            conversation.id,
            index,
            f"较早旅行条件 {index} " + ("保留南京预算和不赶行程；" * 55),
            f"历史回答 {index} " + ("当时的地点与推荐理由；" * 45),
        )
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="回到之前的旅行安排",
        status="pending",
    )
    db_session.add(current)
    db_session.commit()
    original_count = db_session.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation.id
        )
    )
    summarized_blocks = []

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, current.id
    ).build_context(
        current.content,
        summarize=lambda text: summarized_blocks.append(text) or "保留南京预算与慢节奏偏好。",
    )

    assert context.compression_triggered
    assert summarized_blocks
    assert context.token_estimate <= CONVERSATION_MEMORY_TOKEN_BUDGET
    assert db_session.scalar(select(func.count(ChatMessage.id))) == original_count
    summaries = list(
        db_session.scalars(
            select(AgentConversationSummary).where(
                AgentConversationSummary.conversation_id == conversation.id
            )
        ).all()
    )
    assert summaries
    assert all(summary.first_message_id <= summary.last_message_id for summary in summaries)


def test_memory_below_seventy_percent_does_not_request_summary(db_session) -> None:
    user, conversation = _conversation(db_session)
    _add_exchange(db_session, conversation.id, 0, "规划南京周末游")
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="那美食呢？",
        status="pending",
    )
    db_session.add(current)
    db_session.commit()
    calls = []

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, current.id
    ).build_context(current.content, summarize=lambda text: calls.append(text) or "摘要")

    assert not context.compression_triggered
    assert calls == []


def test_summary_failure_leaves_full_messages_available(db_session) -> None:
    user, conversation = _conversation(db_session)
    for index in range(20):
        _add_exchange(db_session, conversation.id, index, "用户确认的行程要求；" * 100)
    current = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="之前的安排",
        status="pending",
    )
    db_session.add(current)
    db_session.commit()

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, current.id
    ).build_context(current.content, summarize=lambda _text: (_ for _ in ()).throw(RuntimeError()))

    assert not context.compression_triggered
    assert context.prompt_context
    assert db_session.scalar(select(AgentConversationSummary)) is None


def test_memory_token_estimate_and_hard_context_limit() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好") >= 1
    assert estimate_tokens("x" * 10) <= estimate_tokens("你" * 10)
    assert CONVERSATION_MEMORY_TOKEN_BUDGET > 0


def test_follow_up_detection_does_not_treat_every_sentence_ending_in_ne_as_follow_up() -> None:
    from app.agent.memory import is_referential_follow_up

    assert is_referential_follow_up("美食呢？")
    assert is_referential_follow_up("那上海呢？")
    assert not is_referential_follow_up("你觉得呢？")


def test_tool_result_lookup_is_scoped_to_its_conversation_and_owner(db_session) -> None:
    owner, conversation = _conversation(db_session, username="tool-owner")
    user_message = _add_exchange(db_session, conversation.id, 0, "南京天气怎么样？")
    other_user, other_conversation = _conversation(
        db_session, username="tool-other-owner"
    )
    other_message = _add_exchange(
        db_session, other_conversation.id, 0, "上海天气怎么样？"
    )
    service = ConversationMemoryService(
        db_session, owner.id, conversation.id, user_message.id + 1
    )
    run = service.record_tool_run(
        user_message.id,
        ToolRunSnapshot(
            tool_name="weather",
            executed_arguments={"city": "南京", "date": "2026-09-27"},
            status="completed",
            summary_text="南京天气：晴。",
            result_json={"data": [{"description": "晴"}]},
        ),
    )

    assert service.get_tool_result(run.id).result_json == {
        "data": [{"description": "晴"}]
    }
    other_service = ConversationMemoryService(
        db_session, other_user.id, other_conversation.id, other_message.id + 1
    )
    assert other_service.get_tool_result(run.id) is None


def test_tool_summary_carries_a_pointer_and_full_result_is_loaded_only_on_request(
    db_session,
) -> None:
    user, conversation = _conversation(db_session, username="tool-pointer-owner")
    source = _add_exchange(db_session, conversation.id, 0, "南京景点推荐")
    run = ConversationMemoryService(
        db_session, user.id, conversation.id, source.id + 1
    ).record_tool_run(
        source.id,
        ToolRunSnapshot(
            tool_name="keyword_search",
            executed_arguments={"city": "南京", "kind": "attraction"},
            status="completed",
            summary_text="南京景点：中山陵；count=1",
            result_json={"pois": [{"id": "P1", "name": "中山陵"}]},
        ),
    )
    recall = ChatMessage(
        conversation_id=conversation.id,
        role="user",
        content="请给我这次工具调用的完整结果",
        status="pending",
    )
    db_session.add(recall)
    db_session.commit()

    context = ConversationMemoryService(
        db_session, user.id, conversation.id, recall.id
    ).build_context(recall.content)

    assert f"tool_run_id={run.id}" in context.prompt_context
    assert '"name": "中山陵"' in context.prompt_context
    assert context.tool_run_ids == [run.id]


def test_graph_passes_session_context_to_requirement_analyzer() -> None:
    class CapturingAnalyzer:
        context = None
        session_state = None

        def analyze(self, query, *, conversation_context=None, session_state=None):
            self.context = conversation_context
            self.session_state = session_state
            return TravelRequirement(intent="poi_recommendation", poi_kind="food")

    analyzer = CapturingAnalyzer()
    state = make_initial_state(
        "美食呢？",
        conversation_context="当前城市：南京",
        session_memory_state={"city": "南京"},
    )

    result = _analyzer_node(analyzer, None)(state)

    assert result["requirement"].intent == "poi_recommendation"
    assert analyzer.context == "当前城市：南京"
    assert analyzer.session_state == {"city": "南京"}
