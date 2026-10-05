"""
Story Hook binary asset storage.

``StoryHookStorage`` is the architectural contract; the local filesystem is only
the first **provider**. Callers must treat ``storage_key`` as opaque and never
build filesystem paths, so swapping in S3/R2/GCS later needs no changes outside
this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol, runtime_checkable
from uuid import uuid4

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_EXTENSION_BY_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_STORAGE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,254}\.[a-z0-9]{1,8}$")
_KEY_HINT_RE = re.compile(r"[^a-z0-9_-]+")
_READ_CHUNK_BYTES = 64 * 1024


class StorageError(RuntimeError):
    """Provider-level failure (missing object, unwritable target, bad key)."""


@runtime_checkable
class StoryHookStorage(Protocol):
    """Binary object store for Story Hook visuals."""

    async def save(
        self,
        *,
        data: bytes,
        content_type: str,
        key_hint: Optional[str] = None,
    ) -> str:
        """Persist bytes and return the opaque ``storage_key``."""

    def open_read(self, storage_key: str) -> AsyncIterator[bytes]:
        """Stream the stored object's bytes."""

    async def delete(self, storage_key: str) -> None:
        """Remove the object. Missing objects are not an error."""

    async def exists(self, storage_key: str) -> bool:
        """True when the object is present."""

    async def copy(
        self,
        source_key: str,
        *,
        key_hint: Optional[str] = None,
    ) -> str:
        """Duplicate an object (clone/import) and return the new ``storage_key``."""


def normalize_key_hint(raw: Optional[str]) -> str:
    """Sanitize a caller hint used only as a readable prefix inside the key."""
    slug = _KEY_HINT_RE.sub("-", str(raw or "").strip().lower()).strip("-")
    return slug[:48]


def is_valid_storage_key(storage_key: str) -> bool:
    """Reject traversal, absolute paths and anything outside the key grammar."""
    key = str(storage_key or "")
    if not key or ".." in key or key.startswith("/") or "\\" in key:
        return False
    return bool(_STORAGE_KEY_RE.match(key))


def extension_for_mime(content_type: str) -> str:
    return _EXTENSION_BY_MIME.get(str(content_type or "").strip().lower(), ".bin")


class LocalStoryHookStorage:
    """
    Development provider backed by the local filesystem.

    Not the production model: a multi-instance deployment needs a shared object
    store behind the same protocol.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, storage_key: str) -> Path:
        if not is_valid_storage_key(storage_key):
            raise StorageError(f"Invalid storage_key: {storage_key!r}")
        path = (self._root / storage_key).resolve()
        if not path.is_relative_to(self._root):
            raise StorageError(f"storage_key escapes storage root: {storage_key!r}")
        return path

    def _build_key(self, *, content_type: str, key_hint: Optional[str]) -> str:
        prefix = normalize_key_hint(key_hint)
        name = f"{prefix}-{uuid4().hex}" if prefix else uuid4().hex
        return f"{name}{extension_for_mime(content_type)}"

    async def save(
        self,
        *,
        data: bytes,
        content_type: str,
        key_hint: Optional[str] = None,
    ) -> str:
        storage_key = self._build_key(content_type=content_type, key_hint=key_hint)
        path = self._resolve(storage_key)
        await asyncio.to_thread(self._write_sync, path, data)
        return storage_key

    @staticmethod
    def _write_sync(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp sibling then move, so a crash cannot leave a
        # half-written image visible under a committed storage_key.
        staging = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            staging.write_bytes(data)
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)

    async def open_read(self, storage_key: str) -> AsyncIterator[bytes]:
        path = self._resolve(storage_key)
        if not await asyncio.to_thread(path.is_file):
            raise StorageError(f"storage_key not found: {storage_key!r}")
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, _READ_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, storage_key: str) -> None:
        try:
            path = self._resolve(storage_key)
        except StorageError:
            logger.warning("[STORY_HOOK_STORAGE] delete_invalid_key key=%s", storage_key)
            return
        await asyncio.to_thread(path.unlink, True)

    async def exists(self, storage_key: str) -> bool:
        try:
            path = self._resolve(storage_key)
        except StorageError:
            return False
        return await asyncio.to_thread(path.is_file)

    async def copy(
        self,
        source_key: str,
        *,
        key_hint: Optional[str] = None,
    ) -> str:
        source = self._resolve(source_key)
        if not await asyncio.to_thread(source.is_file):
            raise StorageError(f"storage_key not found: {source_key!r}")
        suffix = source.suffix or ".bin"
        prefix = normalize_key_hint(key_hint)
        name = f"{prefix}-{uuid4().hex}" if prefix else uuid4().hex
        target_key = f"{name}{suffix}"
        target = self._resolve(target_key)
        await asyncio.to_thread(self._copy_sync, source, target)
        return target_key

    @staticmethod
    def _copy_sync(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


_storage: Optional[StoryHookStorage] = None


def build_story_hook_storage() -> StoryHookStorage:
    """Construct the configured provider. Only ``local`` ships in v1."""
    from app.core.config import settings

    provider = str(settings.STORY_HOOK_STORAGE_PROVIDER or "local").strip().lower()
    if provider == "local":
        return LocalStoryHookStorage(settings.STORY_HOOK_LOCAL_ROOT)
    raise StorageError(
        f"Unsupported STORY_HOOK_STORAGE_PROVIDER '{provider}'. Supported: local"
    )


def get_story_hook_storage() -> StoryHookStorage:
    """Process-wide provider instance (FastAPI dependency friendly)."""
    global _storage
    if _storage is None:
        _storage = build_story_hook_storage()
    return _storage


def set_story_hook_storage(storage: Optional[StoryHookStorage]) -> None:
    """Override the provider (tests use a fake/temp-dir provider)."""
    global _storage
    _storage = storage
