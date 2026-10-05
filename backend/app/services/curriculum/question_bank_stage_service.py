"""Authoring caps and helpers for quiz_stage-tagged Question Bank rows."""

from __future__ import annotations

from typing import Any, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.core.constants import (
    CLUSTER_QUESTIONS_PER_CLUSTER,
    CONCEPT_CHECK_SLOT_TYPES,
)
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.services.handlers.concept_check_question_types import infer_bank_question_type

QuizStage = Literal["concept_check", "cluster_quiz"]
QuestionType = Literal["mcq", "fill_in_blank", "descriptive"]

_CONCEPT_CHECK_MCQ_CAP = sum(1 for t in CONCEPT_CHECK_SLOT_TYPES if t == "mcq")
_CONCEPT_CHECK_FILL_CAP = sum(1 for t in CONCEPT_CHECK_SLOT_TYPES if t == "fill_in_blank")


def effective_question_type(row: TopicQuestionBank | Any) -> QuestionType:
    return infer_bank_question_type(row)  # type: ignore[return-value]


async def sibling_concept_ids(concept: CurriculumConcept) -> list[PydanticObjectId]:
    siblings = await CurriculumConcept.find(
        {
            "curriculum_cluster_id": concept.curriculum_cluster_id,
            "deleted_at": None,
        }
    ).to_list()
    return [s.id for s in siblings if s.id is not None]


async def count_concept_check_by_type(
    concept_id: PydanticObjectId,
    *,
    exclude_question_id: Optional[PydanticObjectId] = None,
) -> dict[str, int]:
    rows = await TopicQuestionBank.find(
        {
            "concept_id": concept_id,
            "quiz_stage": "concept_check",
        }
    ).to_list()
    counts = {"mcq": 0, "fill_in_blank": 0, "descriptive": 0}
    for q in rows:
        if exclude_question_id is not None and q.id == exclude_question_id:
            continue
        counts[effective_question_type(q)] = counts.get(effective_question_type(q), 0) + 1
    return counts


async def count_cluster_quiz_for_cluster(
    concept: CurriculumConcept,
    *,
    exclude_question_id: Optional[PydanticObjectId] = None,
) -> int:
    ids = await sibling_concept_ids(concept)
    if not ids:
        return 0
    rows = await TopicQuestionBank.find(
        {
            "concept_id": {"$in": ids},
            "quiz_stage": "cluster_quiz",
        }
    ).to_list()
    n = 0
    for q in rows:
        if exclude_question_id is not None and q.id == exclude_question_id:
            continue
        n += 1
    return n


async def assert_quiz_stage_caps(
    *,
    concept: CurriculumConcept,
    quiz_stage: Optional[str],
    question_type: Optional[str],
    exclude_question_id: Optional[PydanticObjectId] = None,
) -> None:
    """Raise HTTP 400 when creating/updating would exceed authoring caps."""
    if quiz_stage is None:
        return
    if quiz_stage == "concept_check":
        qtype = question_type or "descriptive"
        counts = await count_concept_check_by_type(
            concept.id, exclude_question_id=exclude_question_id
        )
        if qtype == "mcq" and counts.get("mcq", 0) >= _CONCEPT_CHECK_MCQ_CAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Concept check already has {_CONCEPT_CHECK_MCQ_CAP} MCQ questions. "
                    "Remove or edit an existing concept-check MCQ first."
                ),
            )
        if qtype == "fill_in_blank" and counts.get("fill_in_blank", 0) >= _CONCEPT_CHECK_FILL_CAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Concept check already has {_CONCEPT_CHECK_FILL_CAP} fill-in question. "
                    "Remove or edit the existing concept-check fill-in first."
                ),
            )
        if qtype == "descriptive":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Concept check questions must be MCQ or fill_in_blank.",
            )
        return

    if quiz_stage == "cluster_quiz":
        used = await count_cluster_quiz_for_cluster(
            concept, exclude_question_id=exclude_question_id
        )
        if used >= CLUSTER_QUESTIONS_PER_CLUSTER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This cluster already has {CLUSTER_QUESTIONS_PER_CLUSTER} cluster-quiz "
                    "questions. Remove one from a concept in this cluster first."
                ),
            )
        if question_type == "fill_in_blank":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cluster quiz questions must be descriptive or MCQ.",
            )
        return
