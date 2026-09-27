"""Authenticated HTTP entry point for the Travel Agent."""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.agent.budget import (
    AgentClientDisconnected,
    AgentCancellation,
    AgentTimeoutError,
    cancellation_context,
)
from app.agent.llm import (
    LLMInvalidResponseError,
    LLMNotConfiguredError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.agent.preferences import (
    PreferenceCategory,
    PreferenceOut,
    PreferenceUpsert,
    apply_preference_command,
)
from app.agent.runtime import AgentRunResult
from app.api.auth import current_user
from app.database import get_db
from app.models import ChatConversation, ChatMessage, User, UserPreference


router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


class AgentChatRequest(BaseModel):
    """一次 Agent 对话请求。"""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class AgentChatResponse(BaseModel):
    """一次 Agent 对话响应。"""

    request_id: str
    answer: str
    conversation_id: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationMessageOut(BaseModel):
    id: int
    role: str
    content: str
    status: str
    created_at: datetime


def _owned_conversation(
    db: Session,
    conversation_id: str,
    user_id: int,
) -> ChatConversation:
    conversation = db.scalar(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ConversationOut:
    conversation = ChatConversation(id=str(uuid4()), user_id=user.id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=0,
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ConversationOut]:
    rows = db.execute(
        select(ChatConversation, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatConversation.user_id == user.id)
        .group_by(ChatConversation.id)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
    ).all()
    return [
        ConversationOut(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=message_count,
        )
        for conversation, message_count in rows
    ]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ConversationMessageOut],
)
def list_conversation_messages(
    conversation_id: str,
    limit: int = 50,
    before_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ConversationMessageOut]:
    _owned_conversation(db, conversation_id, user.id)
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    statement = select(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id
    )
    if before_id is not None:
        statement = statement.where(ChatMessage.id < before_id)
    messages = list(
        db.scalars(statement.order_by(ChatMessage.id.desc()).limit(limit)).all()
    )
    messages.reverse()
    return [
        ConversationMessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            status=message.status,
            created_at=message.created_at,
        )
        for message in messages
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    conversation = _owned_conversation(db, conversation_id, user.id)
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)


@router.get("/preferences", response_model=list[PreferenceOut])
def list_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[PreferenceOut]:
    rows = db.scalars(
        select(UserPreference)
        .where(UserPreference.user_id == user.id)
        .order_by(UserPreference.category)
    ).all()
    return [PreferenceOut.model_validate(row) for row in rows]


@router.put("/preferences/{category}", response_model=PreferenceOut)
def upsert_preference(
    category: PreferenceCategory,
    payload: PreferenceUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PreferenceOut:
    row = db.scalar(
        select(UserPreference).where(
            UserPreference.user_id == user.id,
            UserPreference.category == category,
        )
    )
    if row is None:
        row = UserPreference(
            user_id=user.id, category=category, content=payload.content
        )
        db.add(row)
    else:
        row.content = payload.content
    db.commit()
    db.refresh(row)
    return PreferenceOut.model_validate(row)


@router.delete("/preferences/{category}", status_code=204)
def delete_preference(
    category: PreferenceCategory,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    row = db.scalar(
        select(UserPreference).where(
            UserPreference.user_id == user.id,
            UserPreference.category == category,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def _find_client_message(
    db: Session,
    conversation_id: str,
    client_message_id: str,
) -> ChatMessage | None:
    return db.scalar(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "user",
            ChatMessage.client_message_id == client_message_id,
        )
    )


def _mark_chat_failed(db: Session, message: ChatMessage | None) -> None:
    if message is None:
        return
    message.status = "failed"
    try:
        db.commit()
    except Exception:
        db.rollback()


def _llm_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, LLMNotConfiguredError):
        return HTTPException(status_code=503, detail="LLM service is not configured")
    if isinstance(error, LLMTimeoutError):
        return HTTPException(status_code=504, detail="LLM service timed out")
    if isinstance(error, AgentTimeoutError):
        return HTTPException(status_code=504, detail="Agent request timed out")
    if isinstance(error, (LLMUpstreamError, LLMInvalidResponseError)):
        return HTTPException(status_code=502, detail="LLM service request failed")
    raise TypeError(f"Unsupported LLM error: {type(error).__name__}")


async def _watch_client_disconnect(
    request: Request,
    cancellation: AgentCancellation,
    request_id: str,
) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.1)
    cancellation.cancel()
    logger.info("Agent client disconnected request_id=%s", request_id)


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    payload: AgentChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AgentChatResponse:
    """Run one authenticated, synchronous Agent request."""
    started_at = monotonic()
    request_id = request.state.request_id
    conversation = None
    user_message = None
    if payload.conversation_id is not None:
        conversation = _owned_conversation(db, payload.conversation_id, user.id)
        if payload.client_message_id is not None:
            user_message = _find_client_message(
                db, conversation.id, payload.client_message_id
            )
            if user_message is not None:
                if user_message.content != payload.message:
                    raise HTTPException(
                        status_code=409,
                        detail="client_message_id was already used for another message",
                    )
                if user_message.status == "completed":
                    assistant_message = db.scalar(
                        select(ChatMessage).where(
                            ChatMessage.in_reply_to_message_id == user_message.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                    if assistant_message is None:
                        raise HTTPException(
                            status_code=409, detail="Completed message has no saved answer"
                        )
                    return AgentChatResponse(
                        request_id=user_message.request_id or request_id,
                        answer=assistant_message.content,
                        conversation_id=conversation.id,
                    )
                if user_message.status == "pending":
                    raise HTTPException(
                        status_code=409, detail="Message is still being processed"
                    )
                user_message.status = "pending"
                db.commit()
        if user_message is None:
            user_message = ChatMessage(
                conversation_id=conversation.id,
                role="user",
                content=payload.message,
                client_message_id=payload.client_message_id,
                status="pending",
            )
            db.add(user_message)
            if conversation.title == "新对话":
                conversation.title = payload.message[:64]
            conversation.updated_at = datetime.now(timezone.utc)
            try:
                db.commit()
                db.refresh(user_message)
            except IntegrityError:
                db.rollback()
                if payload.client_message_id is None:
                    raise
                duplicate = _find_client_message(
                    db, conversation.id, payload.client_message_id
                )
                if duplicate is None:
                    raise
                raise HTTPException(
                    status_code=409, detail="Message is already being processed"
                )
    preference_answer = apply_preference_command(db, user.id, payload.message)
    if preference_answer is not None:
        if user_message is not None:
            user_message.status = "completed"
            user_message.request_id = request_id
            db.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=preference_answer,
                    status="completed",
                    in_reply_to_message_id=user_message.id,
                )
            )
            conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
        return AgentChatResponse(
            request_id=request_id,
            answer=preference_answer,
            conversation_id=conversation.id if conversation is not None else None,
        )
    cancellation = AgentCancellation()
    disconnect_watcher = asyncio.create_task(
        _watch_client_disconnect(request, cancellation, request_id)
    )
    try:
        with cancellation_context(cancellation):
            runtime_options = (
                {
                    "conversation_id": conversation.id,
                    "user_message_id": user_message.id,
                }
                if conversation is not None and user_message is not None
                else {}
            )
            result = await run_in_threadpool(
                request.app.state.agent_runtime.run,
                payload.message,
                user.id,
                db,
                **runtime_options,
            )
    except (
        LLMNotConfiguredError,
        LLMTimeoutError,
        AgentTimeoutError,
        LLMUpstreamError,
        LLMInvalidResponseError,
    ) as error:
        _mark_chat_failed(db, user_message)
        logger.warning(
            "Agent LLM failure request_id=%s type=%s detail=%s duration_ms=%.0f",
            request_id,
            type(error).__name__,
            str(error),
            (monotonic() - started_at) * 1000,
        )
        raise _llm_http_exception(error) from error
    except AgentClientDisconnected as error:
        _mark_chat_failed(db, user_message)
        logger.info(
            "Agent request cancelled request_id=%s duration_ms=%.0f",
            request_id,
            (monotonic() - started_at) * 1000,
        )
        raise HTTPException(status_code=499, detail="Client disconnected") from error
    except ValueError as error:
        _mark_chat_failed(db, user_message)
        logger.warning(
            "Agent generated an invalid response request_id=%s detail=%s duration_ms=%.0f",
            request_id,
            error,
            (monotonic() - started_at) * 1000,
        )
        raise HTTPException(
            status_code=502,
            detail="Agent generated an invalid response",
        ) from error
    except Exception:
        _mark_chat_failed(db, user_message)
        raise
    finally:
        disconnect_watcher.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_watcher
    if not isinstance(result, AgentRunResult):
        _mark_chat_failed(db, user_message)
        logger.warning("Agent returned an invalid response request_id=%s", request_id)
        raise HTTPException(status_code=502, detail="Agent returned an invalid response")
    if user_message is not None:
        user_message.status = "completed"
        user_message.request_id = result.request_id
        db.add(
            ChatMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=result.answer,
                status="completed",
                in_reply_to_message_id=user_message.id,
            )
        )
        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()
    return AgentChatResponse(
        **result.model_dump(),
        conversation_id=conversation.id if conversation is not None else None,
    )
