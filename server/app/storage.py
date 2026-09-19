from __future__ import annotations

from typing import BinaryIO, Protocol


class StorageError(RuntimeError):
    """Base error for object storage operations."""


class StorageNotConfigured(StorageError):
    """Raised when COS credentials have not been configured."""


class ObjectStorage(Protocol):
    def upload(self, object_key: str, body: BinaryIO, content_type: str | None) -> None:
        ...

    def url(self, object_key: str) -> str:
        ...

    def delete(self, object_key: str) -> None:
        ...


class DisabledObjectStorage:
    def _raise(self) -> None:
        raise StorageNotConfigured("COS storage is not configured")

    def upload(self, object_key: str, body: BinaryIO, content_type: str | None) -> None:
        self._raise()

    def url(self, object_key: str) -> str:
        self._raise()

    def delete(self, object_key: str) -> None:
        self._raise()


class CosObjectStorage:
    def __init__(self, settings) -> None:
        from qcloud_cos import CosConfig, CosS3Client

        config = CosConfig(
            Region=settings.cos_region,
            SecretId=settings.cos_secret_id,
            SecretKey=settings.cos_secret_key,
            Token=settings.cos_session_token,
            Scheme="https",
        )
        self.client = CosS3Client(config)
        self.bucket = settings.cos_bucket
        self.url_expire_seconds = settings.cos_url_expire_seconds

    def upload(self, object_key: str, body: BinaryIO, content_type: str | None) -> None:
        arguments = {
            "Bucket": self.bucket,
            "Key": object_key,
            "Body": body,
        }
        if content_type:
            arguments["ContentType"] = content_type
        self.client.put_object(**arguments)

    def url(self, object_key: str) -> str:
        return self.client.get_presigned_download_url(
            Bucket=self.bucket,
            Key=object_key,
            Expired=self.url_expire_seconds,
        )

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)


def create_storage(settings) -> ObjectStorage:
    if not settings.cos_bucket or not settings.cos_secret_id or not settings.cos_secret_key:
        return DisabledObjectStorage()
    return CosObjectStorage(settings)
