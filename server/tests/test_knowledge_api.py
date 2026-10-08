from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password


URL = "/api/v1/agent/knowledge"
ENTRY = {
    "category": "food_guide",
    "title": "南京早餐",
    "body": "鸭血粉丝汤值得尝试，出发前核实营业时间。",
    "city_code": "320100",
    "city_name": "南京市",
    "tags": ["早餐", "小吃"],
    "source": "自己的旅行笔记",
}


def test_knowledge_crud_and_user_isolation(client: TestClient, db_session: Session) -> None:
    created = client.post(URL, json=ENTRY)
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert client.get(URL).json()[0]["title"] == "南京早餐"
    assert client.get(f"{URL}/{entry_id}").json()["body"] == ENTRY["body"]

    owner_token = client.headers["Authorization"]
    db_session.add(User(username="knowledge-other", password_hash=hash_password("other-password")))
    db_session.commit()
    login = client.post("/api/v1/auth/login", json={
        "username": "knowledge-other", "password": "other-password",
    })
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert client.get(URL).json() == []
    assert client.get(f"{URL}/{entry_id}").status_code == 404
    assert client.patch(f"{URL}/{entry_id}", json={"title": "篡改"}).status_code == 404
    assert client.delete(f"{URL}/{entry_id}").status_code == 404

    client.headers["Authorization"] = owner_token
    updated = client.patch(f"{URL}/{entry_id}", json={"title": "南京早点"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "南京早点"
    assert client.delete(f"{URL}/{entry_id}").status_code == 204
    assert client.get(URL).json() == []
    assert client.get(f"{URL}/{entry_id}").status_code == 404


def test_knowledge_rejects_invalid_category_city_and_boundaries(client: TestClient) -> None:
    invalid = [
        {**ENTRY, "category": "other"},
        {**ENTRY, "body": "x" * 8001},
        {**ENTRY, "body": "   "},
        {**ENTRY, "title": "x" * 121},
        {**ENTRY, "tags": ["x"] * 9},
        {**ENTRY, "city_code": "320106", "city_name": "鼓楼区"},
        {**ENTRY, "city_code": "999999", "city_name": "南京市"},
        {**ENTRY, "city_code": "320100", "city_name": "苏州市"},
    ]
    for payload in invalid:
        assert client.post(URL, json=payload).status_code == 422
    assert client.get(URL).json() == []


def test_knowledge_accepts_municipality_and_direct_administered_city(client: TestClient) -> None:
    for city_code, city_name in [("110000", "北京市"), ("429004", "仙桃市")]:
        response = client.post(URL, json={
            **ENTRY, "city_code": city_code, "city_name": city_name,
        })
        assert response.status_code == 201
    assert len(client.get(URL).json()) == 2
