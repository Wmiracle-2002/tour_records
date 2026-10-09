"""Create admin and migration target with private one-use credentials."""

import json
import os
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def initialize_accounts(db: Session, credential_path: Path) -> None:
    if db.scalar(select(User.id).where(User.username.in_(["admin", "ccqq"]))) is not None:
        raise ValueError("admin or ccqq already exists; no account created")
    passwords = {name: secrets.token_urlsafe(24) for name in ("admin", "ccqq")}
    credential_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(passwords, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        db.add_all([
            User(username="admin", password_hash=hash_password(passwords["admin"]),
                 role="admin", requires_password_change=True),
            User(username="ccqq", password_hash=hash_password(passwords["ccqq"]),
                 role="user", requires_password_change=True),
        ])
        db.commit()
    except Exception:
        db.rollback()
        credential_path.unlink(missing_ok=True)
        raise


def main() -> None:
    path = Path("/app/data/temporary-account-credentials.json")
    with SessionLocal() as db:
        initialize_accounts(db, path)
    print(f"Accounts created; one-use passwords are in {path} (root-only).")


if __name__ == "__main__":
    main()
