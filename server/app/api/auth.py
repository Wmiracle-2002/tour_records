import hashlib
import hmac
import re
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.accounts import delete_account
from app.agent.quota import TokenQuota
from app.models import AuthRateLimit, AuthSession, User
from app.security import create_token, hash_password, token_claims, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class Credentials(BaseModel):
    username: str
    password: str


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", value) or value.lower() == "admin":
            raise ValueError("Username must be 3-32 letters, digits or underscores and cannot be admin")
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        if not 12 <= len(value) <= 128:
            raise ValueError("Password must be 12-128 characters")
        return value


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def valid_new_password(cls, value: str) -> str:
        if not 12 <= len(value) <= 128:
            raise ValueError("Password must be 12-128 characters")
        return value


class AccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str
    confirm: bool

class RefreshRequest(BaseModel):
    refresh_token: str


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    user_id: int
    role: str
    requires_password_change: bool = False
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    status: str
    requires_password_change: bool


def signing_secret(request: Request) -> str:
    secret = request.app.state.settings.token_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Token secret is not configured")
    return secret


def limit_auth_attempts(
    db: Session, request: Request, action: str, *, username: str = "",
) -> None:
    client_ip = request.client.host if request.client is not None else "unknown"
    rules = (
        [(f"register:{client_ip}", 3600, 5)] if action == "register" else [
            (f"login-ip:{client_ip}", 600, 60),
            (f"login-user:{client_ip}:{username}", 600, 10),
        ]
    )
    now = int(time.time())
    for raw_key, seconds, maximum in rules:
        key = hashlib.sha256(raw_key.encode()).hexdigest()
        window = now // seconds
        statement = sqlite_insert(AuthRateLimit).values(
            key=key, window_start=window, attempts=1,
        ).on_conflict_do_update(
            index_elements=[AuthRateLimit.key],
            set_={
                "window_start": window,
                "attempts": case(
                    (AuthRateLimit.window_start == window, AuthRateLimit.attempts + 1),
                    else_=1,
                ),
            },
        ).returning(AuthRateLimit.attempts)
        attempts = db.scalar(statement)
        db.commit()
        if attempts > maximum:
            raise HTTPException(status_code=429, detail="Too many attempts; try later")


def issue_tokens(
    user: User, request: Request, db: Session, session: AuthSession | None = None,
    expected_refresh_hash: str | None = None,
) -> Tokens:
    settings = request.app.state.settings
    secret = signing_secret(request)
    if session is None:
        session = AuthSession(id=str(uuid4()), user_id=user.id, refresh_hash="")
        db.add(session)
    token_id = uuid4().hex
    new_hash = hashlib.sha256(token_id.encode()).hexdigest()
    if expected_refresh_hash is None:
        session.refresh_hash = new_hash
    else:
        changed = db.execute(
            update(AuthSession)
            .where(AuthSession.id == session.id, AuthSession.refresh_hash == expected_refresh_hash,
                   AuthSession.revoked_at.is_(None))
            .values(refresh_hash=new_hash)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    tokens = Tokens(
        access_token=create_token(
            user.id, "access", secret, timedelta(minutes=settings.access_token_minutes),
            session_id=session.id,
        ),
        refresh_token=create_token(
            user.id, "refresh", secret, timedelta(days=settings.refresh_token_days),
            session_id=session.id, token_id=token_id,
        ),
        user_id=user.id,
        role=user.role,
        requires_password_change=user.requires_password_change,
    )
    db.commit()
    return tokens


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    claims = token_claims(credentials.credentials, "access", signing_secret(request))
    user = db.get(User, int(claims["sub"])) if claims is not None else None
    session_id = claims.get("sid") if claims is not None else None
    session = db.get(AuthSession, session_id) if isinstance(session_id, str) else None
    if user is None or user.status != "active" or session is None or session.user_id != user.id or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid access token")
    request.state.auth_session_id = session.id
    if user.requires_password_change and request.url.path not in {
        "/api/v1/auth/password", "/api/v1/auth/me", "/api/v1/auth/logout",
    }:
        raise HTTPException(status_code=403, detail="Password change required")
    return user


@router.post("/login", response_model=Tokens)
def login(
    payload: Credentials, request: Request, db: Session = Depends(get_db)
) -> Tokens:
    limit_auth_attempts(db, request, "login", username=payload.username)
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or user.status != "active" or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return issue_tokens(user, request, db)


@router.post("/refresh", response_model=Tokens)
def refresh(
    payload: RefreshRequest, request: Request, db: Session = Depends(get_db)
) -> Tokens:
    claims = token_claims(payload.refresh_token, "refresh", signing_secret(request))
    user = db.get(User, int(claims["sub"])) if claims is not None else None
    session_id = claims.get("sid") if claims is not None else None
    session = db.get(AuthSession, session_id) if isinstance(session_id, str) else None
    token_id = claims.get("jti") if claims is not None else None
    if (user is None or user.status != "active" or session is None or session.user_id != user.id
            or session.revoked_at is not None or not isinstance(token_id, str)
            or not hmac.compare_digest(session.refresh_hash, hashlib.sha256(token_id.encode()).hexdigest())):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return issue_tokens(user, request, db, session, session.refresh_hash)


@router.post("/register", response_model=Tokens, status_code=201)
def register(payload: Registration, request: Request, db: Session = Depends(get_db)) -> Tokens:
    if not request.app.state.settings.public_registration_enabled:
        raise HTTPException(status_code=503, detail="Registration is not available")
    limit_auth_attempts(db, request, "register")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from error
    db.refresh(user)
    return issue_tokens(user, request, db)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.id == request.state.auth_session_id, AuthSession.user_id == user.id)
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


@router.post("/password", status_code=204)
def change_password(
    payload: PasswordChange, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    user.password_hash = hash_password(payload.new_password)
    user.requires_password_change = False
    db.execute(
        update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/me/quota")
def my_quota(
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
) -> dict[str, int | str]:
    quota = TokenQuota(
        sessionmaker(bind=db.get_bind()), request.app.state.settings.default_monthly_token_limit,
    )
    return quota.balance(user.id)


@router.delete("/me", status_code=204)
def delete_my_account(
    payload: AccountDeletion, request: Request, db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    if user.role != "user":
        raise HTTPException(status_code=403, detail="Administrator account cannot be deleted here")
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="Account deletion must be confirmed")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    delete_account(db, request, user)
