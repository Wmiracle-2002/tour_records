from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap import initialize_account, initialize_admin
from app.models import User
from app.security import hash_password, verify_password


def test_logout_revokes_access_and_refresh_tokens(client: TestClient) -> None:
    tokens = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).json()
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 204
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_refresh_rotates_token_and_rejects_reuse(client: TestClient) -> None:
    tokens = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).json()
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tokens["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_legacy_access_token_is_rejected(client: TestClient) -> None:
    from app.security import create_token

    legacy = create_token(1, "access", "test-only-secret-for-test-cases-only", timedelta(minutes=30))
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 401


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


def test_login_me_refresh_and_registration(client: TestClient) -> None:
    assert client.post("/api/v1/auth/login", json={"username": "shared", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/register", json={"username": "someone"}).status_code == 422
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


def test_public_registration_rejects_invalid_and_admin_names(client: TestClient) -> None:
    endpoint = "/api/v1/auth/register"
    for username in ("ab", "bad-name", "Admin", " ADMIN ", "x" * 33):
        assert client.post(endpoint, json={"username": username, "password": "long-enough-password"}).status_code == 422
    for password in ("short", "x" * 129):
        assert client.post(endpoint, json={"username": "NewUser", "password": password}).status_code == 422
    assert client.post(endpoint, json={"username": "NewUser", "password": "long-enough-password", "role": "admin"}).status_code == 422


def test_registration_is_case_sensitive_and_cannot_escalate(client: TestClient) -> None:
    endpoint = "/api/v1/auth/register"
    first = client.post(endpoint, json={"username": "NewUser", "password": "long-enough-password"})
    assert first.status_code == 201
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "user"
    assert client.get("/api/v1/auth/me/quota", headers=headers).json()["limit"] == 50000
    assert client.post(endpoint, json={"username": "NewUser", "password": "long-enough-password"}).status_code == 409
    assert client.post(endpoint, json={"username": "newuser", "password": "long-enough-password"}).status_code == 201


def test_public_registration_is_rate_limited(client: TestClient) -> None:
    endpoint = "/api/v1/auth/register"
    for index in range(5):
        assert client.post(endpoint, json={
            "username": f"visitor_{index}", "password": "long-enough-password",
        }).status_code == 201
    assert client.post(endpoint, json={
        "username": "visitor_extra", "password": "long-enough-password",
    }).status_code == 429


def test_admin_bootstrap_is_separate_and_singleton(db_session: Session) -> None:
    initialize_account(db_session, "shared", "good-password")
    admin = initialize_admin(db_session, "another-long-password")
    assert admin.username == "admin"
    assert admin.role == "admin"
    assert db_session.scalar(select(User).where(User.username == "shared")).role == "user"
    with pytest.raises(ValueError, match="already"):
        initialize_admin(db_session, "another-long-password")


def test_password_change_revokes_all_sessions(client: TestClient) -> None:
    first = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).json()
    second = client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).json()
    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": "test-password", "new_password": "a-new-long-password"},
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert changed.status_code == 204
    for tokens in (first, second):
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 401
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "shared", "password": "test-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "shared", "password": "a-new-long-password"}).status_code == 200


def test_account_deletion_requires_password_and_invalidates_tokens(client: TestClient) -> None:
    tokens = client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "test-password",
    }).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    endpoint = "/api/v1/auth/me"
    assert client.request("DELETE", endpoint, headers=headers, json={
        "password": "wrong", "confirm": True,
    }).status_code == 401
    assert client.request("DELETE", endpoint, headers=headers, json={
        "password": "test-password", "confirm": False,
    }).status_code == 422
    assert client.request("DELETE", endpoint, headers=headers, json={
        "password": "test-password", "confirm": True,
    }).status_code == 204
    assert client.get(endpoint, headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": tokens["refresh_token"],
    }).status_code == 401


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
