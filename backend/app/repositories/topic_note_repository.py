from typing import Any, Dict, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.content.topic_notes import TopicNote
from app.services.embedding_service import get_embedding
from app.models.curriculum.topics import Topic
from app.repositories.base_repository import BaseRepository


def normalize_concept_filter(concept: Optional[str]) -> Optional[str]:
    """Trim and lowercase for query filters (matches model storage)."""
    if concept is None:
        return None
    if not isinstance(concept, str):
        raise TypeError("concept must be a string or null")
    s = concept.strip().lower()
    return s if s else None


def topic_concept_org_filters(
    topic_id: PydanticObjectId,
    concept: Optional[str],
    organization_id: PydanticObjectId,
) -> Dict[str, Any]:
    """topic + concept (+ optional concept OR null) scoped to one organization."""
    base = topic_concept_filters(topic_id, concept)
    base["organization_id"] = organization_id
    return base


def topic_concept_global_filters(
    topic_id: PydanticObjectId,
    concept: Optional[str],
) -> Dict[str, Any]:
    """Platform catalog: topic + concept, organization_id null."""
    base = topic_concept_filters(topic_id, concept)
    base["organization_id"] = None
    return base


def topic_concept_filters(
    topic_id: PydanticObjectId, concept: Optional[str]
) -> Dict[str, Any]:
    """
    Build Mongo filters for topic_id and optional concept.

    If concept is omitted (None): all notes/questions for the topic.
    If concept is set: rows for that normalized concept **or** general rows
    (concept null / missing — backward compatibility for legacy documents).
    """
    base: Dict[str, Any] = {"topic_id": topic_id}
    nc = normalize_concept_filter(concept)
    if nc is None:
        return base
    base["$or"] = [{"concept": nc}, {"concept": None}]
    return base


def validate_concept_for_topic(topic: Topic, concept: Optional[str]) -> Optional[str]:
    """Delegates to model; use when creating/updating with a topic context."""
    return TopicNote.validate_concept_for_topic(topic, concept)


class TopicNoteRepository(BaseRepository[TopicNote]):
    """Repository for TopicNote document operations."""

    def __init__(self) -> None:
        super().__init__(TopicNote)

    async def create(self, data: Dict[str, Any]) -> TopicNote:
        """Create a note; auto-fill embedding when absent (legacy rows may omit it)."""
        document = self.model(**data)
        if document.embedding is None:
            text = f"{document.concept or ''} {document.content_markdown or ''}".strip()
            text = text[:1000]
            if text:
                document.embedding = get_embedding(text)
        await document.insert()
        return document

    async def get_notes(
        self,
        topic_id: PydanticObjectId,
        concept: Optional[str] = None,
        *,
        organization_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
    ) -> List[TopicNote]:
        """
        Org-scoped notes first, then platform catalog (organization_id null).
        Teacher overrides: for any concept that has a teacher_override in org notes,
        admin/global notes for that concept are omitted.
        """
        org_filters = topic_concept_org_filters(topic_id, concept, organization_id)
        admin_filters = topic_concept_global_filters(topic_id, concept)

        org_notes = await TopicNote.find(org_filters).to_list()
        admin_notes = await TopicNote.find(admin_filters).to_list()

        override_concepts = {
            n.concept
            for n in org_notes
            if getattr(n, "source_type", None) == "teacher_override"
        }

        filtered_admin_notes = [
            n for n in admin_notes if n.concept not in override_concepts
        ]

        merged = org_notes + filtered_admin_notes
        return merged[skip : skip + limit]

    async def get_notes_by_concept_id(
        self,
        topic_id: PydanticObjectId,
        concept_id: PydanticObjectId,
        *,
        organization_id: PydanticObjectId,
        limit: int = 100,
        skip: int = 0,
    ) -> List[TopicNote]:
        """Notes linked to a structured curriculum concept by Mongo id."""
        org_filters: Dict[str, Any] = {
            "topic_id": topic_id,
            "concept_id": concept_id,
            "organization_id": organization_id,
        }
        admin_filters: Dict[str, Any] = {
            "topic_id": topic_id,
            "concept_id": concept_id,
            "organization_id": None,
        }
        org_notes = await TopicNote.find(org_filters).to_list()
        admin_notes = await TopicNote.find(admin_filters).to_list()
        override_concepts = {
            n.concept
            for n in org_notes
            if getattr(n, "source_type", None) == "teacher_override"
        }
        filtered_admin_notes = [
            n for n in admin_notes if n.concept not in override_concepts
        ]
        merged = org_notes + filtered_admin_notes
        return merged[skip : skip + limit]

    async def get_org_notes_for_concept(
        self,
        topic_id: PydanticObjectId,
        concept: str,
        organization_id: PydanticObjectId,
    ) -> List[TopicNote]:
        """Tenant-only notes for one topic+concept, newest first."""
        normalized = normalize_concept_filter(concept)
        if normalized is None:
            return []
        return (
            await TopicNote.find(
                {
                    "organization_id": organization_id,
                    "topic_id": topic_id,
                    "concept": normalized,
                }
            )
            .sort([("created_at", -1)])
            .to_list()
        )


def get_topic_note_repository() -> TopicNoteRepository:
    """FastAPI dependency: return a TopicNoteRepository instance."""
    return TopicNoteRepository()
