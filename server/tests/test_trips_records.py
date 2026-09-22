from fastapi.testclient import TestClient


def trip_payload(city_code: str = "110100") -> dict:
    return {
        "province_code": "110000",
        "city_code": city_code,
        "city_name": "北京市",
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
    }


def record_payload(date: str = "2026-09-02", **changes) -> dict:
    return {
        "type": "ATTRACTION",
        "name": "故宫",
        "date": date,
        "rating": None,
        "cost": None,
        "notes": None,
        **changes,
    }


def test_trip_and_record_crud_with_sorting(client: TestClient) -> None:
    first = client.post("/api/v1/trips", json=trip_payload())
    assert first.status_code == 201
    trip_id = first.json()["id"]

    created = client.post(f"/api/v1/trips/{trip_id}/records", json=record_payload())
    assert created.status_code == 201
    record_id = created.json()["id"]
    assert created.json()["cost"] is None

    food = client.post(
        f"/api/v1/trips/{trip_id}/records",
        json=record_payload("2026-09-03", type="FOOD", name="烤鸭", cost="88.50"),
    )
    assert food.status_code == 201
    assert client.get(f"/api/v1/records/{record_id}").json()["name"] == "故宫"
    assert [item["name"] for item in client.get(f"/api/v1/trips/{trip_id}").json()["records"]] == ["烤鸭", "故宫"]

    edited = client.patch(
        f"/api/v1/records/{record_id}", json={"name": "故宫博物院", "rating": "4.5", "notes": "好看"}
    )
    assert edited.status_code == 200
    assert edited.json()["rating"] == "4.5"
    assert edited.json()["name"] == "故宫博物院"
    assert edited.json()["notes"] == "好看"

    trip_edit = client.patch(f"/api/v1/trips/{trip_id}", json={"end_date": "2026-09-04"})
    assert trip_edit.status_code == 200
    assert trip_edit.json()["end_date"] == "2026-09-04"
    assert client.get("/api/v1/trips").json()[0]["id"] == trip_id

    assert client.delete(f"/api/v1/trips/{trip_id}").status_code == 204
    assert client.get(f"/api/v1/records/{record_id}").status_code == 404
    assert client.get("/api/v1/trips").json() == []


def test_date_bounds_validation_and_missing_resources(client: TestClient) -> None:
    assert client.post(
        "/api/v1/trips", json={**trip_payload(), "end_date": "2026-08-31"}
    ).status_code == 422
    trip_id = client.post("/api/v1/trips", json=trip_payload()).json()["id"]

    for date in ("2026-08-31", "2026-09-04"):
        assert client.post(
            f"/api/v1/trips/{trip_id}/records", json=record_payload(date)
        ).status_code == 422
    assert client.post(
        f"/api/v1/trips/{trip_id}/records", json=record_payload("2026-09-01")
    ).status_code == 201
    assert client.post(
        f"/api/v1/trips/{trip_id}/records", json=record_payload("2026-09-03")
    ).status_code == 201
    assert client.patch(
        f"/api/v1/trips/{trip_id}", json={"end_date": "2026-09-02"}
    ).status_code == 422
    assert client.get(f"/api/v1/trips/{trip_id}").json()["end_date"] == "2026-09-03"
    assert client.get("/api/v1/trips/9999").status_code == 404
    assert client.delete("/api/v1/records/9999").status_code == 404


def test_invalid_record_values(client: TestClient) -> None:
    trip_id = client.post("/api/v1/trips", json=trip_payload()).json()["id"]
    invalid = (
        {"type": "HOTEL"}, {"name": " "}, {"name": "x" * 101},
        {"rating": 0}, {"rating": 5.5}, {"cost": -1},
        {"cost": 10000000.01}, {"notes": "x" * 2001},
    )
    for changes in invalid:
        result = client.post(
            f"/api/v1/trips/{trip_id}/records", json=record_payload(**changes)
        )
        assert result.status_code == 422, changes
    assert client.get(f"/api/v1/trips/{trip_id}").json()["records"] == []


def test_single_day_record_and_trip_date_move_together(client: TestClient) -> None:
    trip_id = client.post(
        "/api/v1/trips", json={**trip_payload(), "end_date": "2026-09-01"}
    ).json()["id"]
    record_id = client.post(
        f"/api/v1/trips/{trip_id}/records", json=record_payload("2026-09-01")
    ).json()["id"]
    result = client.patch(
        f"/api/v1/records/{record_id}",
        json={
            "date": "2026-09-05",
            "trip": {"start_date": "2026-09-05", "end_date": "2026-09-05"},
        },
    )
    assert result.status_code == 200
    trip = client.get(f"/api/v1/trips/{trip_id}").json()
    assert trip["start_date"] == "2026-09-05"
    assert trip["end_date"] == "2026-09-05"
    assert trip["records"][0]["date"] == "2026-09-05"


def test_deleting_last_record_keeps_trip_and_stats_use_distinct_city(client: TestClient) -> None:
    trip1 = client.post("/api/v1/trips", json=trip_payload()).json()["id"]
    trip2 = client.post("/api/v1/trips", json=trip_payload()).json()["id"]
    record1 = client.post(
        f"/api/v1/trips/{trip1}/records", json=record_payload(cost="12.30")
    ).json()["id"]
    client.post(f"/api/v1/trips/{trip2}/records", json=record_payload())
    assert client.get("/api/v1/stats").json() == {
        "city_count": 1, "trip_count": 2, "total_cost": "12.30"
    }

    assert client.delete(f"/api/v1/records/{record1}").status_code == 204
    assert client.get(f"/api/v1/trips/{trip1}").json()["records"] == []
    assert client.get("/api/v1/stats").json() == {
        "city_count": 1, "trip_count": 2, "total_cost": "0.00"
    }


def test_two_sessions_observe_each_others_changes(client: TestClient) -> None:
    with TestClient(client.app) as second_device:
        credentials = second_device.post(
            "/api/v1/auth/login",
            json={"username": "shared", "password": "test-password"},
        ).json()
        second_device.headers["Authorization"] = f"Bearer {credentials['access_token']}"
        trip_id = client.post("/api/v1/trips", json=trip_payload()).json()["id"]
        record_id = client.post(
            f"/api/v1/trips/{trip_id}/records", json=record_payload()
        ).json()["id"]
        assert second_device.get("/api/v1/trips").json()[0]["records"][0]["id"] == record_id
        second_device.patch(f"/api/v1/records/{record_id}", json={"name": "新名称"})
        assert client.get(f"/api/v1/records/{record_id}").json()["name"] == "新名称"
        second_device.delete(f"/api/v1/records/{record_id}")
        assert client.get("/api/v1/trips").json()[0]["id"] == trip_id
        assert client.get("/api/v1/trips").json()[0]["records"] == []
