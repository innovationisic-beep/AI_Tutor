"""Resolve global catalog subject/topics for teacher org class preview (import UX)."""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from typing import Any

from beanie.odm.fields import PydanticObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.models.content.topic_notes import TopicNote
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.prerequisite_graph import PrerequisiteGraph
from app.models.curriculum.subjects import Subject
from app.models.curriculum.topic_progression_map import TopicProgressionMap
from app.models.curriculum.topics import Topic
from app.models.identification.users import User
from app.models.organization import Organization
from app.models.teacher_topic import TeacherTopic
from app.services.organization_structure_service import OrganizationStructureService
from app.services.teacher_topic_service import (
    normalize_ordered_unique_concepts,
    normalize_topic_name,
)

# Minimum fuzzy score when neither string is a substring of the other.
_SUBJECT_SIMILARITY_THRESHOLD = 0.55
# Short-name substring match (e.g. math → mathematics, science → general science).
_SUBSTRING_MATCH_SCORE = 0.92
_MIN_SUBSTRING_LEN = 3

# Preview payload limits (keep responses small and fast).
_PREVIEW_NOTES_PER_TOPIC = 2
_PREVIEW_QUESTIONS_PER_TOPIC = 3
_PREVIEW_NOTE_MARKDOWN_MAX = 150
_PREVIEW_KEY_CONCEPTS_MAX = 30
_PREVIEW_TOPIC_ENRICH_CONCURRENCY = 8


def _truncate_preview_text(text: str, max_len: int) -> str:
    s = text or ""
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "…"


async def _sample_admin_notes_for_topic(topic_id: PydanticObjectId) -> list[dict[str, Any]]:
    rows = await TopicNote.find(
        {
            "topic_id": topic_id,
            "organization_id": None,
            "source_type": "admin",
        }
    ).sort([("updated_at", -1)]).limit(_PREVIEW_NOTES_PER_TOPIC).to_list()
    out: list[dict[str, Any]] = []
    for n in rows:
        raw_md = n.content_markdown or ""
        out.append(
            {
                "concept": n.concept,
                "content_markdown": _truncate_preview_text(
                    raw_md, _PREVIEW_NOTE_MARKDOWN_MAX
                ),
            }
        )
    return out


async def _sample_admin_questions_for_topic(
    topic_id: PydanticObjectId,
) -> list[dict[str, Any]]:
    rows = await TopicQuestionBank.find(
        {
            "topic_id": topic_id,
            "organization_id": None,
            "source_type": "admin",
        }
    ).sort([("updated_at", -1)]).limit(_PREVIEW_QUESTIONS_PER_TOPIC).to_list()
    out: list[dict[str, Any]] = []
    for q in rows:
        out.append(
            {
                "question_text": q.question_text or "",
                "options": list(q.options or []),
                "correct_answer": q.correct_answer,
            }
        )
    return out


async def _build_topic_preview_row(t: Topic) -> dict[str, Any]:
    notes, questions = await asyncio.gather(
        _sample_admin_notes_for_topic(t.id),
        _sample_admin_questions_for_topic(t.id),
    )
    kc_full = list(t.key_concepts or [])
    kc = kc_full[:_PREVIEW_KEY_CONCEPTS_MAX]
    return {
        "name": t.topic_name,
        "concept_count": len(kc_full),
        "key_concepts": kc,
        "sample_notes": notes,
        "sample_questions": questions,
    }


def normalize_grade_for_strict_match(value: str | None) -> str:
    """Same rules as curriculum student grade matching: case-insensitive, optional ``Grade ``."""
    if not value:
        return ""
    s = value.strip().lower()
    if s.startswith("grade "):
        s = s[6:].strip()
    return s


def parse_grade_token_from_class_name(class_name: str) -> str | None:
    """
    Extract a grade token from the org class name for strict catalog matching.

    Prefers explicit grade/class/year + number, then leading class number (e.g. 7A),
    then all-digit label, else the full trimmed name (matches catalog if admins used the same label).
    """
    s = (class_name or "").strip()
    if not s:
        return None
    m = re.search(
        r"\b(?:grade|class|year)\s*([0-9]{1,2})\b",
        s,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.match(r"^([0-9]{1,2})(?:\s|$|\D)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9]{1,2}", s):
        return s
    return s


def _normalize_subject_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def subject_name_match_score(teacher_subject_name: str, catalog_subject_name: str) -> float:
    """Fuzzy / partial match between org subject label and catalog subject name (not exact-only)."""
    a = _normalize_subject_label(teacher_subject_name)
    b = _normalize_subject_label(catalog_subject_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= _MIN_SUBSTRING_LEN and a in b:
        return _SUBSTRING_MATCH_SCORE
    if len(b) >= _MIN_SUBSTRING_LEN and b in a:
        return _SUBSTRING_MATCH_SCORE
    return float(SequenceMatcher(None, a, b).ratio())


def _find_class_and_subject_names(
    org: Organization,
    class_id: str,
    subject_id: str,
) -> tuple[str | None, str | None]:
    for c in org.classes or []:
        if c.id != class_id:
            continue
        cname = (c.name or "").strip()
        for item in c.subjects or []:
            if item.id == subject_id:
                return cname, (item.name or "").strip()
        return cname, None
    return None, None


async def resolve_matched_catalog_bundle(
    org: Organization,
    class_id: str,
    subject_id: str,
) -> tuple[Subject, list[Topic]] | None:
    """
    Match org class/subject to global catalog subject (grade-strict, name fuzzy);
    return that subject and its active global topics, or None.
    """
    class_name, org_subject_name = _find_class_and_subject_names(org, class_id, subject_id)
    if not org_subject_name or class_name is None:
        return None

    grade_token = parse_grade_token_from_class_name(class_name)
    if not grade_token:
        return None

    want_grade = normalize_grade_for_strict_match(grade_token)
    if not want_grade:
        return None

    global_subjects = await Subject.find(
        {
            "organization_id": None,
            "is_active": True,
            "status": "active",
        }
    ).to_list()

    grade_candidates = [
        s
        for s in global_subjects
        if normalize_grade_for_strict_match(s.grade) == want_grade
    ]
    if not grade_candidates:
        return None

    scored = [
        (subject_name_match_score(org_subject_name, s.name), s)
        for s in grade_candidates
    ]
    scored.sort(key=lambda x: (-x[0], (x[1].name or "").lower()))
    best_score, best = scored[0]
    if best_score < _SUBJECT_SIMILARITY_THRESHOLD:
        return None

    topics = await Topic.find(
        {
            "subject_id": best.id,
            "organization_id": None,
            "is_active": True,
            "status": "active",
        }
    ).sort([("topic_order", 1), ("topic_name", 1)]).to_list()

    return best, topics


async def build_teacher_curriculum_preview(
    org: Organization,
    class_id: str,
    subject_id: str,
) -> dict[str, Any]:
    """
    Match org class/subject to a global catalog subject (grade-strict, name fuzzy), then list topics.

    Returns a dict suitable for ``CurriculumPreviewResponse`` serialization.
    """
    bundle = await resolve_matched_catalog_bundle(org, class_id, subject_id)
    if bundle is None:
        return {
            "found": False,
            "message": "No curriculum found",
            "subject": None,
            "topics": [],
        }

    best, topics = bundle

    sem = asyncio.Semaphore(_PREVIEW_TOPIC_ENRICH_CONCURRENCY)

    async def _enrich_one(topic: Topic) -> dict[str, Any]:
        async with sem:
            return await _build_topic_preview_row(topic)

    topic_rows = await asyncio.gather(*[_enrich_one(t) for t in topics])

    return {
        "found": True,
        "message": None,
        "subject": {
            "id": str(best.id),
            "name": best.name,
            "grade": best.grade,
        },
        "topics": list(topic_rows),
    }


def _grade_board_for_imported_notes(subject: Subject) -> tuple[str, str]:
    """TopicNote requires grade/board; use matched catalog subject."""
    g = (subject.grade or "").strip() or "General"
    b = (subject.board or "").strip() or "general"
    return g[:32], b[:64]


async def _copy_admin_notes_to_teacher_topic(
    catalog_topic_id: PydanticObjectId,
    teacher_topic: TeacherTopic,
    org_id: PydanticObjectId,
    grade: str,
    board: str,
) -> None:
    notes = await TopicNote.find(
        {
            "topic_id": catalog_topic_id,
            "organization_id": None,
            "source_type": "admin",
        }
    ).to_list()
    for n in notes:
        md = (n.content_markdown or "").strip()
        if not md:
            continue
        nt = n.note_type
        if nt not in ("summary", "detailed", "revision"):
            nt = "detailed"
        try:
            copy = TopicNote(
                organization_id=org_id,
                topic_id=teacher_topic.id,
                grade=grade,
                board=board,
                note_type=nt,
                content_markdown=md[:25000],
                source_type="teacher",
                teaching_style=n.teaching_style,
                interest_category=n.interest_category,
                difficulty_level=n.difficulty_level or "medium",
                concept=n.concept,
                approved=True,
                usage_count=0,
                embedding=None,
                content_version=1,
            )
            await copy.insert()
        except (ValueError, ValidationError):
            continue


async def _copy_admin_questions_to_teacher_topic(
    catalog_topic_id: PydanticObjectId,
    teacher_topic: TeacherTopic,
    org_id: PydanticObjectId,
) -> None:
    rows = await TopicQuestionBank.find(
        {
            "topic_id": catalog_topic_id,
            "organization_id": None,
            "source_type": "admin",
        }
    ).to_list()
    for q in rows:
        qtext = (q.question_text or "").strip()
        if len(qtext) < 3:
            continue
        expl = (q.explanation or "").strip()
        if not expl:
            expl = "Imported from curriculum."
        opts = [str(x).strip() for x in (q.options or []) if str(x).strip()][
            :10
        ]
        try:
            copy = TopicQuestionBank(
                organization_id=org_id,
                topic_id=teacher_topic.id,
                difficulty_level=q.difficulty_level or "medium",
                question_text=qtext[:5000],
                options=opts,
                correct_answer=q.correct_answer,
                explanation=expl[:5000],
                source_type="teacher",
                concept=q.concept,
                question_type=getattr(q, "question_type", None),
                quiz_stage=getattr(q, "quiz_stage", None),
                approved=True,
                usage_count=0,
                embedding=None,
            )
            await copy.insert()
        except (ValueError, ValidationError):
            continue


async def import_catalog_teacher_topics(
    user: User,
    org: Organization,
    class_id: str,
    subject_id: str,
) -> dict[str, Any]:
    """
    Link org subject to matched global catalog subject and create ``TeacherTopic`` rows
    (with ``curriculum_topic_id`` and key concepts), skipping names that already exist
    for this class/subject in the organization.

    For each newly inserted teacher topic, copies all admin ``TopicNote`` and
    ``TopicQuestionBank`` rows from the catalog topic onto the teacher topic id
    (org-scoped, ``source_type`` teacher).

    After inserts, copies admin global (``organization_id`` null) prerequisite and
    progression edges whose endpoints are both in the admin→teacher topic id map
    for this import batch onto org-scoped graph documents (teacher topic ids).
    """
    if user.organization_id is None:
        return {
            "ok": False,
            "message": "User has no organization",
            "imported_count": 0,
            "skipped_count": 0,
        }

    cid = class_id.strip()
    sid = subject_id.strip()
    bundle = await resolve_matched_catalog_bundle(org, cid, sid)
    if bundle is None:
        return {
            "ok": False,
            "message": "No curriculum found",
            "imported_count": 0,
            "skipped_count": 0,
        }

    matched_subject, catalog_topics = bundle

    await OrganizationStructureService.link_class_subject_to_curriculum(
        org, cid, sid, matched_subject.id
    )

    existing = await TeacherTopic.find(
        {
            "organization_id": user.organization_id,
            "class_id": cid,
            "subject_id": sid,
        }
    ).to_list()
    used_names = {normalize_topic_name(d.topic_name) for d in existing}

    imported_count = 0
    skipped_count = 0
    note_grade, note_board = _grade_board_for_imported_notes(matched_subject)
    topic_id_map: dict[PydanticObjectId, PydanticObjectId] = {}

    for t in catalog_topics:
        tnorm = normalize_topic_name(t.topic_name)
        if not tnorm:
            skipped_count += 1
            continue
        if tnorm in used_names:
            skipped_count += 1
            continue

        doc = TeacherTopic(
            organization_id=user.organization_id,
            teacher_id=user.id,
            class_id=cid,
            subject_id=sid,
            topic_name=tnorm,
            key_concepts=normalize_ordered_unique_concepts(
                list(t.key_concepts or [])
            ),
            concept_clusters=t.concept_clusters,
            curriculum_topic_id=t.id,
        )
        await doc.insert()
        if t.curriculum_schema_version == "v2":
            from app.services.curriculum.curriculum_clone_service import (
                clone_structured_curriculum,
            )

            await clone_structured_curriculum(
                source_topic_id=t.id,
                source_topic_source="catalog",
                source_organization_id=None,
                target_topic_id=doc.id,
                target_topic_source="teacher",
                target_organization_id=user.organization_id,
                copy_content=True,
                note_grade=note_grade,
                note_board=note_board,
            )
        else:
            await _copy_admin_notes_to_teacher_topic(
                t.id,
                doc,
                user.organization_id,
                note_grade,
                note_board,
            )
            await _copy_admin_questions_to_teacher_topic(
                t.id,
                doc,
                user.organization_id,
            )
        topic_id_map[t.id] = doc.id
        used_names.add(tnorm)
        imported_count += 1

    org_id = user.organization_id
    if topic_id_map:
        catalog_ids = list(topic_id_map.keys())
        admin_prereqs = await PrerequisiteGraph.find(
            {
                "organization_id": None,
                "topic_id": {"$in": catalog_ids},
                "prerequisite_topic_id": {"$in": catalog_ids},
            }
        ).to_list()
        for edge in admin_prereqs:
            aid = edge.topic_id
            pre_id = edge.prerequisite_topic_id
            if aid not in topic_id_map or pre_id not in topic_id_map:
                continue
            new_topic_id = topic_id_map[aid]
            new_pre_id = topic_id_map[pre_id]
            if new_topic_id == new_pre_id:
                continue
            dup = await PrerequisiteGraph.find_one(
                {
                    "organization_id": org_id,
                    "topic_id": new_topic_id,
                    "prerequisite_topic_id": new_pre_id,
                }
            )
            if dup is not None:
                continue
            try:
                await PrerequisiteGraph(
                    organization_id=org_id,
                    topic_id=new_topic_id,
                    prerequisite_topic_id=new_pre_id,
                ).insert()
            except (DuplicateKeyError, ValidationError):
                continue

        admin_prog = await TopicProgressionMap.find(
            {
                "organization_id": None,
                "topic_id": {"$in": catalog_ids},
                "recommended_next_topic_id": {"$in": catalog_ids},
            }
        ).to_list()
        for row in admin_prog:
            aid = row.topic_id
            next_id = row.recommended_next_topic_id
            if aid not in topic_id_map or next_id not in topic_id_map:
                continue
            new_topic_id = topic_id_map[aid]
            new_next_id = topic_id_map[next_id]
            if new_topic_id == new_next_id:
                continue
            mastery = float(row.minimum_mastery_to_recommend)
            mastery = min(100.0, max(0.0, mastery))
            dup = await TopicProgressionMap.find_one(
                {
                    "organization_id": org_id,
                    "topic_id": new_topic_id,
                    "recommended_next_topic_id": new_next_id,
                }
            )
            if dup is not None:
                continue
            try:
                await TopicProgressionMap(
                    organization_id=org_id,
                    topic_id=new_topic_id,
                    recommended_next_topic_id=new_next_id,
                    minimum_mastery_to_recommend=mastery,
                ).insert()
            except (DuplicateKeyError, ValidationError):
                continue

    return {
        "ok": True,
        "message": None,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "curriculum_subject_id": str(matched_subject.id),
    }
