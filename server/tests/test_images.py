from typing import BinaryIO

from fastapi.testclient import TestClient


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def upload(self, object_key: str, body: BinaryIO, content_type: str | None) -> None:
        self.uploaded[object_key] = body.read()

    def url(self, object_key: str) -> str:
        return f"https://images.test/{object_key}"

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)
        self.uploaded.pop(object_key, None)


def create_record(client: TestClient) -> int:
    trip = client.post(
        "/api/v1/trips",
        json={
            "province_code": "110000",
            "city_code": "110100",
            "city_name": "Beijing",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
        },
    )
    assert trip.status_code == 201
    record = client.post(
        f"/api/v1/trips/{trip.json()['id']}/records",
        json={
            "type": "ATTRACTION",
            "name": "Forbidden City",
            "date": "2026-09-02",
            "rating": None,
            "cost": None,
            "notes": None,
        },
    )
    assert record.status_code == 201
    return record.json()["id"]


def upload(client: TestClient, record_id: int, name: str = "photo.jpg"):
    return client.post(
        f"/api/v1/records/{record_id}/images",
        files={"file": (name, b"original-image", "image/jpeg")},
    )


def test_upload_list_and_delete_image(client: TestClient) -> None:
    storage = FakeStorage()
    client.app.state.storage = storage
    record_id = create_record(client)

    uploaded = upload(client, record_id)

    assert uploaded.status_code == 201
    image = uploaded.json()
    assert image["record_id"] == record_id
    assert image["object_key"].startswith(f"records/{record_id}/")
    assert image["url"] == f"https://images.test/{image['object_key']}"
    assert storage.uploaded[image["object_key"]] == b"original-image"

    listed = client.get(f"/api/v1/records/{record_id}/images")
    assert listed.status_code == 200
    assert listed.json() == [image]
    assert client.get(f"/api/v1/records/{record_id}").json()["images"] == [image]

    deleted = client.delete(f"/api/v1/images/{image['id']}")
    assert deleted.status_code == 204
    assert storage.deleted == [image["object_key"]]
    assert client.get(f"/api/v1/records/{record_id}/images").json() == []


def test_record_allows_at_most_nine_images(client: TestClient) -> None:
    storage = FakeStorage()
    client.app.state.storage = storage
    record_id = create_record(client)

    for index in range(9):
        assert upload(client, record_id, f"photo-{index}.jpg").status_code == 201

    rejected = upload(client, record_id, "photo-9.jpg")
    assert rejected.status_code == 422
    assert len(storage.uploaded) == 9


def test_deleting_record_deletes_all_cos_objects(client: TestClient) -> None:
    storage = FakeStorage()
    client.app.state.storage = storage
    record_id = create_record(client)
    keys = [upload(client, record_id, f"photo-{index}.jpg").json()["object_key"] for index in range(2)]

    deleted = client.delete(f"/api/v1/records/{record_id}")

    assert deleted.status_code == 204
    assert storage.deleted == keys
    assert storage.uploaded == {}
