from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.progression.student_plan_progress import StudentPlanProgress


class ReleasePolicy(ABC):
    """When a session completes, decides availability of the next session."""

    @abstractmethod
    def release_at(self, *, completed_at: datetime) -> datetime:
        """When the next session becomes available."""

    @abstractmethod
    def should_auto_start(self) -> bool:
        """Whether the unlock engine should immediately start the next session."""

    def is_available_now(self, *, available_at: datetime, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        return now >= available_at


class ImmediateReleasePolicy(ReleasePolicy):
    """Testing / production default: next session unlocks and starts immediately."""

    def release_at(self, *, completed_at: datetime) -> datetime:
        return completed_at

    def should_auto_start(self) -> bool:
        return True


class ScheduledReleasePolicy(ReleasePolicy):
    """Future: teacher-controlled or next-day release (engine unchanged)."""

    def __init__(self, *, delay_seconds: int = 86400) -> None:
        self._delay_seconds = delay_seconds

    def release_at(self, *, completed_at: datetime) -> datetime:
        from datetime import timedelta

        return completed_at + timedelta(seconds=self._delay_seconds)

    def should_auto_start(self) -> bool:
        return False
