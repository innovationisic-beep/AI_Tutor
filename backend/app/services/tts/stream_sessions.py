"""Short-lived one-time TTS stream tickets for progressive HTMLAudioElement playback.

Browser cannot POST JSON + Authorization on <audio src>, so:
  1) Authenticated POST creates an opaque single-use ticket holding the text.
  2) GET with ticket streams Lemonfox audio (credentials never leave the backend).

``TTS_TICKET_STORE=memory`` (default) keeps tickets in this process.
``TTS_TICKET_STORE=redis`` shares them across workers via ``REDIS_URL``.
If Redis is selected but the client library is missing, tickets stay in memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Single-use tickets; short TTL limits URL leakage risk in logs/history.
SESSION_TTL_SECONDS = 60.0


@dataclass
class SpeechStreamSession:
    text: str
    ticket: str
    user_id: str
    created_at: float


_sessions: Dict[str, SpeechStreamSession] = {}
_lock = asyncio.Lock()
_redis_client: object | None = None
_redis_unavailable = False


def ticket_store_mode() -> str:
    mode = os.getenv("TTS_TICKET_STORE", "memory").strip().lower()
    return "redis" if mode == "redis" else "memory"


def _purge_expired_unlocked(now: float) -> None:
    expired = [
        sid
        for sid, sess in _sessions.items()
        if now - sess.created_at > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _sessions.pop(sid, None)


async def _redis():
    """Shared Redis client, or None when Redis is not selected or not installed."""
    global _redis_client, _redis_unavailable
    if ticket_store_mode() != "redis" or _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning(
            "TTS_TICKET_STORE=redis but redis package is not installed; using memory"
        )
        _redis_unavailable = True
        return None
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    _redis_client = aioredis.from_url(url, decode_responses=True)
    return _redis_client


def _redis_key(session_id: str) -> str:
    return f"tts:ticket:{session_id}"


_TAKE_LUA = """
local ticket = redis.call('HGET', KEYS[1], 'ticket')
if not ticket then
  return nil
end
if ticket ~= ARGV[1] then
  return nil
end
local text = redis.call('HGET', KEYS[1], 'text')
local user_id = redis.call('HGET', KEYS[1], 'user_id')
redis.call('DEL', KEYS[1])
return {text, user_id}
"""


async def create_speech_stream_session(*, text: str, user_id: str) -> tuple[str, str]:
    """Return (session_id, ticket)."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty text")
    session_id = secrets.token_urlsafe(16)
    ticket = secrets.token_urlsafe(24)
    client = await _redis()
    if client is not None:
        await client.hset(
            _redis_key(session_id),
            mapping={"text": cleaned, "ticket": ticket, "user_id": user_id},
        )
        await client.expire(_redis_key(session_id), max(1, int(SESSION_TTL_SECONDS)))
        return session_id, ticket
    now = time.monotonic()
    async with _lock:
        _purge_expired_unlocked(now)
        _sessions[session_id] = SpeechStreamSession(
            text=cleaned,
            ticket=ticket,
            user_id=user_id,
            created_at=now,
        )
    return session_id, ticket


async def take_speech_stream_session(
    session_id: str,
    ticket: str,
) -> Optional[SpeechStreamSession]:
    """Atomically consume a valid session (single-use)."""
    client = await _redis()
    if client is not None:
        raw = await client.eval(_TAKE_LUA, 1, _redis_key(session_id), ticket)
        if not raw or not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return None
        return SpeechStreamSession(
            text=str(raw[0] or ""),
            ticket=ticket,
            user_id=str(raw[1] or ""),
            created_at=time.monotonic(),
        )
    now = time.monotonic()
    async with _lock:
        _purge_expired_unlocked(now)
        sess = _sessions.get(session_id)
        if sess is None:
            return None
        if sess.ticket != ticket:
            return None
        if now - sess.created_at > SESSION_TTL_SECONDS:
            _sessions.pop(session_id, None)
            return None
        _sessions.pop(session_id, None)
        return sess


async def clear_all_speech_stream_sessions() -> None:
    """Test helper. Clears the in-process store (not a remote Redis)."""
    async with _lock:
        _sessions.clear()
