"""Authoring-time usage counts for curriculum concepts (Phase 2)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.core.constants import CLUSTER_QUESTIONS_PER_CLUSTER
from app.models.content.topic_question_bank import TopicQuestionBank
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.question_bank_stage_service import (
    count_cluster_quiz_for_cluster,
    count_concept_check_by_type,
    effective_question_type,
    sibling_concept_ids,
)
from app.services.curriculum.topic_context_service import TopicContext


class ConceptUsageService:
    def __init__(
        self,
        concept_repo: Optional[CurriculumConceptRepository] = None,
    ) -> None:
        self._concepts = concept_repo or CurriculumConceptRepository()

    async def get_usage(self, ctx: TopicContext, concept_id: PydanticObjectId) -> Dict[str, Any]:
        concept = await self._concepts.get_by_id(concept_id)
        if concept is None or concept.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")
        if concept.topic_id != ctx.topic_id or concept.topic_source != ctx.topic_source:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")

        question_filters: Dict[str, Any] = {"concept_id": concept_id}

        questions = await TopicQuestionBank.find(question_filters).to_list()

        concept_check_counts = await count_concept_check_by_type(concept_id)
        cluster_quiz_used = await count_cluster_quiz_for_cluster(concept)
        sibling_ids = await sibling_concept_ids(concept)

        return {
            "concept_id": str(concept_id),
            "topic_id": str(ctx.topic_id),
            "topic_source": ctx.topic_source,
            "canonical_runtime_key": concept.canonical_runtime_key,
            "display_name": concept.display_name,
            # Structured notes retired from concept authoring — teaching uses VTSE templates.
            "note_count": 0,
            "question_count": len(questions),
            "notes": [],
            "questions": [
                {
                    "id": str(q.id),
                    "concept_source": q.concept_source,
                    "approved": bool(q.approved),
                    "question_text": q.question_text,
                    "options": list(q.options or []),
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation or "",
                    "difficulty_level": q.difficulty_level,
                    "question_type": effective_question_type(q),
                    "quiz_stage": getattr(q, "quiz_stage", None),
                }
                for q in questions
            ],
            "concept_check": {
                "mcq_count": concept_check_counts.get("mcq", 0),
                "mcq_cap": 2,
                "fill_in_blank_count": concept_check_counts.get("fill_in_blank", 0),
                "fill_in_blank_cap": 1,
                "slots_remaining": max(0, 2 - concept_check_counts.get("mcq", 0))
                + max(0, 1 - concept_check_counts.get("fill_in_blank", 0)),
            },
            "cluster_quiz": {
                "used": cluster_quiz_used,
                "cap": CLUSTER_QUESTIONS_PER_CLUSTER,
                "remaining": max(0, CLUSTER_QUESTIONS_PER_CLUSTER - cluster_quiz_used),
                "cluster_concept_ids": [str(i) for i in sibling_ids],
            },
        }
