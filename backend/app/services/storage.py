"""Хранилище файлов: локальные файлы в dev, S3-совместимое в проде.

Документы верификации — чувствительные ПДн: живут в отдельном приватном
контуре (в проде — отдельный шифруемый бакет, п. 6 ТЗ), наружу не отдаются
напрямую, только через эндпоинты с проверкой прав и журналом доступа.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Protocol

from app.core.config import settings


class Storage(Protocol):
    async def put(self, key: str, content: bytes, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class LocalStorage:
    """Файлы под backend/var/storage/<bucket>/... — для разработки без S3."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        # Ключ не должен выходить за пределы корня хранилища.
        safe = re.sub(r"[^\w./-]", "_", key).lstrip("/")
        path = (self._root / safe).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError("Некорректный ключ хранилища")
        return path

    async def put(self, key: str, content: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)


class S3Storage:
    """S3-совместимый бэкенд (прод). Требует boto3 — ставится при подключении S3."""

    def __init__(self, bucket: str | None = None) -> None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Для S3-хранилища установите boto3: pip install boto3"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        self._bucket = bucket or settings.s3_documents_bucket

    async def put(self, key: str, content: bytes, content_type: str | None = None) -> None:
        import asyncio  # noqa: PLC0415

        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=content_type or "application/octet-stream",
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        import asyncio  # noqa: PLC0415

        response = await asyncio.to_thread(
            self._client.get_object, Bucket=self._bucket, Key=key
        )
        return response["Body"].read()

    async def delete(self, key: str) -> None:
        import asyncio  # noqa: PLC0415

        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)


_storage: Storage | None = None
_media_storage: Storage | None = None


def _local_root() -> Path:
    return Path(__file__).resolve().parents[2] / "var" / "storage"


def get_document_storage() -> Storage:
    """Закрытый контур: документы верификации, доступ только модераторам."""
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.s3_endpoint_url else LocalStorage(_local_root())
    return _storage


def get_media_storage() -> Storage:
    """Медиа приложения (вложения чата, аватары) — отдельно от документного бакета."""
    global _media_storage
    if _media_storage is None:
        if settings.s3_endpoint_url:
            _media_storage = S3Storage(bucket=settings.s3_media_bucket)
        else:
            _media_storage = LocalStorage(_local_root() / "media")
    return _media_storage


def _extension(file_name: str | None) -> str:
    if file_name and "." in file_name:
        return "." + file_name.rsplit(".", 1)[1].lower()[:8]
    return ""


def make_document_key(user_id: str, document_type: str, file_name: str | None) -> str:
    """Ключ вида documents/<user>/<type>/<random>.<ext> — имя файла не раскрывается."""
    return f"documents/{user_id}/{document_type}/{secrets.token_urlsafe(16)}{_extension(file_name)}"


def make_chat_attachment_key(thread_id: str, file_name: str | None) -> str:
    """Вложение чата: chat/<thread>/<random>.<ext>."""
    return f"chat/{thread_id}/{secrets.token_urlsafe(16)}{_extension(file_name)}"


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
