from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredObject:
    key: str
    url: str
    size_bytes: int


class LocalStorage:
    def __init__(self, root: Path, public_base_url: str):
        self.root = root
        self.public_base_url = public_base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def put_file(self, key: str, source: Path) -> StoredObject:
        safe_key = normalize_key(key)
        target = self.root / safe_key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return StoredObject(key=safe_key, url=f"/api/storage/{safe_key}", size_bytes=target.stat().st_size)

    def open_file(self, key: str) -> Path:
        safe_key = normalize_key(key)
        path = (self.root / safe_key).resolve()
        root = self.root.resolve()
        if root not in [path, *path.parents] or not path.is_file():
            raise FileNotFoundError(key)
        return path

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        safe_prefix = normalize_key(prefix).rstrip("/")
        root = (self.root / safe_prefix).resolve()
        if not root.exists():
            return []
        objects: list[StoredObject] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(self.root).as_posix()
            objects.append(StoredObject(key=key, url=f"/api/storage/{key}", size_bytes=path.stat().st_size))
        return objects


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        public_base_url: str | None,
    ):
        if not bucket:
            raise RuntimeError("s3_bucket_required")
        try:
            import boto3  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"s3_dependency_missing: {exc}") from exc
        client_kwargs: dict[str, Any] = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            client_kwargs["aws_access_key_id"] = access_key_id
            client_kwargs["aws_secret_access_key"] = secret_access_key
        self.client = boto3.client("s3", **client_kwargs)
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None

    def put_file(self, key: str, source: Path) -> StoredObject:
        safe_key = normalize_key(key)
        self.client.upload_file(str(source), self.bucket, safe_key)
        return StoredObject(key=safe_key, url=self.object_url(safe_key), size_bytes=source.stat().st_size)

    def object_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return f"s3://{self.bucket}/{key}"

    def write_healthcheck(self) -> None:
        key = f".healthcheck/{uuid.uuid4()}.txt"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=b"ok")
        self.client.delete_object(Bucket=self.bucket, Key=key)


def normalize_key(key: str) -> str:
    safe = key.strip().replace("\\", "/").lstrip("/")
    if not safe or ".." in safe.split("/"):
        raise ValueError("invalid_storage_key")
    return safe


def publish_artifacts_to_storage(
    *,
    storage_backend: str,
    storage_dir: Path,
    public_base_url: str,
    task_id: str,
    output_dir: Path,
    artifacts: list[dict[str, Any]],
    s3_bucket: str | None = None,
    s3_endpoint_url: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_public_base_url: str | None = None,
) -> list[dict[str, Any]]:
    if storage_backend == "local":
        storage: Any = LocalStorage(storage_dir, public_base_url)
    elif storage_backend == "s3":
        storage = S3Storage(
            bucket=s3_bucket or "",
            endpoint_url=s3_endpoint_url,
            access_key_id=s3_access_key_id,
            secret_access_key=s3_secret_access_key,
            public_base_url=s3_public_base_url,
        )
    else:
        raise RuntimeError(f"unsupported_storage_backend:{storage_backend}")

    published: list[dict[str, Any]] = []
    for artifact in artifacts:
        source = output_dir / artifact["path"]
        if not source.is_file():
            published.append(artifact)
            continue
        stored = storage.put_file(f"tasks/{task_id}/{artifact['path']}", source)
        published.append({**artifact, "storage_key": stored.key, "storage_url": stored.url})
    return published


def storage_health(settings: Any) -> dict[str, str | bool | None]:
    if settings.storage_backend == "local":
        try:
            settings.storage_dir.mkdir(parents=True, exist_ok=True)
            probe = settings.storage_dir / ".healthcheck"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {"backend": "local", "available": True, "reason": None}
        except Exception as exc:
            return {"backend": "local", "available": False, "reason": str(exc)}
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            return {"backend": "s3", "available": False, "reason": "s3_bucket_required"}
        try:
            storage = S3Storage(
                bucket=settings.s3_bucket,
                endpoint_url=settings.s3_endpoint_url,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key,
                public_base_url=settings.s3_public_base_url,
            )
            storage.write_healthcheck()
            return {"backend": "s3", "available": True, "reason": None}
        except Exception as exc:
            return {"backend": "s3", "available": False, "reason": str(exc)}
    return {"backend": settings.storage_backend, "available": False, "reason": "unsupported_storage_backend"}
