"""Authenticated TTS Voice Gateway — proxies Lemonfox without exposing API keys."""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.dependencies import get_current_user
from app.models.identification.users import User
from app.services.tts.lemonfox_provider import LemonfoxProvider, LemonfoxTTSError
from app.services.tts.stream_sessions import (
    create_speech_stream_session,
    take_speech_stream_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["TTS"])


class SpeechStreamSessionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class SpeechStreamSessionResponse(BaseModel):
    """One-time ticket for progressive HTMLAudioElement GET streaming."""

    session_id: str
    ticket: str
    stream_path: str
    text_chars: int


def _retryable_tts(exc: BaseException) -> bool:
    if isinstance(exc, StopAsyncIteration):
        return True
    if isinstance(exc, LemonfoxTTSError):
        return exc.status_code in (502, 504, None)
    return False


async def _open_mp3_stream(provider: LemonfoxProvider, text: str):
    """
    Open Lemonfox and return the first audio chunk.

    A transient upstream failure is retried once. The browser ticket is
    single-use, so a 502 here cannot be fetched again by the audio element.
    """
    last_exc: BaseException | None = None
    for attempt in (1, 2):
        upstream = provider.iter_mp3_stream(text)
        try:
            first_chunk = await upstream.__anext__()
            return upstream, first_chunk
        except (StopAsyncIteration, LemonfoxTTSError) as exc:
            last_exc = exc
            await upstream.aclose()
            logger.warning(
                "tts.timing be_stream_open_failed attempt=%s detail=%s",
                attempt,
                str(exc)[:200],
            )
            if attempt == 1 and _retryable_tts(exc):
                continue
            break
    if isinstance(last_exc, LemonfoxTTSError):
        raise _map_lemonfox_http(last_exc) from last_exc
    raise HTTPException(status_code=502, detail="TTS synthesis failed") from last_exc


def _map_lemonfox_http(exc: LemonfoxTTSError) -> HTTPException:
    status = exc.status_code or 502
    if status == 503:
        return HTTPException(status_code=503, detail="TTS provider is not configured")
    if status == 400:
        return HTTPException(status_code=400, detail=str(exc))
    if status == 504:
        return HTTPException(status_code=504, detail="TTS provider timed out")
    return HTTPException(status_code=502, detail="TTS synthesis failed")


@router.post("/speech/sessions", response_model=SpeechStreamSessionResponse)
async def create_speech_stream_session_route(
    body: SpeechStreamSessionRequest,
    current_user: User = Depends(get_current_user),
) -> SpeechStreamSessionResponse:
    """
    Authenticated prepare step for progressive playback.

    Returns a single-use ticket + path so <audio src> can GET the MP3 stream
    without sending Authorization headers or exposing Lemonfox credentials.
    """
    cleaned = body.text.strip()
    user_id = str(getattr(current_user, "id", "") or "")
    logger.info(
        "tts.timing be_session_created text_chars=%s mode=progressive",
        len(cleaned),
    )
    try:
        session_id, ticket = await create_speech_stream_session(
            text=cleaned,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stream_path = f"/tts/speech/sessions/{session_id}/audio"
    return SpeechStreamSessionResponse(
        session_id=session_id,
        ticket=ticket,
        stream_path=stream_path,
        text_chars=len(cleaned),
    )


@router.get("/speech/sessions/{session_id}/audio")
async def stream_speech_session_audio(
    session_id: str,
    request: Request,
    ticket: str = Query(..., min_length=8, max_length=128),
) -> StreamingResponse:
    """
    Progressive MP3 proxy: stream Lemonfox bytes to the client as they arrive.

    Auth is the single-use ticket from POST /tts/speech/sessions (not JWT), so
    HTMLAudioElement can load the URL directly.
    """
    sess = await take_speech_stream_session(session_id, ticket)
    if sess is None:
        raise HTTPException(status_code=404, detail="TTS stream session not found")

    text_chars = len(sess.text)
    t_be = time.perf_counter()
    logger.info(
        "tts.timing be_stream_open text_chars=%s mode=progressive",
        text_chars,
    )

    provider = LemonfoxProvider()
    if not provider.is_configured():
        raise HTTPException(status_code=503, detail="TTS provider is not configured")

    upstream, first_chunk = await _open_mp3_stream(provider, sess.text)

    async def byte_iter() -> AsyncIterator[bytes]:
        logger.info(
            "tts.timing be_stream_first_byte_out text_chars=%s since_open_ms=%s",
            text_chars,
            int((time.perf_counter() - t_be) * 1000),
        )
        yield first_chunk
        try:
            async for chunk in upstream:
                if await request.is_disconnected():
                    logger.info(
                        "tts.timing be_stream_client_disconnect text_chars=%s",
                        text_chars,
                    )
                    break
                yield chunk
        except LemonfoxTTSError as exc:
            logger.warning(
                "tts.timing be_stream_error text_chars=%s detail=%s",
                text_chars,
                str(exc)[:160],
            )
            return
        finally:
            # Ensure upstream stream/context closes if client aborts early.
            await upstream.aclose()
            logger.info(
                "tts.timing be_stream_closed text_chars=%s elapsed_ms=%s",
                text_chars,
                int((time.perf_counter() - t_be) * 1000),
            )

    return StreamingResponse(
        byte_iter(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-TTS-Text-Chars": str(text_chars),
            "X-TTS-Mode": "progressive",
        },
    )
