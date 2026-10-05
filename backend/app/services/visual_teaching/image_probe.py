"""Lightweight image dimension probe (JPEG/PNG/WebP) without Pillow."""

from __future__ import annotations

import struct
from typing import Optional, Tuple


def probe_image_dimensions(data: bytes, content_type: str) -> Tuple[int, int]:
    """Return (width, height) or (0, 0) if unknown."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime == "image/png":
        return _png(data)
    if mime in ("image/jpeg", "image/jpg"):
        return _jpeg(data)
    if mime == "image/webp":
        return _webp(data)
    return (0, 0)


def _png(data: bytes) -> Tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    try:
        w, h = struct.unpack(">II", data[16:24])
        return (int(w), int(h))
    except struct.error:
        return (0, 0)


def _jpeg(data: bytes) -> Tuple[int, int]:
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return (0, 0)
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):
            continue
        if i + 2 > n:
            break
        seglen = struct.unpack(">H", data[i : i + 2])[0]
        if seglen < 2:
            break
        # SOF0..SOF3, SOF5..SOF7, SOF9..SOF11, SOF13..SOF15
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            if i + 7 <= n:
                h, w = struct.unpack(">HH", data[i + 3 : i + 7])
                return (int(w), int(h))
            break
        i += seglen
    return (0, 0)


def _webp(data: bytes) -> Tuple[int, int]:
    if len(data) < 30 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return (0, 0)
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        # Lossy: width/height in frame header at offset 26
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return (int(w), int(h))
    if chunk == b"VP8L" and len(data) >= 25:
        bits = struct.unpack("<I", data[21:25])[0]
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return (int(w), int(h))
    if chunk == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return (int(w), int(h))
    return (0, 0)


def safe_probe(data: bytes, content_type: str) -> Tuple[int, int]:
    try:
        w, h = probe_image_dimensions(data, content_type)
        if w > 0 and h > 0:
            return (w, h)
    except Exception:  # noqa: BLE001
        pass
    return (0, 0)
