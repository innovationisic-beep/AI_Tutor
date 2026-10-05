"""In-process counters for teaching-runtime rejects. Not a dashboard product."""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_counters: Dict[str, int] = {}


def incr(name: str, n: int = 1) -> None:
    key = str(name or "").strip()
    if not key or n <= 0:
        return
    with _lock:
        _counters[key] = _counters.get(key, 0) + int(n)


def snapshot() -> Dict[str, int]:
    with _lock:
        return dict(_counters)


def reset() -> None:
    with _lock:
        _counters.clear()
