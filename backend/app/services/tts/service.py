"""Small provider-independent TTS gateway (Lemonfox now; Polly later)."""

from __future__ import annotations

from typing import Optional

from app.core.config import Settings
from app.services.tts.lemonfox_provider import LemonfoxProvider, LemonfoxTTSError
from app.services.tts.types import SynthesizeResult


class TTSService:
    """Voice gateway. Phase 1 routes all English synthesis to Lemonfox."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        lemonfox: Optional[LemonfoxProvider] = None,
    ) -> None:
        self._settings = settings or Settings()
        self._lemonfox = lemonfox or LemonfoxProvider(self._settings)

    async def synthesize(
        self,
        text: str,
        *,
        word_timestamps: bool = False,
    ) -> SynthesizeResult:
        return await self._lemonfox.synthesize(
            text,
            word_timestamps=word_timestamps,
            response_format="mp3",
            speed=self._settings.LEMONFOX_SPEED,
        )


async def synthesize_speech(
    text: str,
    *,
    word_timestamps: bool = False,
    settings: Optional[Settings] = None,
) -> SynthesizeResult:
    """Module-level helper for benches/tests (full-buffer synth; not the hot path)."""
    return await TTSService(settings=settings).synthesize(
        text,
        word_timestamps=word_timestamps,
    )


# Re-export for route error mapping
__all__ = ["TTSService", "synthesize_speech", "LemonfoxTTSError"]
