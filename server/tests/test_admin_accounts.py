from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bootstrap import initialize_admin
from app.models import AdminAudit
from sqlalchemy import select


def _admin_token(client: TestClient, db: Session) -> str:
    initialize_admin(db, "administrator-password")
    response = client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "administrator-password",
    })
    assert response.status_code == 200
    return response.json()["access_token"]


def test_only_admin_can_manage_user_accounts(client: TestClient, db_session: Session) -> None:
    token = _admin_token(client, db_session)
    assert client.get("/api/v1/admin/users").status_code == 403
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/admin/users", headers=headers, json={
        "username": "Alice", "password": "temporary-password",
    })
    assert response.status_code == 201
    user_id = response.json()["id"]
    assert response.json()["role"] == "user"
    assert response.json()["requires_password_change"] is True
    audit = db_session.scalar(select(AdminAudit).where(AdminAudit.target_user_id == user_id))
    assert audit is not None
    assert audit.actor_user_id != user_id
    assert audit.method == "POST"
    assert audit.status_code == 201
    assert any(row["id"] == user_id for row in client.get("/api/v1/admin/users", headers=headers).json())
    assert client.post("/api/v1/admin/users", headers=headers, json={
        "username": "ADMIN", "password": "temporary-password",
    }).status_code == 422


def test_disable_and_reset_revoke_all_sessions(client: TestClient, db_session: Session) -> None:
    token = _admin_token(client, db_session)
    admin_headers = {"Authorization": f"Bearer {token}"}
    user_tokens = client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "test-password",
    }).json()
    response = client.get("/api/v1/admin/users", headers=admin_headers)
    user_id = next(row["id"] for row in response.json() if row["username"] == "shared")
    assert client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin_headers, json={
        "status": "disabled",
    }).status_code == 200
    assert client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {user_tokens['access_token']}",
    }).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={
        "refresh_token": user_tokens["refresh_token"],
    }).status_code == 401
    assert client.patch(f"/api/v1/admin/users/{user_id}/status", headers=admin_headers, json={
        "status": "active",
    }).status_code == 200
    assert client.post(f"/api/v1/admin/users/{user_id}/password", headers=admin_headers, json={
        "new_password": "reset-long-password",
    }).status_code == 204
    assert client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "test-password",
    }).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "reset-long-password",
    }).status_code == 200
    temporary = client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "reset-long-password",
    }).json()
    assert temporary["requires_password_change"] is True
    temporary_headers = {"Authorization": f"Bearer {temporary['access_token']}"}
    assert client.get("/api/v1/trips", headers=temporary_headers).status_code == 403
    assert client.post("/api/v1/auth/password", headers=temporary_headers, json={
        "current_password": "reset-long-password", "new_password": "changed-again-password",
    }).status_code == 204
    assert client.get("/api/v1/trips", headers=temporary_headers).status_code == 401
    changed = client.post("/api/v1/auth/login", json={
        "username": "shared", "password": "changed-again-password",
    }).json()
    assert changed["requires_password_change"] is False


def test_admin_can_set_default_and_per_user_quota(client: TestClient, db_session: Session) -> None:
    token = _admin_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}
    user_id = next(row["id"] for row in client.get("/api/v1/admin/users", headers=headers).json()
                   if row["username"] == "shared")
    assert client.put("/api/v1/admin/quota/default", json={"limit": 1000}).status_code == 403
    assert client.put("/api/v1/admin/quota/default", headers=headers, json={"limit": 1000}).status_code == 200
    assert client.get("/api/v1/auth/me/quota").json()["limit"] == 1000
    assert client.put(f"/api/v1/admin/users/{user_id}/quota", headers=headers, json={"limit": 250}).status_code == 200
    assert client.get("/api/v1/auth/me/quota").json()["limit"] == 250
    assert client.put(f"/api/v1/admin/users/{user_id}/quota", headers=headers, json={"limit": -1}).status_code == 422


def test_admin_trip_edits_reuse_owner_validation_and_sync(client: TestClient, db_session: Session) -> None:
    token = _admin_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}
    user_id = next(row["id"] for row in client.get("/api/v1/admin/users", headers=headers).json()
                   if row["username"] == "shared")
    trip = {
        "province_code": "320000", "city_code": "320100", "city_name": "南京市",
        "start_date": "2026-10-01", "end_date": "2026-10-03",
    }
    endpoint = f"/api/v1/admin/users/{user_id}/trips"
    assert client.post(endpoint, json=trip).status_code == 403
    created = client.post(endpoint, headers=headers, json=trip)
    assert created.status_code == 201
    trip_id = created.json()["id"]
    assert client.post(f"{endpoint}/{trip_id}/records", headers=headers, json={
        "type": "FOOD", "name": "鸭血粉丝汤", "date": "2026-10-04",
    }).status_code == 422
    assert client.get("/api/v1/trips").json()[0]["id"] == trip_id
    assert client.get("/api/v1/sync/trips").json()["upserts"][0]["id"] == trip_id
