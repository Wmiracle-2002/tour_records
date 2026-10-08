"""Administrator-only account operations."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.auth import Registration, UserOut, current_user
from app.accounts import delete_account
from app.database import get_db
from app.models import AuthSession, User
from app.security import hash_password
from app.agent.quota import TokenQuota
from app.models import TokenQuotaPolicy
from app.api import travel as travel_api
from app.api import knowledge as knowledge_api
from app.api import agent as agent_api


router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserOut(UserOut):
    created_at: datetime
    monthly_token_limit: int | None
    photo_bytes_used: int


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "disabled"]


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str

    @field_validator("new_password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        if not 12 <= len(value) <= 128:
            raise ValueError("Password must be 12-128 characters")
        return value


class QuotaLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int | None = Field(ge=0)


class DefaultQuotaLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(ge=0)


def administrator(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    request.state.admin_actor_id = user.id
    request.state.admin_bind = db.get_bind()
    return user


def _ordinary_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != "user":
        raise HTTPException(status_code=403, detail="Administrator accounts cannot be managed here")
    return user


def _revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def _user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id, username=user.username, role=user.role, status=user.status,
        requires_password_change=user.requires_password_change, created_at=user.created_at,
        monthly_token_limit=user.monthly_token_limit,
        photo_bytes_used=user.photo_bytes_used,
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    limit: int = Query(default=50, ge=1, le=100), after_id: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), _admin: User = Depends(administrator),
) -> list[AdminUserOut]:
    users = db.scalars(select(User).where(User.id > after_id).order_by(User.id).limit(limit)).all()
    return [_user_out(user) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=201)
def create_user(
    payload: Registration, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator),
) -> AdminUserOut:
    user = User(
        username=payload.username, password_hash=hash_password(payload.password),
        requires_password_change=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from error
    db.refresh(user)
    request.state.admin_target_id = user.id
    return _user_out(user)


@router.patch("/users/{user_id}/status", response_model=AdminUserOut)
def change_status(
    user_id: int, payload: StatusChange, db: Session = Depends(get_db),
    _admin: User = Depends(administrator),
) -> AdminUserOut:
    user = _ordinary_user(db, user_id)
    user.status = payload.status
    if payload.status == "disabled":
        _revoke_user_sessions(db, user_id)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(
    user_id: int, payload: PasswordReset, db: Session = Depends(get_db),
    _admin: User = Depends(administrator),
) -> None:
    user = _ordinary_user(db, user_id)
    user.password_hash = hash_password(payload.new_password)
    user.requires_password_change = True
    _revoke_user_sessions(db, user_id)
    db.commit()


@router.delete("/users/{user_id}", status_code=204)
def remove_user(
    user_id: int, request: Request, db: Session = Depends(get_db),
    _admin: User = Depends(administrator),
) -> None:
    delete_account(db, request, _ordinary_user(db, user_id))


@router.get("/users/{user_id}/quota")
def user_quota(
    user_id: int, db: Session = Depends(get_db), _admin: User = Depends(administrator),
) -> dict[str, int | str]:
    _ordinary_user(db, user_id)
    return TokenQuota(sessionmaker(bind=db.get_bind())).balance(user_id)


@router.put("/users/{user_id}/quota", response_model=AdminUserOut)
def set_user_quota(
    user_id: int, payload: QuotaLimit, db: Session = Depends(get_db),
    _admin: User = Depends(administrator),
) -> AdminUserOut:
    user = _ordinary_user(db, user_id)
    user.monthly_token_limit = payload.limit
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.get("/quota/default")
def get_default_quota(
    db: Session = Depends(get_db), _admin: User = Depends(administrator),
) -> dict[str, int]:
    policy = db.get(TokenQuotaPolicy, 1)
    return {"limit": policy.default_limit if policy else 0}


@router.put("/quota/default")
def set_default_quota(
    payload: DefaultQuotaLimit, db: Session = Depends(get_db),
    _admin: User = Depends(administrator),
) -> dict[str, int]:
    policy = db.get(TokenQuotaPolicy, 1)
    if policy is None:
        policy = TokenQuotaPolicy(id=1, default_limit=payload.limit)
        db.add(policy)
    else:
        policy.default_limit = payload.limit
    db.commit()
    return {"limit": payload.limit}


@router.get("/users/{user_id}/trips", response_model=list[travel_api.TripDetail])
def list_user_trips(user_id: int, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.list_trips(request, db, _ordinary_user(db, user_id))


@router.post("/users/{user_id}/trips", response_model=travel_api.TripOut, status_code=201)
def create_user_trip(user_id: int, payload: travel_api.TripFields, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.create_trip(payload, db, _ordinary_user(db, user_id))


@router.patch("/users/{user_id}/trips/{trip_id}", response_model=travel_api.TripDetail)
def patch_user_trip(user_id: int, trip_id: int, payload: travel_api.TripPatch, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.update_trip(trip_id, payload, request, db, _ordinary_user(db, user_id))


@router.delete("/users/{user_id}/trips/{trip_id}", status_code=204)
def delete_user_trip(user_id: int, trip_id: int, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.delete_trip(trip_id, request, db, _ordinary_user(db, user_id))


@router.post("/users/{user_id}/trips/{trip_id}/records", response_model=travel_api.RecordOut, status_code=201)
def create_user_record(user_id: int, trip_id: int, payload: travel_api.RecordFields, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.create_record(trip_id, payload, request, db, _ordinary_user(db, user_id))


@router.patch("/users/{user_id}/records/{record_id}", response_model=travel_api.RecordOut)
def patch_user_record(user_id: int, record_id: int, payload: travel_api.RecordPatch, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.update_record(record_id, payload, request, db, _ordinary_user(db, user_id))


@router.delete("/users/{user_id}/records/{record_id}", status_code=204)
def delete_user_record(user_id: int, record_id: int, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.delete_record(record_id, request, db, _ordinary_user(db, user_id))


@router.post("/users/{user_id}/records/{record_id}/images", response_model=travel_api.ImageOut, status_code=201)
def upload_user_image(user_id: int, record_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.upload_image(record_id, request, file, db, _ordinary_user(db, user_id))


@router.delete("/users/{user_id}/images/{image_id}", status_code=204)
def delete_user_image(user_id: int, image_id: int, request: Request, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return travel_api.delete_image(image_id, request, db, _ordinary_user(db, user_id))


@router.get("/users/{user_id}/knowledge", response_model=list[knowledge_api.KnowledgeOut])
def list_user_knowledge(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return knowledge_api.list_knowledge(db=db, user=_ordinary_user(db, user_id))


@router.post("/users/{user_id}/knowledge", response_model=knowledge_api.KnowledgeOut, status_code=201)
def create_user_knowledge(user_id: int, payload: knowledge_api.KnowledgePayload, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return knowledge_api.create_knowledge(payload, db, _ordinary_user(db, user_id))


@router.patch("/users/{user_id}/knowledge/{entry_id}", response_model=knowledge_api.KnowledgeOut)
def patch_user_knowledge(user_id: int, entry_id: int, payload: knowledge_api.KnowledgePatch, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return knowledge_api.patch_knowledge(entry_id, payload, db, _ordinary_user(db, user_id))


@router.delete("/users/{user_id}/knowledge/{entry_id}", status_code=204)
def delete_user_knowledge(user_id: int, entry_id: int, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return knowledge_api.delete_knowledge(entry_id, db, _ordinary_user(db, user_id))


@router.get("/users/{user_id}/conversations", response_model=list[agent_api.ConversationOut])
def list_user_conversations(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.list_conversations(db, _ordinary_user(db, user_id))


@router.get("/users/{user_id}/conversations/{conversation_id}/messages", response_model=list[agent_api.ConversationMessageOut])
def list_user_messages(user_id: int, conversation_id: str, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.list_conversation_messages(conversation_id, db=db, user=_ordinary_user(db, user_id))


@router.delete("/users/{user_id}/conversations/{conversation_id}", status_code=204)
def delete_user_conversation(user_id: int, conversation_id: str, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.delete_conversation(conversation_id, db, _ordinary_user(db, user_id))


@router.get("/users/{user_id}/preferences", response_model=list[agent_api.PreferenceOut])
def list_user_preferences(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.list_preferences(db, _ordinary_user(db, user_id))


@router.put("/users/{user_id}/preferences/{category}", response_model=agent_api.PreferenceOut)
def put_user_preference(user_id: int, category: agent_api.PreferenceCategory, payload: agent_api.PreferenceUpsert, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.upsert_preference(category, payload, db, _ordinary_user(db, user_id))


@router.delete("/users/{user_id}/preferences/{category}", status_code=204)
def delete_user_preference(user_id: int, category: agent_api.PreferenceCategory, db: Session = Depends(get_db), _admin: User = Depends(administrator)):
    return agent_api.delete_preference(category, db, _ordinary_user(db, user_id))
