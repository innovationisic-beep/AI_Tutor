from datetime import datetime
from typing import List, Optional

from beanie.odm.fields import PydanticObjectId

from app.enums.learning_enums import SessionEventType
from app.models.learning.knowledge_gaps import KnowledgeGap
from app.models.learning.mastery_records import (
    MasteryRecord,
    mastery_record_filter,
    normalize_concept,
)
from app.models.learning.session_events import SessionEvent
from app.repositories.event_repository import EventRepository
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.session_repository import SessionRepository


class MasteryService:
    """Computes mastery from session events and updates MasteryRecord. Uses Session, Event, and Mastery repositories only."""

    def __init__(
        self,
        session_repository: SessionRepository,
        event_repository: EventRepository,
        mastery_repository: MasteryRepository,
    ) -> None:
        self.session_repository = session_repository
        self.event_repository = event_repository
        self.mastery_repository = mastery_repository

    async def calculate_mastery_for_session(
        self,
        session_id: PydanticObjectId,
    ) -> MasteryRecord:
        """
        Load session and its events, compute learning signals and mastery score,
        then create or update the MasteryRecord for the session's student and topic.
        Raises ValueError if session does not exist.
        """
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")

        student_id = session.student_id
        topic_id = session.topic_id
        organization_id = session.organization_id
        concept = normalize_concept(getattr(session, "current_concept", None))

        events: List[SessionEvent] = await self.event_repository.get_session_events(
            session_id, limit=10_000
        )

        accuracy_score = self._accuracy_score(events)
        engagement_score = self._engagement_score(events)
        average_response_time = self._average_response_time_ms(events)
        response_speed_score = self._response_speed_score(average_response_time)

        mastery_score = round(
            min(
                100.0,
                max(
                    0.0,
                    0.6 * accuracy_score
                    + 0.25 * engagement_score
                    + 0.15 * response_speed_score,
                ),
            ),
            1,
        )

        confusion_score = self._detect_confusion(events)
        revision_needed = confusion_score > 0
        if revision_needed:
            mastery_score = round(
                max(0.0, mastery_score - (confusion_score * 0.1)), 1
            )

        session_mastery_signal = mastery_score

        record = await self.mastery_repository.get_one(
            mastery_record_filter(
                organization_id,
                student_id,
                topic_id,
                concept,
            )
        )
        now = datetime.utcnow()

        if record is not None:
            blended = 0.6 * float(record.mastery_score) + 0.4 * float(
                session_mastery_signal
            )
            mastery_score = round(min(100.0, max(0.0, blended)), 1)
            record.mastery_score = mastery_score
            record.engagement_score = engagement_score
            record.attempt_count = int(record.attempt_count) + 1
            record.last_session_id = session_id
            record.last_updated = now
            record.revision_needed = revision_needed
            # Spaced-retrieval: stamp every session-end review.
            record.last_reviewed_at = now
            await record.save()
            result = record
        else:
            result = await self.mastery_repository.create(
                {
                    "organization_id": organization_id,
                    "student_id": student_id,
                    "topic_id": topic_id,
                    "concept": concept,
                    "mastery_score": session_mastery_signal,
                    "confidence_score": session_mastery_signal,
                    "teachback_average": 0.0,
                    "engagement_score": engagement_score,
                    "revision_needed": revision_needed,
                    "attempt_count": 1,
                    "last_session_id": session_id,
                    "last_updated": now,
                    # Spaced-retrieval: first-ever review timestamp.
                    "last_reviewed_at": now,
                }
            )

        # Knowledge gap detection: only after multiple attempts (attempt_count >= 2)
        attempt_count_after = int(result.attempt_count)
        if mastery_score < 40 and attempt_count_after >= 2:
            existing_gap = await KnowledgeGap.find_one(
                {
                    "organization_id": organization_id,
                    "student_id": student_id,
                    "topic_id": topic_id,
                    "resolved": False,
                }
            )
            if existing_gap is None:
                severity = min(100.0, 100.0 - mastery_score)
                gap = KnowledgeGap(
                    organization_id=organization_id,
                    student_id=student_id,
                    topic_id=topic_id,
                    root_cause_topic_id=topic_id,
                    severity_score=severity,
                    detected_reason="Low mastery after session",
                    resolved=False,
                )
                await gap.insert()

        return result

    async def update_mastery(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
        concept: str | None,
        is_correct: bool,
        organization_id: PydanticObjectId,
    ) -> MasteryRecord:
        """
        Incrementally adjust mastery_score after a quiz/teachback evaluation.
        Creates a record if none exists for this student–topic (and optional concept) pair.
        """
        concept = normalize_concept(concept)
        record = await self.mastery_repository.get_one(
            mastery_record_filter(
                organization_id,
                student_id,
                topic_id,
                concept,
            )
        )
        now = datetime.utcnow()
        delta = 8.0 if is_correct else -6.0

        if record is None:
            record = MasteryRecord(
                organization_id=organization_id,
                student_id=student_id,
                topic_id=topic_id,
                concept=concept,
                mastery_score=50.0,
                confidence_score=0.0,
                teachback_average=0.0,
                engagement_score=50.0,
                revision_needed=False,
                attempt_count=0,
                last_session_id=None,
                last_updated=now,
            )

        new_score = max(0.0, min(100.0, float(record.mastery_score) + delta))
        mastery_record_attempt_count = int(record.attempt_count) + 1
        confidence_score = min(100.0, float(mastery_record_attempt_count) * 10.0)

        record.mastery_score = new_score
        record.attempt_count = mastery_record_attempt_count
        record.confidence_score = confidence_score
        record.last_updated = now
        record.revision_needed = new_score < 40.0
        # Spaced-retrieval: stamp every review event (explain / quiz / teachback).
        record.last_reviewed_at = now

        await record.save()
        return record

    def _accuracy_score(self, events: List[SessionEvent]) -> float:
        """Fraction of answer events that are correct, as 0–100."""
        answer_events = [e for e in events if e.event_type == SessionEventType.ANSWER]
        total = len(answer_events)
        if total == 0:
            return 0.0
        correct = sum(1 for e in answer_events if e.is_correct is True)
        return round(100.0 * correct / total, 1)

    def _engagement_score(self, events: List[SessionEvent]) -> float:
        """Weighted engagement points by event type, normalized to 0–100."""
        weights = {
            SessionEventType.QUESTION: 3,
            SessionEventType.ANSWER: 2,
            SessionEventType.REWIND: 1,
            SessionEventType.PAUSE: 1,
            SessionEventType.HINT_REQUEST: 2,
            SessionEventType.TEACHBACK: 4,
            SessionEventType.SUBTITLE_EXPLANATION_REQUEST: 2,
        }
        engagement_points = 0
        for e in events:
            engagement_points += weights.get(e.event_type, 0)
        engagement_score = min(100.0, engagement_points * 2.0)
        return round(engagement_score, 1)

    def _average_response_time_ms(
        self, events: List[SessionEvent]
    ) -> Optional[float]:
        """Mean of response_time_ms for events that have it."""
        times = [e.response_time_ms for e in events if e.response_time_ms is not None]
        if not times:
            return None
        return sum(times) / len(times)

    def _response_speed_score(
        self, average_response_time_ms: Optional[float]
    ) -> float:
        """Faster responses score higher; 0–100. Uses 300s as upper bound (0 score)."""
        if average_response_time_ms is None:
            return 50.0
        # 0 ms -> 100, 300_000 ms -> 0
        raw = 100.0 - (average_response_time_ms / 3000.0)
        return round(max(0.0, min(100.0, raw)), 1)

    def _detect_confusion(self, events: List[SessionEvent]) -> float:
        """Confusion score 0–100 from pause, rewind, hint, subtitle-explanation events."""
        rewind_count = sum(
            1 for e in events if e.event_type == SessionEventType.REWIND
        )
        pause_count = sum(
            1 for e in events if e.event_type == SessionEventType.PAUSE
        )
        hint_count = sum(
            1 for e in events if e.event_type == SessionEventType.HINT_REQUEST
        )
        subtitle_count = sum(
            1
            for e in events
            if e.event_type == SessionEventType.SUBTITLE_EXPLANATION_REQUEST
        )
        base_confusion = (
            rewind_count * 10
            + pause_count * 5
            + hint_count * 20
            + subtitle_count * 20
        )
        return round(min(100.0, max(0.0, base_confusion)), 1)
