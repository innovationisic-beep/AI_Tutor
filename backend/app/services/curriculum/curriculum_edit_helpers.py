"""Shared helpers for curriculum entity edit lifecycle (Phase 3B.1A)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status


def published_locked_detail(entity_label: str) -> dict[str, Any]:
    return {
        "code": "PUBLISHED_LOCKED",
        "message": (
            f"Published curriculum {entity_label} cannot be deleted. "
            "Edit to create a draft revision, then republish."
        ),
    }


def raise_published_locked(entity_label: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=published_locked_detail(entity_label),
    )


def demote_published_to_draft(entity: Any) -> bool:
    """Return True if entity was demoted from published to draft."""
    if getattr(entity, "status", None) == "published":
        entity.status = "draft"
        entity.updated_at = datetime.utcnow()
        return True
    return False
