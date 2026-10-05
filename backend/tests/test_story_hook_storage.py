"""Story Hook storage provider contract: opaque keys, safe paths, copy/delete."""

from __future__ import annotations

import pytest

from app.services.storage.story_hook_storage import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_IMAGE_BYTES,
    LocalStoryHookStorage,
    StorageError,
    StoryHookStorage,
    build_story_hook_storage,
    extension_for_mime,
    is_valid_storage_key,
    normalize_key_hint,
    set_story_hook_storage,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 16


@pytest.fixture()
def storage(tmp_path) -> LocalStoryHookStorage:
    return LocalStoryHookStorage(tmp_path / "story_hook")


async def _read_all(store: LocalStoryHookStorage, key: str) -> bytes:
    out = bytearray()
    async for chunk in store.open_read(key):
        out.extend(chunk)
    return bytes(out)


def test_local_provider_satisfies_the_protocol(storage):
    assert isinstance(storage, StoryHookStorage)


@pytest.mark.asyncio
async def test_save_returns_an_opaque_key_that_reads_back(storage):
    key = await storage.save(data=PNG, content_type="image/png", key_hint="Stomata Surface")

    # Readable prefix for humans, but no directory structure the caller could rely on.
    assert key.startswith("stomata-surface-")
    assert key.endswith(".png")
    assert "/" not in key
    assert await storage.exists(key) is True
    assert await _read_all(storage, key) == PNG


@pytest.mark.asyncio
async def test_two_saves_never_collide(storage):
    first = await storage.save(data=PNG, content_type="image/png", key_hint="leaf")
    second = await storage.save(data=PNG, content_type="image/png", key_hint="leaf")

    assert first != second
    assert await storage.exists(first)
    assert await storage.exists(second)


@pytest.mark.asyncio
async def test_copy_duplicates_bytes_under_a_new_key(storage):
    source = await storage.save(data=PNG, content_type="image/png", key_hint="leaf")

    target = await storage.copy(source, key_hint="leaf")

    assert target != source
    assert await _read_all(storage, target) == PNG
    # Independent objects: deleting the source leaves the copy intact.
    await storage.delete(source)
    assert await storage.exists(source) is False
    assert await storage.exists(target) is True


@pytest.mark.asyncio
async def test_copy_of_a_missing_object_fails_loudly(storage):
    with pytest.raises(StorageError):
        await storage.copy("does-not-exist.png")


@pytest.mark.asyncio
async def test_delete_is_idempotent(storage):
    key = await storage.save(data=PNG, content_type="image/png")

    await storage.delete(key)
    await storage.delete(key)

    assert await storage.exists(key) is False


@pytest.mark.asyncio
async def test_reading_a_missing_object_raises(storage):
    with pytest.raises(StorageError):
        await _read_all(storage, "missing.png")


@pytest.mark.parametrize(
    "bad_key",
    [
        "../secrets.png",
        "/etc/passwd",
        "nested/../../escape.png",
        "windows\\path.png",
        "",
        "no-extension",
    ],
)
@pytest.mark.asyncio
async def test_traversal_and_malformed_keys_are_rejected(storage, bad_key):
    assert is_valid_storage_key(bad_key) is False
    assert await storage.exists(bad_key) is False
    with pytest.raises(StorageError):
        await _read_all(storage, bad_key)
    # Delete swallows bad keys so cleanup paths cannot explode.
    await storage.delete(bad_key)


@pytest.mark.asyncio
async def test_nothing_is_written_outside_the_root(storage, tmp_path):
    await storage.save(data=PNG, content_type="image/png")

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written
    assert all(storage.root in p.parents for p in written)


@pytest.mark.asyncio
async def test_no_partial_files_survive_a_save(storage):
    await storage.save(data=PNG, content_type="image/png")

    assert not list(storage.root.glob("*.part"))


def test_key_hint_is_sanitized():
    assert normalize_key_hint("  Stomata / Surface!! ") == "stomata-surface"
    assert normalize_key_hint("../../etc") == "etc"
    assert normalize_key_hint(None) == ""
    assert len(normalize_key_hint("x" * 200)) == 48


def test_extension_follows_the_mime_allowlist():
    assert {extension_for_mime(m) for m in ALLOWED_IMAGE_MIME_TYPES} == {
        ".jpg",
        ".png",
        ".webp",
    }
    assert extension_for_mime("application/pdf") == ".bin"
    assert MAX_IMAGE_BYTES == 5 * 1024 * 1024


def test_factory_rejects_an_unknown_provider(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "STORY_HOOK_STORAGE_PROVIDER", "s3")
    with pytest.raises(StorageError):
        build_story_hook_storage()


def test_factory_builds_the_local_provider(monkeypatch, tmp_path):
    from app.core import config

    monkeypatch.setattr(config.settings, "STORY_HOOK_STORAGE_PROVIDER", "local")
    monkeypatch.setattr(config.settings, "STORY_HOOK_LOCAL_ROOT", str(tmp_path / "x"))
    try:
        built = build_story_hook_storage()
        assert isinstance(built, LocalStoryHookStorage)
    finally:
        set_story_hook_storage(None)
