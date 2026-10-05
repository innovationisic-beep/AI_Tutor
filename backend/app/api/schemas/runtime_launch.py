"""Schemas for classroom session launch (Phase 3B.1)."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class LaunchClassSessionRequest(BaseModel):
    action: Optional[Literal["continue", "restart"]] = None


class ManifestSummaryOut(BaseModel):
    key_count: int
    cluster_count: int
    first_concept: Optional[str] = None
    launch_context: dict[str, Any]


class LaunchClassSessionResponse(BaseModel):
    type: Literal["session", "resume_prompt"]
    session_id: Optional[str] = None
    message: Optional[str] = None
    buttons: Optional[List[str]] = None
    manifest_summary: Optional[ManifestSummaryOut] = None
