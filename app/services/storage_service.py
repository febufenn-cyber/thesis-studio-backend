"""Storage service — abstract interface with R2 and local-filesystem backends.

Backend selection (STORAGE_BACKEND setting):
  "r2"    — always use Cloudflare R2 (boto3 + S3-compatible endpoint).
  "local" — always use LOCAL_STORAGE_DIR on disk.
  "auto"  — R2 if all four credential settings are non-empty and not the
            "replace_me" placeholder, otherwise local.

All public methods are async.  boto3 is synchronous; every boto3 call is
wrapped in asyncio.to_thread so it does not block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class StorageService(ABC):
    """Abstract storage backend.  Concrete subclasses implement each method."""

    @abstractmethod
    async def upload_file(
        self,
        local_path: str,
        key: str,
        content_type: str = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
    ) -> int:
        """Upload a file to the backend under *key*.

        Returns the size of the uploaded file in bytes.
        """

    @abstractmethod
    async def download_to_temp(self, key: str) -> str:
        """Download the object identified by *key* to a temporary local file.

        Returns the absolute path of the temp file.  The caller is responsible
        for deleting it after use.
        """

    @abstractmethod
    async def presigned_download_url(
        self,
        key: str,
        filename: str,
        expires_in: int = 900,
    ) -> str | None:
        """Return a time-limited URL for the client to download the file.

        Returns None if the backend does not support URL generation (local);
        the caller must then serve the bytes directly.
        """

    @abstractmethod
    async def open_local_path(self, key: str) -> str:
        """Return the absolute local filesystem path for *key*.

        Intended for FastAPI FileResponse.  Only the local backend implements
        this; R2StorageService raises NotImplementedError.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object identified by *key* from the backend."""


# ---------------------------------------------------------------------------
# R2 backend
# ---------------------------------------------------------------------------


class R2StorageService(StorageService):
    """Cloudflare R2 storage backend (S3-compatible, via boto3)."""

    def __init__(self) -> None:
        """Initialise the boto3 S3 client from application settings."""
        settings = get_settings()
        endpoint = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        self._bucket = settings.R2_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="auto",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        )

    async def upload_file(
        self,
        local_path: str,
        key: str,
        content_type: str = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
    ) -> int:
        """Upload *local_path* to R2 under *key*; return file size in bytes."""
        size = os.path.getsize(local_path)

        def _upload() -> None:
            self._client.upload_file(
                local_path,
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )

        await asyncio.to_thread(_upload)
        log.info("r2 upload: key=%s size=%d", key, size)
        return size

    async def download_to_temp(self, key: str) -> str:
        """Download *key* from R2 to a temporary file and return its path."""
        fd, tmp_path = tempfile.mkstemp(prefix="r2dl_")
        os.close(fd)

        def _download() -> None:
            self._client.download_file(self._bucket, key, tmp_path)

        try:
            await asyncio.to_thread(_download)
        except (BotoCoreError, ClientError):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        log.info("r2 download: key=%s -> %s", key, tmp_path)
        return tmp_path

    async def presigned_download_url(
        self,
        key: str,
        filename: str,
        expires_in: int = 900,
    ) -> str | None:
        """Generate a presigned GET URL for *key* with a content-disposition header."""
        def _sign() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                },
                ExpiresIn=expires_in,
            )

        url: str = await asyncio.to_thread(_sign)
        return url

    async def open_local_path(self, key: str) -> str:
        """Not supported for R2; always raises NotImplementedError."""
        raise NotImplementedError(
            "open_local_path is not supported by the R2 backend; "
            "use presigned_download_url or download_to_temp instead."
        )

    async def delete(self, key: str) -> None:
        """Delete *key* from the R2 bucket."""
        def _delete() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(_delete)
        log.info("r2 delete: key=%s", key)


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


def _sanitize_key(key: str) -> None:
    """Raise ValueError if *key* contains path-traversal sequences."""
    if ".." in key:
        raise ValueError(f"Storage key must not contain '..': {key!r}")
    if key.startswith("/"):
        raise ValueError(f"Storage key must not start with '/': {key!r}")


class LocalStorageService(StorageService):
    """Local filesystem storage backend, rooted at LOCAL_STORAGE_DIR."""

    def __init__(self) -> None:
        """Resolve and create the storage root directory."""
        settings = get_settings()
        self._root = Path(settings.LOCAL_STORAGE_DIR).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        """Return the absolute path for *key* after sanitisation."""
        _sanitize_key(key)
        return self._root / key

    async def upload_file(
        self,
        local_path: str,
        key: str,
        content_type: str = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
    ) -> int:
        """Copy *local_path* into the local storage root under *key*.

        Returns the file size in bytes.  content_type is accepted for interface
        compatibility but is not stored (filesystem has no metadata layer).
        """
        dest = self._key_path(key)

        def _copy() -> int:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, dest)
            return os.path.getsize(local_path)

        size = await asyncio.to_thread(_copy)
        log.info("local upload: key=%s size=%d", key, size)
        return size

    async def download_to_temp(self, key: str) -> str:
        """Copy the file for *key* to a temporary file and return its path."""
        src = self._key_path(key)
        fd, tmp_path = tempfile.mkstemp(prefix="localdl_")
        os.close(fd)
        await asyncio.to_thread(shutil.copy2, src, tmp_path)
        log.info("local download: key=%s -> %s", key, tmp_path)
        return tmp_path

    async def presigned_download_url(
        self,
        key: str,
        filename: str,
        expires_in: int = 900,
    ) -> str | None:
        """Return None — the local backend has no URL-signing capability."""
        return None

    async def open_local_path(self, key: str) -> str:
        """Return the absolute path for *key*, suitable for FileResponse."""
        return str(self._key_path(key))

    async def delete(self, key: str) -> None:
        """Delete the file for *key* from the local storage root."""
        path = self._key_path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            log.warning("local delete: key=%s not found (already deleted?)", key)
        else:
            log.info("local delete: key=%s", key)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _r2_settings_complete() -> bool:
    """Return True if all four R2 credential settings are present and not placeholder.

    The four settings that gate R2 access are: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME.  R2_PUBLIC_URL is not required for
    presigned/private access so it is intentionally excluded.
    """
    settings = get_settings()
    candidates = (
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )
    return all(v and "replace_me" not in v.lower() for v in candidates)


@lru_cache
def get_storage_service() -> StorageService:
    """Return the cached singleton StorageService for this process.

    Backend is selected by the STORAGE_BACKEND setting:
      "r2"    — R2StorageService
      "local" — LocalStorageService
      "auto"  — R2 if all four R2 credential settings are populated and not
                 placeholder values, otherwise LocalStorageService.
    """
    settings = get_settings()
    backend = settings.STORAGE_BACKEND.lower()

    if backend == "r2":
        svc: StorageService = R2StorageService()
        log.info("storage backend: r2 (forced via STORAGE_BACKEND=r2)")
    elif backend == "local":
        svc = LocalStorageService()
        log.info("storage backend: local (forced via STORAGE_BACKEND=local)")
    else:
        # "auto" — choose based on whether R2 credentials are configured.
        if _r2_settings_complete():
            svc = R2StorageService()
            log.info("storage backend: r2 (auto — R2 credentials present)")
        else:
            svc = LocalStorageService()
            log.info("storage backend: local (auto — R2 credentials absent or placeholder)")

    return svc
