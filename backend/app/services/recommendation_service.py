from datetime import datetime
from typing import List, TypedDict

from beanie.odm.fields import PydanticObjectId

from app.models.curriculum.topics import Topic
from app.repositories.knowledge_gap_repository import KnowledgeGapRepository
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.repositories.topic_progression_repository import (
    TopicProgressionRepository,
)
from app.repositories.topic_repository import TopicRepository


class RecommendedTopicPayload(TypedDict):
    """Structured recommendation returned to API clients (and logged separately)."""

    id: str
    name: str
    reason: str
    score: float


class RecommendationService:
    """Recommends next topics based on knowledge gaps and mastery progression."""

    def __init__(
        self,
        topic_repository: TopicRepository,
        mastery_repository: MasteryRepository,
        recommendation_repository: RecommendationRepository,
        knowledge_gap_repository: KnowledgeGapRepository,
        topic_progression_repository: TopicProgressionRepository,
    ) -> None:
        self.topic_repository = topic_repository
        self.mastery_repository = mastery_repository
        self.recommendation_repository = recommendation_repository
        self.knowledge_gap_repository = knowledge_gap_repository
        self.topic_progression_repository = topic_progression_repository

    async def recommend_next_topics(
        self,
        student_id: PydanticObjectId,
        topic_id: PydanticObjectId,
    ) -> List[RecommendedTopicPayload]:
        """
        Return up to 3 structured recommendations. Prioritizes knowledge gap
        remediation, then mastery-based progression.
        """
        current_topic = await self.topic_repository.get_by_id(topic_id)
        if current_topic is None:
            return []
        organization_id = current_topic.organization_id

        # Step 1 — Check knowledge gaps (highest severity first)
        gaps = await self.knowledge_gap_repository.get_unresolved_for_student(
            student_id, organization_id, limit=10
        )
        gaps = sorted(gaps, key=lambda g: g.severity_score, reverse=True)
        if gaps:
            root_cause_id = gaps[0].root_cause_topic_id
            root_topic = await self.topic_repository.get_by_id(root_cause_id)
            if root_topic is not None:
                await self.recommendation_repository.create_log(
                    {
                        "organization_id": organization_id,
                        "student_id": student_id,
                        "recommended_topic_id": root_cause_id,
                        "recommendation_reason": "Knowledge gap remediation",
                        "recommendation_score": 100.0,
                        "accepted": False,
                        "timestamp": datetime.utcnow(),
                    }
                )
                item: RecommendedTopicPayload = {
                    "id": str(root_topic.id),
                    "name": str(getattr(root_topic, "topic_name", "") or ""),
                    "reason": "Fix your basics",
                    "score": 100.0,
                }
                return [item]
            # else fall through to progression logic

        # Step 2 — Get mastery record
        mastery = await self.mastery_repository.get_topic_mastery(
            student_id, topic_id, organization_id=organization_id
        )
        if mastery is None:
            return []

        # Step 3 — Load next topic candidates
        candidates = await self.topic_progression_repository.get_next_candidates(
            topic_id, organization_id, limit=50
        )
        if not candidates:
            return []

        # Step 4 — Compute recommendation score with difficulty adjustment, keep score >= -20
        difficulty_adjustment = {"easy": 10.0, "medium": 0.0, "hard": -10.0}
        scored: List[tuple[PydanticObjectId, float]] = []
        for c in candidates:
            base_score = mastery.mastery_score - c.minimum_mastery_to_recommend
            candidate_topic = await self.topic_repository.get_by_id(
                c.recommended_next_topic_id
            )
            dl = (
                str(getattr(candidate_topic, "difficulty_level", "") or "").lower().strip()
                if candidate_topic is not None
                else ""
            )
            adj = difficulty_adjustment.get(dl, 0.0)
            score = base_score + adj
            if score >= -20:
                scored.append((c.recommended_next_topic_id, score))

        # Step 5 — Rank and take top 3
        scored.sort(key=lambda x: x[1], reverse=True)
        top3 = scored[:3]
        if not top3:
            return []

        # Step 6 — Load Topic documents
        topic_ids = [tid for tid, _ in top3]
        topics: List[Topic] = []
        for tid in topic_ids:
            t = await self.topic_repository.get_by_id(tid)
            if t is not None:
                topics.append(t)

        # Step 7 — Store recommendation logs
        score_by_id = {tid: s for tid, s in top3}
        for t in topics:
            raw_score = score_by_id.get(t.id)
            if raw_score is not None:
                log_score = max(0.0, min(100.0, raw_score))
                await self.recommendation_repository.create_log(
                    {
                        "organization_id": organization_id,
                        "student_id": student_id,
                        "recommended_topic_id": t.id,
                        "recommendation_reason": "Mastery progression recommendation",
                        "recommendation_score": log_score,
                        "accepted": False,
                        "timestamp": datetime.utcnow(),
                    }
                )

        out: List[RecommendedTopicPayload] = []
        for t in topics:
            computed = score_by_id.get(t.id)
            if computed is not None:
                out.append(
                    {
                        "id": str(t.id),
                        "name": str(getattr(t, "topic_name", "") or ""),
                        "reason": "Recommended based on your progress",
                        "score": float(computed),
                    }
                )
        return out
