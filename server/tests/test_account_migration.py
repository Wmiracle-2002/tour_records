from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.migrate_account import account_counts, transfer_account
from app.models import ChatConversation, KnowledgeEntry, Trip, User, UserPreference
from app.security import hash_password


def test_transfer_requires_empty_target_and_preserves_parent_content(client: TestClient, db_session: Session) -> None:
    source = db_session.scalar(select(User).where(User.username == "shared"))
    assert source is not None
    target = User(username="ccqq", password_hash=hash_password("different-password"))
    db_session.add(target)
    db_session.commit()
    trip = client.post("/api/v1/trips", json={
        "province_code": "320000", "city_code": "320100", "city_name": "南京",
        "start_date": "2026-10-01", "end_date": "2026-10-03",
    })
    assert trip.status_code == 201
    db_session.add_all([
        ChatConversation(id="migration-conversation", user_id=source.id, title="旅行"),
        UserPreference(user_id=source.id, category="travel_pace", content="轻松"),
        KnowledgeEntry(user_id=source.id, category="note", title="笔记", body="内容",
                       city_code="320100", city_name="南京", tags=[]),
    ])
    db_session.commit()

    before = account_counts(db_session, source.id)
    assert transfer_account(db_session, "shared", "ccqq") == before
    assert account_counts(db_session, source.id) == before
    assert transfer_account(db_session, "shared", "ccqq", apply=True) == before
    assert db_session.scalar(select(User).where(User.username == "shared")) is None
    assert account_counts(db_session, target.id) == before
    assert db_session.get(Trip, trip.json()["id"]).user_id == target.id


def test_transfer_refuses_nonempty_target(client: TestClient, db_session: Session) -> None:
    target = User(username="ccqq", password_hash=hash_password("different-password"))
    db_session.add(target)
    db_session.commit()
    db_session.add(UserPreference(user_id=target.id, category="travel_pace", content="快速"))
    db_session.commit()
    try:
        transfer_account(db_session, "shared", "ccqq", apply=True)
    except ValueError as error:
        assert "already has content" in str(error)
    else:
        raise AssertionError("Transfer should reject occupied target")
