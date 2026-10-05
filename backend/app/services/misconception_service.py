from __future__ import annotations

from typing import Any


MAX_PROBE_ATTEMPTS = 3


def handle_misconception(eval_result: dict[str, Any], mode: str, attempt: int) -> dict[str, Any]:
    """
    Minimal shared misconception handler used across quiz/teachback/micro flows.

    Returns:
        {
            "type": "correct" | "partial" | "wrong",
            "action": "confirm" | "probe" | "re_explain",
            "next_attempt": int,
        }
    """
    _ = mode  # reserved for future mode-specific tuning while keeping a single API
    score = float(eval_result.get("score", 0) or 0)
    correct = bool(eval_result.get("correct", False))
    missing_points = [
        str(m).strip() for m in (eval_result.get("missing_points") or []) if str(m).strip()
    ]

    if correct or (score >= 75 and not missing_points):
        m_type = "correct"
    elif score >= 45 or bool(missing_points):
        m_type = "partial"
    else:
        m_type = "wrong"

    if m_type == "correct":
        return {"type": "correct", "action": "confirm", "next_attempt": 0}

    if m_type == "partial":
        return {"type": "partial", "action": "probe", "next_attempt": int(attempt or 0) + 1}

    # wrong
    attempt_i = int(attempt or 0)
    if attempt_i < MAX_PROBE_ATTEMPTS:
        return {"type": "wrong", "action": "probe", "next_attempt": attempt_i + 1}
    return {"type": "wrong", "action": "re_explain", "next_attempt": 0}
