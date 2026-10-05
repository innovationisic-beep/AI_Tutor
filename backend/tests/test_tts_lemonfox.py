"""Unit tests for Lemonfox TTS provider + Voice Gateway route helpers."""

from __future__ import annotations

import base64
from typing import Any, Dict

import pytest

from app.core.config import Settings
from app.services.tts.lemonfox_provider import (
    LemonfoxProvider,
    LemonfoxTTSError,
    close_shared_http_client,
)
from app.services.tts.service import TTSService


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        headers: Dict[str, str] | None = None,
        json_data: Any = None,
        text: str = "",
        reason_phrase: str = "OK",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json_data = json_data
        self.text = text
        self.reason_phrase = reason_phrase

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class _FakeClient:
    """Injected httpx stand-in (persistent-client path does not use async with)."""

    def __init__(self, response: _FakeResponse, captured: Dict[str, Any] | None = None) -> None:
        self._response = response
        self.captured = captured if captured is not None else {}

    async def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any]) -> _FakeResponse:
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["json"] = json
        return self._response


@pytest.fixture(autouse=True)
async def _reset_shared_client() -> None:
    await close_shared_http_client()
    yield
    await close_shared_http_client()


@pytest.mark.asyncio
async def test_lemonfox_synthesize_raw_audio() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_API_URL = "https://api.lemonfox.ai/v1/audio/speech"
    settings.LEMONFOX_VOICE = "sarah"
    settings.LEMONFOX_LANGUAGE = "en-us"
    settings.LEMONFOX_SPEED = 0.92
    settings.LEMONFOX_TIMEOUT_SECONDS = 5.0

    captured: Dict[str, Any] = {}
    client = _FakeClient(
        _FakeResponse(content=b"ID3fake-mp3", headers={"content-type": "audio/mpeg"}),
        captured,
    )

    provider = LemonfoxProvider(settings, client=client)  # type: ignore[arg-type]
    result = await provider.synthesize("Hello world", word_timestamps=False)

    assert result.audio_bytes == b"ID3fake-mp3"
    assert result.content_type == "audio/mpeg"
    assert result.word_timestamps is None
    assert result.lemonfox_ms is not None
    assert captured["json"]["input"] == "Hello world"
    assert captured["json"]["voice"] == "sarah"
    assert captured["json"]["speed"] == 0.92
    assert "word_timestamps" not in captured["json"]
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in str(result.audio_bytes)


@pytest.mark.asyncio
async def test_lemonfox_synthesize_with_word_timestamps() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_API_URL = "https://api.lemonfox.ai/v1/audio/speech"

    audio_b64 = base64.b64encode(b"mp3-bytes").decode("ascii")
    captured: Dict[str, Any] = {}
    client = _FakeClient(
        _FakeResponse(
            headers={"content-type": "application/json"},
            json_data={
                "audio": audio_b64,
                "word_timestamps": [
                    {"word": "Hello", "start": 0.1, "end": 0.4},
                    {"word": "world", "start": 0.45, "end": 0.8},
                ],
            },
            content=b'{"audio":"..."}',
        ),
        captured,
    )

    result = await LemonfoxProvider(settings, client=client).synthesize(  # type: ignore[arg-type]
        "Hello world",
        word_timestamps=True,
    )
    assert result.audio_bytes == b"mp3-bytes"
    assert result.word_timestamps is not None
    assert len(result.word_timestamps) == 2
    assert result.word_timestamps[0].word == "Hello"
    assert captured["json"].get("word_timestamps") is True


@pytest.mark.asyncio
async def test_lemonfox_missing_key_raises() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = ""
    with pytest.raises(LemonfoxTTSError) as exc:
        await LemonfoxProvider(settings).synthesize("Hi")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_lemonfox_provider_error_mapped() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    client = _FakeClient(
        _FakeResponse(
            status_code=429,
            text='{"error":"rate limited"}',
            json_data={"error": "rate limited"},
            reason_phrase="Too Many Requests",
        )
    )

    with pytest.raises(LemonfoxTTSError) as exc:
        await LemonfoxProvider(settings, client=client).synthesize("Hi")  # type: ignore[arg-type]
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_tts_service_delegates_to_lemonfox() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_SPEED = 0.92
    captured: Dict[str, Any] = {}
    client = _FakeClient(
        _FakeResponse(content=b"abc", headers={"content-type": "audio/mpeg"}),
        captured,
    )
    provider = LemonfoxProvider(settings, client=client)  # type: ignore[arg-type]
    result = await TTSService(settings=settings, lemonfox=provider).synthesize("Speak")
    assert result.audio_bytes == b"abc"
    assert captured["json"]["speed"] == 0.92


@pytest.mark.asyncio
async def test_lemonfox_speed_override_and_clamp() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_SPEED = 0.92
    captured: Dict[str, Any] = {}
    client = _FakeClient(
        _FakeResponse(content=b"x", headers={"content-type": "audio/mpeg"}),
        captured,
    )
    provider = LemonfoxProvider(settings, client=client)  # type: ignore[arg-type]
    await provider.synthesize("Hi", speed=1.1)
    assert captured["json"]["speed"] == 1.1
    await provider.synthesize("Hi", speed=9.0)
    assert captured["json"]["speed"] == 4.0
    await provider.synthesize("Hi", speed=0.1)
    assert captured["json"]["speed"] == 0.5
    await provider.synthesize("Hi")
    assert captured["json"]["speed"] == 0.92


@pytest.mark.asyncio
async def test_ab_timestamps_vs_raw_request_shape() -> None:
    """
    A/B structural proof: timestamps path sends word_timestamps=true and expects
    JSON; raw path omits the flag and accepts audio/mpeg bytes.
    Documents the latency-relevant transport difference (no live Lemonfox call).
    """
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_API_URL = "https://api.lemonfox.ai/v1/audio/speech"

    sample = "Stomata are tiny pores on leaves that allow gas exchange."

    raw_captured: Dict[str, Any] = {}
    raw_client = _FakeClient(
        _FakeResponse(content=b"mp3-raw", headers={"content-type": "audio/mpeg"}),
        raw_captured,
    )
    raw = await LemonfoxProvider(settings, client=raw_client).synthesize(  # type: ignore[arg-type]
        sample,
        word_timestamps=False,
    )
    assert "word_timestamps" not in raw_captured["json"]
    assert raw.word_timestamps is None
    assert raw.audio_bytes == b"mp3-raw"

    ts_captured: Dict[str, Any] = {}
    audio_b64 = base64.b64encode(b"mp3-ts").decode("ascii")
    ts_client = _FakeClient(
        _FakeResponse(
            headers={"content-type": "application/json"},
            json_data={"audio": audio_b64, "word_timestamps": []},
            content=b"{}",
        ),
        ts_captured,
    )
    stamped = await LemonfoxProvider(settings, client=ts_client).synthesize(  # type: ignore[arg-type]
        sample,
        word_timestamps=True,
    )
    assert ts_captured["json"].get("word_timestamps") is True
    assert stamped.audio_bytes == b"mp3-ts"
