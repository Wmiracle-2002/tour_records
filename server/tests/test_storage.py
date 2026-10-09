from io import BytesIO
import sys
from types import ModuleType

import pytest

from app.core.config import Settings
from app.storage import CosObjectStorage, StorageNotConfigured, create_storage


def test_storage_is_disabled_without_credentials() -> None:
    storage = create_storage(
        Settings(cos_bucket=None, cos_secret_id=None, cos_secret_key=None)
    )

    with pytest.raises(StorageNotConfigured):
        storage.upload("records/1/photo.jpg", BytesIO(b"image"), "image/jpeg")


def test_cos_storage_uses_bucket_region_and_presigned_download(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs):
            calls["config"] = kwargs

    class FakeClient:
        def __init__(self, config):
            calls["client_config"] = config

        def put_object(self, **kwargs):
            calls["put"] = kwargs

        def get_presigned_download_url(self, **kwargs):
            calls["url"] = kwargs
            return "https://signed.test/image"

        def delete_object(self, **kwargs):
            calls["delete"] = kwargs

    fake_module = ModuleType("qcloud_cos")
    fake_module.CosConfig = FakeConfig
    fake_module.CosS3Client = FakeClient
    monkeypatch.setitem(sys.modules, "qcloud_cos", fake_module)

    storage = CosObjectStorage(
        Settings(
            cos_bucket="footmark-1489262329",
            cos_region="ap-hongkong",
            cos_secret_id="secret-id",
            cos_secret_key="secret-key",
        )
    )
    body = BytesIO(b"original")

    storage.upload("records/7/photo.jpg", body, "image/jpeg")
    assert storage.url("records/7/photo.jpg") == "https://signed.test/image"
    storage.delete("records/7/photo.jpg")

    assert calls["config"] == {
        "Region": "ap-hongkong",
        "SecretId": "secret-id",
        "SecretKey": "secret-key",
        "Token": None,
        "Scheme": "https",
    }
    assert calls["put"]["Bucket"] == "footmark-1489262329"
    assert calls["put"]["Key"] == "records/7/photo.jpg"
    assert calls["put"]["ContentType"] == "image/jpeg"
    assert calls["url"] == {
        "Bucket": "footmark-1489262329",
        "Key": "records/7/photo.jpg",
        "Expired": 3600,
    }
    assert calls["delete"] == {
        "Bucket": "footmark-1489262329",
        "Key": "records/7/photo.jpg",
    }
