"""
Real-HTTP progressive stream check (not ASGITransport).

Spins a temporary uvicorn on :8765 with auth overridden, then measures
Lemonfox TTFB vs complete through POST /tts/speech/sessions + GET audio.

  cd backend
  set PYTHONPATH=.
  python -m scripts.tts_http_progressive_check
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import uvicorn

from app.core.dependencies import get_current_user
from app.main import app


class _U:
    id = "http-bench-user"


async def _override_user():
    return _U()


def _run_server(port: int) -> None:
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


async def main() -> None:
    port = 8765
    app.dependency_overrides[get_current_user] = _override_user
    thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    thread.start()
    await asyncio.sleep(1.2)

    text = (
        "Stomata are tiny pores on the surface of leaves that allow plants to "
        "exchange gases with the air. Carbon dioxide enters through stomata "
        "during photosynthesis, while oxygen and water vapor can exit. Guard "
        "cells open and close each pore to balance gas exchange with water loss."
    )
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        for i in range(3):
            t0 = time.perf_counter()
            prep = await client.post(
                "/tts/speech/sessions",
                json={"text": text},
                headers={"Authorization": "Bearer unused"},
            )
            assert prep.status_code == 200, prep.text
            data = prep.json()
            url = f"{data['stream_path']}?ticket={data['ticket']}"
            t_prep = time.perf_counter()
            async with client.stream("GET", url) as resp:
                assert resp.status_code == 200
                t_headers = time.perf_counter()
                first = None
                total = 0
                async for chunk in resp.aiter_bytes():
                    if chunk and first is None:
                        first = time.perf_counter()
                    total += len(chunk or b"")
                t_done = time.perf_counter()
            print(
                f"run{i + 1} prepare_ms={int((t_prep - t0) * 1000)} "
                f"headers_ms={int((t_headers - t_prep) * 1000)} "
                f"ttfb_ms={int(((first or t_done) - t_prep) * 1000)} "
                f"complete_ms={int((t_done - t_prep) * 1000)} "
                f"total_from_start_ms={int((t_done - t0) * 1000)} "
                f"bytes={total} gap={int((t_done - (first or t_done)) * 1000)}"
            )

    app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
