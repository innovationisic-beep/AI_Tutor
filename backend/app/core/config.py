import math
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _lemonfox_speed_from_env() -> float:
    """Patient teacher default 0.92; clamp to Lemonfox official range 0.5–4.0."""
    raw = os.getenv("LEMONFOX_SPEED", "0.92")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.92
    if not math.isfinite(value) or value <= 0:
        value = 0.92
    return max(0.5, min(4.0, value))


class Settings:
    """Application settings loaded from environment variables."""

    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017/ai_tutor")
    # Long learning sessions need a longer-lived JWT (default 8 hours).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480")
    )
    # Legacy ``deepseek-chat`` was retired; V4 Pro works with thinking disabled.
    DEEPSEEK_API_URL: str = os.getenv(
        "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
    )
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    # Lemonfox TTS (server-side only; never expose to the browser).
    LEMONFOX_API_KEY: str = os.getenv("LEMONFOX_API_KEY", "")
    LEMONFOX_API_URL: str = os.getenv(
        "LEMONFOX_API_URL", "https://api.lemonfox.ai/v1/audio/speech"
    )
    LEMONFOX_VOICE: str = os.getenv("LEMONFOX_VOICE", "sarah")
    LEMONFOX_LANGUAGE: str = os.getenv("LEMONFOX_LANGUAGE", "en-us")
    # Global teacher-tone pacing (voice-dependent sweet spot; retune if voice changes).
    LEMONFOX_SPEED: float = _lemonfox_speed_from_env()
    LEMONFOX_TIMEOUT_SECONDS: float = float(
        os.getenv("LEMONFOX_TIMEOUT_SECONDS", "60")
    )
    # Story Hook visual binaries. ``local`` is a development provider only —
    # multi-instance deployments need a shared object store behind the same
    # StoryHookStorage protocol.
    STORY_HOOK_STORAGE_PROVIDER: str = os.getenv("STORY_HOOK_STORAGE_PROVIDER", "local")
    STORY_HOOK_LOCAL_ROOT: str = os.getenv(
        "STORY_HOOK_LOCAL_ROOT",
        str(Path(__file__).resolve().parents[2] / "storage" / "story_hook"),
    )
    # Visual Teaching image binaries (separate root from Story Hook).
    VISUAL_TEACHING_STORAGE_PROVIDER: str = os.getenv(
        "VISUAL_TEACHING_STORAGE_PROVIDER", "local"
    )
    VISUAL_TEACHING_LOCAL_ROOT: str = os.getenv(
        "VISUAL_TEACHING_LOCAL_ROOT",
        str(Path(__file__).resolve().parents[2] / "storage" / "visual_teaching"),
    )
    VTSE_VISUALS_STORAGE_PROVIDER: str = os.getenv(
        "VTSE_VISUALS_STORAGE_PROVIDER", "local"
    )
    VTSE_VISUALS_LOCAL_ROOT: str = os.getenv(
        "VTSE_VISUALS_LOCAL_ROOT",
        str(Path(__file__).resolve().parents[2] / "storage" / "vtse_visuals"),
    )
    # TTS stream tickets. ``memory`` is process-local; ``redis`` shares them
    # across workers (REDIS_URL, default redis://localhost:6379/0).
    TTS_TICKET_STORE: str = os.getenv("TTS_TICKET_STORE", "memory")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")


settings = Settings()
# Non-thinking mode keeps short pedagogy replies fast on V4 models.
DEEPSEEK_THINKING_DISABLED = {"type": "disabled"}
