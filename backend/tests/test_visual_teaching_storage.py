"""Visual Teaching storage smoke tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.storage.visual_teaching_storage import (
    LocalVisualTeachingStorage,
    is_valid_storage_key,
)
from app.services.visual_teaching.image_probe import probe_image_dimensions


def test_storage_key_grammar():
    assert is_valid_storage_key("leaf-abc123.jpg")
    assert not is_valid_storage_key("../etc/passwd")
    assert not is_valid_storage_key("/abs/path.png")


@pytest.mark.asyncio
async def test_local_storage_roundtrip(tmp_path: Path):
    storage = LocalVisualTeachingStorage(tmp_path)
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    key = await storage.save(data=data, content_type="image/png", key_hint="demo")
    assert await storage.exists(key)
    chunks = []
    async for chunk in storage.open_read(key):
        chunks.append(chunk)
    assert b"".join(chunks) == data
    copy_key = await storage.copy(key, key_hint="demo-copy")
    assert copy_key != key
    assert await storage.exists(copy_key)
    await storage.delete(key)
    assert not await storage.exists(key)


def test_png_probe():
    # Minimal IHDR-bearing PNG header
    data = bytearray(b"\x89PNG\r\n\x1a\n")
    data += b"\x00\x00\x00\rIHDR"
    data += (100).to_bytes(4, "big")  # width
    data += (50).to_bytes(4, "big")  # height
    data += b"\x00" * 5
    w, h = probe_image_dimensions(bytes(data), "image/png")
    assert w == 100
    assert h == 50
