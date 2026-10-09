from pathlib import Path
import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap_accounts import initialize_accounts
from app.models import User
from app.security import verify_password


def test_initial_accounts_use_distinct_one_use_passwords(db_session: Session, tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    initialize_accounts(db_session, path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    import json
    passwords = json.loads(path.read_text(encoding="utf-8"))
    assert passwords["admin"] != passwords["ccqq"]
    for name in ("admin", "ccqq"):
        user = db_session.scalar(select(User).where(User.username == name))
        assert user is not None and user.requires_password_change
        assert verify_password(passwords[name], user.password_hash)
    with pytest.raises(ValueError):
        initialize_accounts(db_session, tmp_path / "second.json")
    assert not (tmp_path / "second.json").exists()
