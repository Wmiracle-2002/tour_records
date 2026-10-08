from fastapi.testclient import TestClient


TRIP = {
    "province_code": "320000", "city_code": "320100", "city_name": "南京市",
    "start_date": "2026-10-01", "end_date": "2026-10-03",
}


def test_snapshot_then_delta_including_record_and_deletion(client: TestClient) -> None:
    first = client.post("/api/v1/trips", json=TRIP)
    assert first.status_code == 201
    trip_id = first.json()["id"]
    snapshot = client.get("/api/v1/sync/trips?limit=1")
    assert snapshot.status_code == 200
    assert [trip["id"] for trip in snapshot.json()["upserts"]] == [trip_id]
    cursor = snapshot.json()["next_cursor"]
    assert cursor
    record = client.post(f"/api/v1/trips/{trip_id}/records", json={
        "type": "ATTRACTION", "name": "中山陵", "date": "2026-10-01",
    })
    assert record.status_code == 201
    delta = client.get("/api/v1/sync/trips", params={"cursor": cursor})
    assert delta.status_code == 200
    assert delta.json()["upserts"][0]["records"][0]["name"] == "中山陵"
    assert client.delete(f"/api/v1/trips/{trip_id}").status_code == 204
    deleted = client.get("/api/v1/sync/trips", params={"cursor": delta.json()["next_cursor"]})
    assert deleted.json()["deleted_ids"] == [trip_id]


def test_sync_cursor_pages_without_skipping_trips(client: TestClient) -> None:
    ids = []
    for name in ("南京市", "苏州市", "无锡市"):
        payload = dict(TRIP, city_name=name)
        ids.append(client.post("/api/v1/trips", json=payload).json()["id"])
    cursor = None
    seen = []
    for _ in range(4):
        response = client.get("/api/v1/sync/trips", params={"limit": 1, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()
        seen.extend(trip["id"] for trip in page["upserts"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    assert seen == ids
