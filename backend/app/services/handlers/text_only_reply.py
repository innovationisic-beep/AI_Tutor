"""Plain-text tutor replies — no legacy JSON/visual payloads."""

from __future__ import annotations

import json


PLAIN_TEXT_REPLY_SUFFIX = (
    "\n\nReply in plain natural language only. "
    "Do NOT return JSON, markdown code blocks, bullet lists, or structured visual data."
)


def coerce_plain_text_reply(text: str) -> str:
    """Extract teaching prose from LLM output; strip accidental JSON/visual leaks."""
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.startswith("{") or '"explanation"' in raw[:300]:
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end > start:
                data = json.loads(raw[start : end + 1])
                if isinstance(data, dict):
                    expl = str(data.get("explanation") or "").strip()
                    if expl:
                        return expl
        except Exception:
            pass
    return raw
