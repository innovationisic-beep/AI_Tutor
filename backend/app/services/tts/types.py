"""Shared TTS result types (provider-independent)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class WordTimestamp:
    """Word-level timing from a TTS provider (seconds)."""

    word: str
    start: float
    end: float


@dataclass
class SynthesizeResult:
    """Normalized synthesis output from any TTS provider."""

    audio_bytes: bytes
    content_type: str = "audio/mpeg"
    word_timestamps: Optional[List[WordTimestamp]] = field(default=None)
    # Upstream Lemonfox round-trip ms (instrumentation).
    lemonfox_ms: Optional[int] = None
    text_chars: Optional[int] = None
