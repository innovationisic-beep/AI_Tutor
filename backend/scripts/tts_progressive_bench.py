"""
Measure full-buffer vs progressive Lemonfox TTFB/complete (backend-only).

Usage (backend venv, LEMONFOX_API_KEY set):

  cd backend
  python -m scripts.tts_progressive_bench

Does not change production defaults.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.services.tts.lemonfox_provider import LemonfoxProvider, close_shared_http_client

SAMPLES = {
    "c50": "Stomata are tiny pores on leaf surfaces today.",
    "c250": (
        "Stomata are tiny pores on the surface of leaves that allow plants to "
        "exchange gases with the air. Carbon dioxide enters through stomata "
        "during photosynthesis, while oxygen and water vapor exit."
    ),
    "c500": (
        "Stomata are tiny pores on the surface of leaves that allow plants to "
        "exchange gases with the air. Carbon dioxide enters through stomata "
        "during photosynthesis, while oxygen and water vapor can exit. Guard "
        "cells open and close each pore to balance gas exchange with water "
        "loss under changing conditions. This regulation helps plants survive "
        "heat, drought, and bright sunlight without drying out too quickly."
    ),
    "c1000": (
        "Stomata are tiny pores on the surface of leaves that allow plants to "
        "exchange gases with the air. Carbon dioxide enters through stomata "
        "during photosynthesis, while oxygen and water vapor can exit. Guard "
        "cells open and close each pore to balance gas exchange with water "
        "loss under changing conditions. This regulation helps plants survive "
        "heat, drought, and bright sunlight without drying out too quickly. "
        "When soil moisture is high and light is strong, stomata tend to open "
        "so photosynthesis can proceed. When the plant risks losing too much "
        "water, the guard cells lose turgor and the pore closes for safety. "
        "Understanding stomata is essential for biology students studying "
        "plant physiology and environmental adaptation."
    ),
}


async def time_full(provider: LemonfoxProvider, text: str) -> dict:
    t0 = time.perf_counter()
    result = await provider.synthesize(text, word_timestamps=False)
    return {
        "mode": "full",
        "chars": len(text),
        "ttfb_ms": None,
        "complete_ms": result.lemonfox_ms,
        "wall_ms": int((time.perf_counter() - t0) * 1000),
        "bytes": len(result.audio_bytes),
    }


async def time_stream(provider: LemonfoxProvider, text: str) -> dict:
    t0 = time.perf_counter()
    ttfb = None
    total = 0
    async for chunk in provider.iter_mp3_stream(text):
        if ttfb is None:
            ttfb = int((time.perf_counter() - t0) * 1000)
        total += len(chunk)
    complete = int((time.perf_counter() - t0) * 1000)
    return {
        "mode": "stream",
        "chars": len(text),
        "ttfb_ms": ttfb,
        "complete_ms": complete,
        "wall_ms": complete,
        "bytes": total,
    }


async def main() -> None:
    settings = Settings()
    if not (settings.LEMONFOX_API_KEY or "").strip():
        print("LEMONFOX_API_KEY not set")
        raise SystemExit(1)

    provider = LemonfoxProvider(settings)
    await provider.synthesize("Warmup.", word_timestamps=False)

    print("label mode chars ttfb_ms complete_ms bytes")
    for label, text in SAMPLES.items():
        full_rows = [await time_full(provider, text) for _ in range(3)]
        stream_rows = [await time_stream(provider, text) for _ in range(3)]
        full_med = int(median([r["complete_ms"] or 0 for r in full_rows]))
        stream_ttfb = int(median([r["ttfb_ms"] or 0 for r in stream_rows]))
        stream_done = int(median([r["complete_ms"] for r in stream_rows]))
        print(
            f"{label} full    {len(text):4d}     -     {full_med:5d} "
            f"{full_rows[1]['bytes']}"
        )
        print(
            f"{label} stream  {len(text):4d} {stream_ttfb:5d} {stream_done:5d} "
            f"{stream_rows[1]['bytes']}"
        )
        print(
            f"  delta complete(full)-stream_ttfb~{full_med - stream_ttfb} ms "
            f"(theoretical TTFA win if browser plays near TTFB)"
        )

    await close_shared_http_client()


if __name__ == "__main__":
    asyncio.run(main())
