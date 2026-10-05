from __future__ import annotations

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.models.curriculum.topics import Topic
from app.models.identification.users import User
from app.models.organization import Organization
from app.models.teacher_topic import TeacherTopic
from app.repositories.topic_repository import TopicRepository


async def load_org(organization_id: PydanticObjectId) -> Organization | None:
    return await Organization.get(organization_id)


def _subject_ids_for_class(org: Organization, class_id: str) -> set[str]:
    for c in org.classes or []:
        if c.id == class_id:
            return {s.id for s in (c.subjects or [])}
    return set()


def assert_class_subject_allowed(
    user: User,
    class_id: str,
    subject_id: str,
    org: Organization | None,
) -> None:
    if user.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    valid_c = {c.id for c in (org.classes or [])}
    if class_id not in valid_c:
        raise HTTPException(
            status_code=400,
            detail="class_id is not valid for this organization",
        )
    subjects_in_class = _subject_ids_for_class(org, class_id)
    if subject_id not in subjects_in_class:
        raise HTTPException(
            status_code=400,
            detail="subject_id is not defined for this class",
        )

    if user.role == "teacher":
        assigned_c = list(user.assigned_classes or [])
        assigned_s = list(user.assigned_subjects or [])
        if class_id not in assigned_c:
            raise HTTPException(
                status_code=400,
                detail="class_id is not in your assigned classes",
            )
        if subject_id not in assigned_s:
            raise HTTPException(
                status_code=400,
                detail="subject_id is not in your assigned subjects",
            )
    elif user.role != "admin":
        raise HTTPException(status_code=403, detail="Teacher or admin access required")


def normalize_topic_name(name: str) -> str:
    return name.strip().lower()


def normalize_ordered_unique_concepts(incoming: list[str]) -> list[str]:
    """Trim, drop empties, dedupe case-insensitively, preserve first-seen order."""
    seen_lower: set[str] = set()
    out: list[str] = []
    for raw in incoming:
        t = raw.strip()
        if not t:
            continue
        key = t.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        out.append(t)
    return out


def validate_concept_clusters(
    key_concepts: list[str],
    concept_clusters: list[list[str]] | None,
) -> None:
    """
    Validate that concept_clusters is consistent with key_concepts.

    Rules (all raise ValueError on violation):
      * Every concept inside a cluster must appear in key_concepts
        (case-insensitive, trimmed comparison).
      * No concept may appear in more than one cluster.
      * Empty inner lists are rejected.

    Does nothing when concept_clusters is None or empty — callers may pass
    None freely; the clusters field is always optional.
    """
    if not concept_clusters:
        return

    key_set = {c.strip().lower() for c in key_concepts if c and c.strip()}
    seen: set[str] = set()

    for cluster in concept_clusters:
        if not cluster:
            raise ValueError("concept_clusters must not contain empty inner lists")
        for concept in cluster:
            c_norm = (concept or "").strip().lower()
            if not c_norm:
                raise ValueError(
                    "concept_clusters must not contain empty concept strings"
                )
            if c_norm not in key_set:
                raise ValueError(
                    f"Concept '{concept}' in concept_clusters is not present in key_concepts"
                )
            if c_norm in seen:
                raise ValueError(
                    f"Concept '{concept}' appears more than once across concept_clusters"
                )
            seen.add(c_norm)


async def assert_no_duplicate_topic_name(
    organization_id: PydanticObjectId,
    class_id: str,
    subject_id: str,
    topic_name: str,
    exclude_topic_id: PydanticObjectId | None = None,
) -> None:
    cid = class_id.strip()
    sid = subject_id.strip()
    tname = normalize_topic_name(topic_name)
    if not tname:
        raise HTTPException(status_code=400, detail="topic_name is required")
    candidates = await TeacherTopic.find(
        TeacherTopic.organization_id == organization_id,
        TeacherTopic.class_id == cid,
        TeacherTopic.subject_id == sid,
    ).to_list()
    for doc in candidates:
        if exclude_topic_id is not None and doc.id == exclude_topic_id:
            continue
        if normalize_topic_name(doc.topic_name) == tname:
            raise HTTPException(
                status_code=400,
                detail="Topic already exists for this class and subject",
            )


def org_curriculum_subject_id_for_teacher_topic_row(
    org: Organization | None,
    class_id: str,
    subject_id: str,
) -> PydanticObjectId | None:
    if org is None:
        return None
    for c in org.classes or []:
        if c.id != class_id:
            continue
        for s in c.subjects or []:
            if s.id == subject_id:
                return s.curriculum_subject_id
    return None


async def assert_curriculum_topic_allowed_for_teacher_row(
    user: User,
    teacher_topic: TeacherTopic,
    curriculum_topic_id: PydanticObjectId,
    topic_repository: TopicRepository,
    org: Organization | None,
) -> Topic:
    row = await topic_repository.get_by_id(curriculum_topic_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail="Curriculum topic not found"
        )
    if user.organization_id is None:
        raise HTTPException(status_code=403, detail="User must belong to an organization")
    if (
        row.organization_id is not None
        and row.organization_id != user.organization_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Curriculum topic is not in your organization",
        )
    csid = org_curriculum_subject_id_for_teacher_topic_row(
        org, teacher_topic.class_id, teacher_topic.subject_id
    )
    if csid is None:
        raise HTTPException(
            status_code=400,
            detail="Link the org class subject to a curriculum subject (ID) before linking topics",
        )
    if row.subject_id != csid:
        raise HTTPException(
            status_code=400,
            detail="Curriculum topic does not belong to the curriculum subject linked to this org subject",
        )
    return row


async def get_topic_for_mutation(
    topic_id: PydanticObjectId,
    user: User,
) -> TeacherTopic:
    topic = await TeacherTopic.get(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if user.organization_id is None or topic.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Topic not in your organization")
    if user.role == "teacher" and topic.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own topics")
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Not allowed")
    return topic
