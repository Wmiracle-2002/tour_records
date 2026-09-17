from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import initialize_account
from app.models import User
from app.security import hash_password, verify_password


def test_password_hash_and_single_account_initialization(db_session: Session) -> None:
    stored = hash_password("good-password")
    assert stored != "good-password"
    assert verify_password("good-password", stored)
    assert not verify_password("wrong-password", stored)

    user = initialize_account(db_session, "shared", "good-password")
    assert user.password_hash != "good-password"
    assert db_session.scalar(select(User)).username == "shared"
    with pytest.raises(ValueError, match="already initialized"):
        initialize_account(db_session, "second", "another-password")


def test_login_me_refresh_and_no_registration(client: TestClient) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "shared", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/register", json={"username": "someone"}).status_code == 404
    result = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"})
    assert result.status_code == 200
    access = result.json()["access_token"]
    refresh = result.json()["refresh_token"]
    assert access != refresh
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).json()["username"] == "shared"
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert refreshed.status_code == 200
    assert client.get("/api/v1/trips", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": access}).status_code == 401


def test_business_routes_require_valid_access_token(client: TestClient) -> None:
    for method, path in (
        ("GET", "/api/v1/trips"), ("POST", "/api/v1/trips"),
        ("GET", "/api/v1/trips/1"), ("PATCH", "/api/v1/trips/1"),
        ("DELETE", "/api/v1/trips/1"), ("POST", "/api/v1/trips/1/records"),
        ("GET", "/api/v1/records/1"), ("PATCH", "/api/v1/records/1"),
        ("DELETE", "/api/v1/records/1"), ("GET", "/api/v1/stats"),
        ("GET", "/api/v1/auth/me"),
    ):
        assert client.request(method, path, headers={"Authorization": ""}).status_code == 401, path
        assert client.request(method, path, headers={"Authorization": "Bearer invalid"}).status_code == 401, path


def test_expired_and_wrong_type_tokens_are_rejected(client: TestClient) -> None:
    expired = jwt.encode(
        {"sub": "1", "type": "access", "iss": "footmarks", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        "test-only-secret-for-test-cases-only", algorithm="HS256",
    )
    refresh = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).json()["refresh_token"]
    assert client.get("/api/v1/trips", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    assert client.get("/api/v1/trips", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
