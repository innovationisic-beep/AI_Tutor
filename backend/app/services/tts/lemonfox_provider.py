"""Lemonfox AI TTS provider (official OpenAI-compatible speech endpoint)."""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.config import Settings
from app.services.tts.types import SynthesizeResult, WordTimestamp

logger = logging.getLogger(__name__)

_shared_client: Optional[httpx.AsyncClient] = None
_shared_client_lock = asyncio.Lock()
_shared_client_timeout: Optional[float] = None


class LemonfoxTTSError(Exception):
    """Raised when Lemonfox synthesis fails."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def get_shared_http_client(settings: Settings) -> httpx.AsyncClient:
    """Process-level keep-alive client (avoids per-request TLS handshake)."""
    global _shared_client, _shared_client_timeout
    timeout_s = float(settings.LEMONFOX_TIMEOUT_SECONDS)
    async with _shared_client_lock:
        if (
            _shared_client is None
            or _shared_client.is_closed
            or _shared_client_timeout != timeout_s
        ):
            if _shared_client is not None and not _shared_client.is_closed:
                await _shared_client.aclose()
            _shared_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s),
                http2=False,
            )
            _shared_client_timeout = timeout_s
        return _shared_client


async def close_shared_http_client() -> None:
    """Test / shutdown helper."""
    global _shared_client, _shared_client_timeout
    async with _shared_client_lock:
        if _shared_client is not None and not _shared_client.is_closed:
            await _shared_client.aclose()
        _shared_client = None
        _shared_client_timeout = None


class LemonfoxProvider:
    """Calls Lemonfox ``POST /v1/audio/speech`` with server-side credentials."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._settings = settings or Settings()
        self._injected_client = client

    @property
    def api_key(self) -> str:
        return (self._settings.LEMONFOX_API_KEY or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _resolve_speed(self, speed: Optional[float]) -> float:
        """Use settings speed when omitted; clamp to Lemonfox 0.5–4.0."""
        if speed is None or not math.isfinite(speed) or speed <= 0:
            value = float(getattr(self._settings, "LEMONFOX_SPEED", 0.92) or 0.92)
        else:
            value = float(speed)
        if not math.isfinite(value) or value <= 0:
            value = 0.92
        return max(0.5, min(4.0, value))

    async def _client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return self._injected_client
        return await get_shared_http_client(self._settings)

    async def synthesize(
        self,
        text: str,
        *,
        word_timestamps: bool = False,
        response_format: str = "mp3",
        speed: Optional[float] = None,
    ) -> SynthesizeResult:
        if not self.is_configured():
            raise LemonfoxTTSError(
                "LEMONFOX_API_KEY is not configured",
                status_code=503,
            )

        cleaned = (text or "").strip()
        if not cleaned:
            raise LemonfoxTTSError("input text is empty", status_code=400)

        payload: Dict[str, Any] = {
            "input": cleaned,
            "voice": self._settings.LEMONFOX_VOICE or "sarah",
            "language": self._settings.LEMONFOX_LANGUAGE or "en-us",
            "response_format": response_format or "mp3",
            "speed": self._resolve_speed(speed),
        }
        if word_timestamps:
            payload["word_timestamps"] = True

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        text_chars = len(cleaned)
        t0 = time.perf_counter()
        logger.info(
            "tts.timing lemonfox_start text_chars=%s word_timestamps=%s",
            text_chars,
            word_timestamps,
        )

        try:
            client = await self._client()
            response = await client.post(
                self._settings.LEMONFOX_API_URL,
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise LemonfoxTTSError("Lemonfox request timed out", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise LemonfoxTTSError(
                f"Lemonfox network error: {exc}",
                status_code=502,
            ) from exc

        lemonfox_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "tts.timing lemonfox_complete text_chars=%s word_timestamps=%s "
            "status=%s lemonfox_ms=%s bytes=%s",
            text_chars,
            word_timestamps,
            response.status_code,
            lemonfox_ms,
            len(response.content or b""),
        )

        if response.status_code >= 400:
            detail = _safe_error_detail(response)
            logger.warning(
                "Lemonfox TTS error status=%s detail=%s",
                response.status_code,
                detail[:200],
            )
            raise LemonfoxTTSError(
                f"Lemonfox TTS failed: {detail}",
                status_code=502,
            )

        content_type = (response.headers.get("content-type") or "").lower()

        if word_timestamps or "application/json" in content_type:
            result = _parse_timestamp_response(response)
        else:
            audio = response.content
            if not audio:
                raise LemonfoxTTSError("Lemonfox returned empty audio", status_code=502)

            media = "audio/mpeg"
            if "audio/" in content_type:
                media = content_type.split(";")[0].strip()
            elif response_format == "wav":
                media = "audio/wav"
            elif response_format == "ogg":
                media = "audio/ogg"

            result = SynthesizeResult(
                audio_bytes=audio,
                content_type=media,
                word_timestamps=None,
            )

        result.lemonfox_ms = lemonfox_ms
        result.text_chars = text_chars
        return result

    async def iter_mp3_stream(
        self,
        text: str,
        *,
        speed: Optional[float] = None,
    ) -> AsyncIterator[bytes]:
        """
        Yield raw MP3 bytes as Lemonfox sends them (no full-body buffer).

        Logs lemonfox_start / first_byte / complete. Raises LemonfoxTTSError on
        upstream failure before or during the stream.
        """
        if not self.is_configured():
            raise LemonfoxTTSError(
                "LEMONFOX_API_KEY is not configured",
                status_code=503,
            )

        cleaned = (text or "").strip()
        if not cleaned:
            raise LemonfoxTTSError("input text is empty", status_code=400)

        payload: Dict[str, Any] = {
            "input": cleaned,
            "voice": self._settings.LEMONFOX_VOICE or "sarah",
            "language": self._settings.LEMONFOX_LANGUAGE or "en-us",
            "response_format": "mp3",
            "speed": self._resolve_speed(speed),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        text_chars = len(cleaned)
        t0 = time.perf_counter()
        logger.info(
            "tts.timing lemonfox_start text_chars=%s word_timestamps=%s mode=stream",
            text_chars,
            False,
        )

        client = await self._client()
        try:
            async with client.stream(
                "POST",
                self._settings.LEMONFOX_API_URL,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    # Drain error body for detail; do not yield audio.
                    await response.aread()
                    detail = _safe_error_detail(response)
                    raise LemonfoxTTSError(
                        f"Lemonfox TTS failed: {detail}",
                        status_code=502,
                    )

                content_type = (response.headers.get("content-type") or "").lower()
                if "application/json" in content_type:
                    await response.aread()
                    raise LemonfoxTTSError(
                        "Lemonfox returned JSON on progressive MP3 path",
                        status_code=502,
                    )

                first_byte_ms: Optional[int] = None
                total = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    if first_byte_ms is None:
                        first_byte_ms = int((time.perf_counter() - t0) * 1000)
                        logger.info(
                            "tts.timing lemonfox_first_byte text_chars=%s "
                            "ttfb_ms=%s",
                            text_chars,
                            first_byte_ms,
                        )
                    total += len(chunk)
                    yield chunk

                complete_ms = int((time.perf_counter() - t0) * 1000)
                logger.info(
                    "tts.timing lemonfox_complete text_chars=%s word_timestamps=%s "
                    "status=%s lemonfox_ms=%s ttfb_ms=%s bytes=%s mode=stream",
                    text_chars,
                    False,
                    response.status_code,
                    complete_ms,
                    first_byte_ms,
                    total,
                )
                if total == 0:
                    raise LemonfoxTTSError(
                        "Lemonfox returned empty audio",
                        status_code=502,
                    )
        except LemonfoxTTSError:
            raise
        except httpx.TimeoutException as exc:
            raise LemonfoxTTSError(
                "Lemonfox request timed out",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise LemonfoxTTSError(
                f"Lemonfox network error: {exc}",
                status_code=502,
            ) from exc


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            for key in ("error", "detail", "message"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict):
                    msg = val.get("message")
                    if isinstance(msg, str) and msg.strip():
                        return msg.strip()
        return response.text[:300] or response.reason_phrase or "unknown error"
    except Exception:
        return response.text[:300] or response.reason_phrase or "unknown error"


def _parse_timestamp_response(response: httpx.Response) -> SynthesizeResult:
    try:
        data = response.json()
    except Exception as exc:
        raise LemonfoxTTSError(
            "Lemonfox returned invalid JSON for word_timestamps",
            status_code=502,
        ) from exc

    if not isinstance(data, dict):
        raise LemonfoxTTSError(
            "Lemonfox word_timestamps response was not an object",
            status_code=502,
        )

    audio_b64 = data.get("audio")
    if not isinstance(audio_b64, str) or not audio_b64.strip():
        raise LemonfoxTTSError(
            "Lemonfox word_timestamps response missing audio",
            status_code=502,
        )

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=False)
    except Exception as exc:
        raise LemonfoxTTSError(
            "Lemonfox audio base64 decode failed",
            status_code=502,
        ) from exc

    if not audio_bytes:
        raise LemonfoxTTSError("Lemonfox returned empty audio", status_code=502)

    stamps: List[WordTimestamp] = []
    raw_stamps = data.get("word_timestamps") or data.get("timestamps") or []
    if isinstance(raw_stamps, list):
        for item in raw_stamps:
            if not isinstance(item, dict):
                continue
            word = item.get("word")
            start = item.get("start")
            end = item.get("end")
            if not isinstance(word, str):
                continue
            try:
                stamps.append(
                    WordTimestamp(
                        word=word,
                        start=float(start),
                        end=float(end),
                    )
                )
            except (TypeError, ValueError):
                continue

    return SynthesizeResult(
        audio_bytes=audio_bytes,
        content_type="audio/mpeg",
        word_timestamps=stamps or None,
    )
