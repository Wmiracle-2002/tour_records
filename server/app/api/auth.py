from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import create_token, read_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class Credentials(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str


def signing_secret(request: Request) -> str:
    secret = request.app.state.settings.token_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=503, detail="Token secret is not configured")
    return secret


def issue_tokens(user: User, request: Request) -> Tokens:
    settings = request.app.state.settings
    secret = signing_secret(request)
    return Tokens(
        access_token=create_token(
            user.id, "access", secret, timedelta(minutes=settings.access_token_minutes)
        ),
        refresh_token=create_token(
            user.id, "refresh", secret, timedelta(days=settings.refresh_token_days)
        ),
    )


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = read_token(credentials.credentials, "access", signing_secret(request))
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid access token")
    return user


@router.post("/login", response_model=Tokens)
def login(
    payload: Credentials, request: Request, db: Session = Depends(get_db)
) -> Tokens:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return issue_tokens(user, request)


@router.post("/refresh", response_model=Tokens)
def refresh(
    payload: RefreshRequest, request: Request, db: Session = Depends(get_db)
) -> Tokens:
    user_id = read_token(payload.refresh_token, "refresh", signing_secret(request))
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return issue_tokens(user, request)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
