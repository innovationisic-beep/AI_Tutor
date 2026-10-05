from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.content.topic_question_bank import TopicQuestionBank
from app.repositories.base_repository import BaseRepository
from app.repositories.topic_note_repository import (
    topic_concept_global_filters,
    topic_concept_org_filters,
)
from app.services.embedding_service import get_embedding


class TopicQuestionRepository(BaseRepository[TopicQuestionBank]):
    """Repository for topic question bank (TopicQuestionBank) document operations."""

    def __init__(self) -> None:
        super().__init__(TopicQuestionBank)

    async def create(self, data: Dict[str, Any]) -> TopicQuestionBank:
        """Create a question; auto-fill embedding when absent (legacy rows may omit it)."""
        document = self.model(**data)
        if document.embedding is None:
            text = f"{document.concept or ''} {document.question_text or ''}".strip()
            text = text[:1000]
            if text:
                document.embedding = get_embedding(text)
        await document.insert()
        return document

    async def get_questions(
        self,
        topic_id: PydanticObjectId,
        concept: Optional[str] = None,
        *,
        organization_id: PydanticObjectId,
        difficulty_level: Optional[str] = None,
        approved: bool = True,
        limit: int = 100,
        skip: int = 0,
    ) -> List[TopicQuestionBank]:
        """
        Org-scoped questions first, then platform catalog (organization_id null).
        Teacher overrides: for any concept that has a teacher_override in org rows,
        admin/global questions for that concept are omitted.

        approved=True (default) enforces the approved flag in Mongo so unapproved
        questions are never fetched.  Pass approved=False only in admin contexts.
        difficulty_level, when set, filters by the DB field value directly ("basic",
        "medium", or "hard").
        """
        org_filters = topic_concept_org_filters(topic_id, concept, organization_id)
        admin_filters = topic_concept_global_filters(topic_id, concept)

        if approved:
            org_filters["approved"] = True
            admin_filters["approved"] = True

        if difficulty_level:
            org_filters["difficulty_level"] = difficulty_level
            admin_filters["difficulty_level"] = difficulty_level

        org_questions = await TopicQuestionBank.find(org_filters).to_list()
        admin_questions = await TopicQuestionBank.find(admin_filters).to_list()

        override_concepts = {
            q.concept
            for q in org_questions
            if getattr(q, "source_type", None) == "teacher_override"
        }

        filtered_admin_questions = [
            q for q in admin_questions if q.concept not in override_concepts
        ]

        merged = org_questions + filtered_admin_questions
        return merged[skip : skip + limit]


def get_topic_question_repository() -> TopicQuestionRepository:
    return TopicQuestionRepository()
