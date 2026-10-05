"""TTS Voice Gateway — provider-independent synthesis for the tutor."""

from app.services.tts.service import TTSService, synthesize_speech
from app.services.tts.types import SynthesizeResult, WordTimestamp

__all__ = [
    "TTSService",
    "SynthesizeResult",
    "WordTimestamp",
    "synthesize_speech",
]
