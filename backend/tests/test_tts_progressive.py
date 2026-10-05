"""Session store + progressive stream unit tests (no live Lemonfox)."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app
from app.services.tts.lemonfox_provider import (
    LemonfoxProvider,
    LemonfoxTTSError,
    close_shared_http_client,
)
from app.services.tts.stream_sessions import (
    clear_all_speech_stream_sessions,
    create_speech_stream_session,
    take_speech_stream_session,
)


class _FakeStreamResponse:
    def __init__(
        self,
        *,
        chunks: List[bytes],
        status_code: int = 200,
        headers: Dict[str, str] | None = None,
        error_text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "audio/mpeg"}
        self._chunks = chunks
        self.text = error_text
        self.reason_phrase = "OK" if status_code < 400 else "Error"
        self.content = b"".join(chunks)

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return self.content

    def json(self) -> Any:
        raise ValueError("no json")


class _FakeStreamClient:
    def __init__(self, response: _FakeStreamResponse, captured: Dict[str, Any]) -> None:
        self._response = response
        self.captured = captured

    def stream(self, method: str, url: str, headers: Dict[str, str], json: Dict[str, Any]):
        self.captured["method"] = method
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["json"] = json
        return self._response


@pytest.fixture(autouse=True)
async def _reset() -> None:
    await close_shared_http_client()
    await clear_all_speech_stream_sessions()
    yield
    await clear_all_speech_stream_sessions()
    await close_shared_http_client()


@pytest.mark.asyncio
async def test_stream_session_single_use() -> None:
    sid, ticket = await create_speech_stream_session(text="Hello", user_id="u1")
    sess = await take_speech_stream_session(sid, ticket)
    assert sess is not None
    assert sess.text == "Hello"
    assert await take_speech_stream_session(sid, ticket) is None


@pytest.mark.asyncio
async def test_stream_session_bad_ticket() -> None:
    sid, _ticket = await create_speech_stream_session(text="Hello", user_id="u1")
    assert await take_speech_stream_session(sid, "wrong-ticket-value") is None


@pytest.mark.asyncio
async def test_iter_mp3_stream_yields_chunks_progressively() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    settings.LEMONFOX_API_URL = "https://api.lemonfox.ai/v1/audio/speech"
    settings.LEMONFOX_SPEED = 0.92
    captured: Dict[str, Any] = {}
    client = _FakeStreamClient(
        _FakeStreamResponse(chunks=[b"ID3a", b"bcde", b"fghi"]),
        captured,
    )
    provider = LemonfoxProvider(settings, client=client)  # type: ignore[arg-type]
    out = b""
    n = 0
    async for chunk in provider.iter_mp3_stream("Hello world"):
        n += 1
        out += chunk
    assert n == 3
    assert out == b"ID3abcdefghi"
    assert captured["json"]["speed"] == 0.92
    assert "word_timestamps" not in captured["json"]


@pytest.mark.asyncio
async def test_iter_mp3_stream_upstream_error() -> None:
    settings = Settings()
    settings.LEMONFOX_API_KEY = "test-key"
    client = _FakeStreamClient(
        _FakeStreamResponse(
            chunks=[b'{"error":"nope"}'],
            status_code=500,
            headers={"content-type": "application/json"},
            error_text='{"error":"nope"}',
        ),
        {},
    )
    provider = LemonfoxProvider(settings, client=client)  # type: ignore[arg-type]
    with pytest.raises(LemonfoxTTSError):
        async for _ in provider.iter_mp3_stream("Hi"):
            pass


@pytest.mark.asyncio
async def test_stream_audio_route_requires_valid_ticket() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/tts/speech/sessions/does-not-exist/audio",
            params={"ticket": "abcdefghi"},
        )
    assert res.status_code == 404
