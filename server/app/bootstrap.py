import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def initialize_account(db: Session, username: str, password: str) -> User:
    if db.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Account is already initialized")
    if not username.strip() or len(password) < 12:
        raise ValueError("A username and password of at least 12 characters are required")
    user = User(username=username.strip(), password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def initialize_admin(db: Session, password: str) -> User:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Admin password must be 12-128 characters")
    if db.scalar(select(User.id).where(User.username == "admin")) is not None:
        raise ValueError("Admin account is already initialized")
    user = User(username="admin", password_hash=hash_password(password), role="admin")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    username = os.environ.get("FOOTMARKS_INITIAL_USERNAME", "shared")
    password = os.environ.get("FOOTMARKS_INITIAL_PASSWORD")
    if not password:
        raise SystemExit("Set FOOTMARKS_INITIAL_PASSWORD before initialization")
    with SessionLocal() as db:
        try:
            initialize_account(db, username, password)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    print("Account initialized")


if __name__ == "__main__":
    main()
