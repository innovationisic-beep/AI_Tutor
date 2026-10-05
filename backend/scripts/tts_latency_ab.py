"""
Optional live A/B timing: raw MP3 vs word_timestamps for the same utterance.

Usage (backend venv, with LEMONFOX_API_KEY set):

  cd backend
  python -m scripts.tts_latency_ab

Does not change production behavior — measurement only.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

# Allow `python -m scripts.tts_latency_ab` from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.services.tts.lemonfox_provider import LemonfoxProvider, close_shared_http_client


SAMPLE_SHORT = "Stomata are tiny pores."
SAMPLE_LONG = (
    "Stomata are tiny pores on the surface of leaves that allow plants to "
    "exchange gases with the air. Carbon dioxide enters through stomata during "
    "photosynthesis, while oxygen and water vapor can exit. Guard cells open "
    "and close each pore to balance gas exchange with water loss."
)


async def _time_once(provider: LemonfoxProvider, text: str, *, timestamps: bool) -> dict:
    t0 = time.perf_counter()
    result = await provider.synthesize(text, word_timestamps=timestamps)
    total_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "word_timestamps": timestamps,
        "text_chars": len(text),
        "audio_bytes": len(result.audio_bytes),
        "lemonfox_ms": result.lemonfox_ms,
        "wall_ms": total_ms,
        "stamp_count": len(result.word_timestamps or []),
    }


async def main() -> None:
    settings = Settings()
    if not (settings.LEMONFOX_API_KEY or "").strip():
        print("LEMONFOX_API_KEY not set — aborting live A/B.")
        raise SystemExit(1)

    provider = LemonfoxProvider(settings)
    rows = []
    for label, text in (("short", SAMPLE_SHORT), ("long", SAMPLE_LONG)):
        for timestamps in (True, False):
            # Warm connection once before first timed call of each mode pair.
            row = await _time_once(provider, text, timestamps=timestamps)
            row["label"] = label
            rows.append(row)
            print(
                f"{label:5} timestamps={str(timestamps):5} "
                f"chars={row['text_chars']:4} wall_ms={row['wall_ms']:5} "
                f"lemonfox_ms={row['lemonfox_ms']} bytes={row['audio_bytes']}"
            )

    print("\nDelta (timestamps_true - raw) wall_ms by label:")
    for label in ("short", "long"):
        ts = next(r for r in rows if r["label"] == label and r["word_timestamps"])
        raw = next(r for r in rows if r["label"] == label and not r["word_timestamps"])
        print(f"  {label}: {ts['wall_ms'] - raw['wall_ms']} ms")

    await close_shared_http_client()


if __name__ == "__main__":
    asyncio.run(main())
