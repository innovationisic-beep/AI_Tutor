"""Tests for quiz_stage tagging, caps, and bank selection filters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.core.constants import CLUSTER_QUESTIONS_PER_CLUSTER, CONCEPT_CHECK_SLOT_TYPES
from app.models.content.topic_question_bank import TopicQuestionBank
from app.models.curriculum.curriculum_cluster import CurriculumCluster
from app.models.curriculum.curriculum_concept import CurriculumConcept
from app.models.curriculum.curriculum_zone import CurriculumZone
from app.models.curriculum.topics import Topic
from app.services.curriculum.question_bank_stage_service import (
    assert_quiz_stage_caps,
    count_cluster_quiz_for_cluster,
    count_concept_check_by_type,
)
from app.services.handlers.cluster_check_question_service import (
    _pick_cluster_quiz_from_bank,
)
from app.services.handlers.concept_check_question_service import _pick_from_bank


async def _seed_cluster_with_two_concepts(db):
    topic = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Quiz Stage Topic",
        topic_slug="quiz-stage-topic",
        topic_description="Topic for quiz_stage tests",
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2025",
        curriculum_version="1",
        curriculum_schema_version="v2",
        key_concepts=[],
    )
    await topic.insert()

    zone = await CurriculumZone(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        zone_number=1,
        title="Core",
        purpose="core_teaching",
        allows_vtse=True,
        status="draft",
    ).insert()

    cluster = await CurriculumCluster(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        cluster_number=1,
        title="Cluster A",
        sort_order=0,
        status="draft",
    ).insert()

    a = await CurriculumConcept(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        curriculum_cluster_id=cluster.id,
        slug="concept-a",
        display_name="Concept A",
        canonical_runtime_key="concept a",
        sort_order=0,
        study_points=["Study A"],
        learning_outcomes=["Outcome A"],
        status="draft",
    ).insert()
    b = await CurriculumConcept(
        organization_id=None,
        topic_id=topic.id,
        topic_source="catalog",
        curriculum_zone_id=zone.id,
        curriculum_cluster_id=cluster.id,
        slug="concept-b",
        display_name="Concept B",
        canonical_runtime_key="concept b",
        sort_order=1,
        study_points=["Study B"],
        learning_outcomes=["Outcome B"],
        status="draft",
    ).insert()
    return topic, a, b


@pytest.mark.asyncio
async def test_topic_question_bank_accepts_quiz_stage(db):
    topic_id = PydanticObjectId()
    row = TopicQuestionBank(
        organization_id=None,
        topic_id=topic_id,
        question_text="What is matter?",
        options=["A", "B", "C", "D"],
        correct_answer="A",
        explanation="A is correct",
        difficulty_level="medium",
        source_type="admin",
        approved=True,
        question_type="mcq",
        quiz_stage="concept_check",
        concept="matter",
    )
    await row.insert()
    loaded = await TopicQuestionBank.get(row.id)
    assert loaded is not None
    assert loaded.quiz_stage == "concept_check"
    assert loaded.question_type == "mcq"


@pytest.mark.asyncio
async def test_concept_check_cap_rejects_third_mcq(db):
    topic, concept_a, _ = await _seed_cluster_with_two_concepts(db)
    for i in range(2):
        await TopicQuestionBank(
            organization_id=None,
            topic_id=topic.id,
            question_text=f"MCQ {i} about concept A?",
            options=["Yes", "No", "Maybe", "Never"],
            correct_answer="Yes",
            explanation="Yes",
            difficulty_level="medium",
            source_type="admin",
            approved=True,
            concept="concept a",
            concept_id=concept_a.id,
            question_type="mcq",
            quiz_stage="concept_check",
        ).insert()

    counts = await count_concept_check_by_type(concept_a.id)
    assert counts["mcq"] == 2

    with pytest.raises(HTTPException) as exc:
        await assert_quiz_stage_caps(
            concept=concept_a,
            quiz_stage="concept_check",
            question_type="mcq",
        )
    assert exc.value.status_code == 400
    assert "MCQ" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_cluster_quiz_cap_is_cluster_wide(db):
    topic, concept_a, concept_b = await _seed_cluster_with_two_concepts(db)
    for i in range(CLUSTER_QUESTIONS_PER_CLUSTER):
        owner = concept_a if i < 2 else concept_b
        await TopicQuestionBank(
            organization_id=None,
            topic_id=topic.id,
            question_text=f"Describe idea {i} in your own words please.",
            options=[],
            correct_answer=None,
            explanation="See board",
            difficulty_level="medium",
            source_type="admin",
            approved=True,
            concept=owner.canonical_runtime_key,
            concept_id=owner.id,
            question_type="descriptive",
            quiz_stage="cluster_quiz",
        ).insert()

    used = await count_cluster_quiz_for_cluster(concept_b)
    assert used == CLUSTER_QUESTIONS_PER_CLUSTER

    with pytest.raises(HTTPException) as exc:
        await assert_quiz_stage_caps(
            concept=concept_b,
            quiz_stage="cluster_quiz",
            question_type="descriptive",
        )
    assert exc.value.status_code == 400
    assert "cluster" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_pick_from_bank_ignores_null_and_cluster_stage():
    session = SimpleNamespace(
        id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        used_question_ids=[],
        last_question="matter",
        current_zone=1,
    )
    ctx = MagicMock()

    tagged_ok = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Which option describes matter correctly?",
        options=["Has mass", "Has no mass", "Is energy only", "Is vacuum"],
        correct_answer="Has mass",
        explanation="Matter has mass",
        difficulty_level="basic",
        question_type="mcq",
        quiz_stage="concept_check",
        concept="matter",
        embedding=None,
    )
    wrong_stage = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Which option is for cluster only?",
        options=["A", "B", "C", "D"],
        correct_answer="A",
        explanation="A",
        difficulty_level="basic",
        question_type="mcq",
        quiz_stage="cluster_quiz",
        concept="matter",
        embedding=None,
    )
    null_stage = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Untagged MCQ that must be ignored?",
        options=["A", "B", "C", "D"],
        correct_answer="A",
        explanation="A",
        difficulty_level="basic",
        question_type="mcq",
        quiz_stage=None,
        concept="matter",
        embedding=None,
    )

    async def fake_get_questions(*args, **kwargs):
        return [wrong_stage, null_stage, tagged_ok]

    with (
        patch(
            "app.services.handlers.concept_check_question_service.TopicQuestionRepository"
        ) as Repo,
        patch(
            "app.services.handlers.concept_check_question_service.EventRepository"
        ) as EvRepo,
        patch(
            "app.services.handlers.concept_check_question_service._db_difficulty_for_session",
            new=AsyncMock(return_value=("easy", {"$in": ["basic"]})),
        ),
        patch(
            "app.services.handlers.concept_check_question_service.pack_matches_taught",
            return_value=True,
        ),
        patch(
            "app.services.handlers.concept_check_question_service.is_broad_quiz_stem",
            return_value=False,
        ),
        patch(
            "app.services.handlers.concept_check_question_service.is_meta_quiz_question",
            return_value=False,
        ),
    ):
        Repo.return_value.get_questions = AsyncMock(side_effect=fake_get_questions)
        EvRepo.return_value.get_many = AsyncMock(return_value=[])

        pack = await _pick_from_bank(
            ctx,
            session,
            concept="matter",
            required_type="mcq",
            taught_ctx={"facts": ["matter has mass"]},
            quiz_stage="concept_check",
        )

    assert pack is not None
    assert pack["source"] == "db"
    assert "matter" in pack["question"].lower() or "mass" in pack["question"].lower()
    assert pack["bank_id"] == str(tagged_ok.id)


@pytest.mark.asyncio
async def test_pick_cluster_quiz_from_all_concepts_in_order():
    session = SimpleNamespace(
        id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        used_question_ids=[],
        last_question="",
        current_zone=1,
    )
    ctx = MagicMock()

    q_a = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Explain concept A briefly in your own words.",
        options=[],
        correct_answer=None,
        explanation="A",
        difficulty_level="basic",
        question_type="descriptive",
        quiz_stage="cluster_quiz",
        concept="concept a",
        created_at=datetime(2024, 1, 1),
        embedding=None,
    )
    q_b = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Explain concept B briefly in your own words.",
        options=[],
        correct_answer=None,
        explanation="B",
        difficulty_level="basic",
        question_type="descriptive",
        quiz_stage="cluster_quiz",
        concept="concept b",
        created_at=datetime(2024, 1, 2),
        embedding=None,
    )
    ignored_cc = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Concept-check descriptive should be ignored here.",
        options=[],
        correct_answer=None,
        explanation="no",
        difficulty_level="basic",
        question_type="descriptive",
        quiz_stage="concept_check",
        concept="concept a",
        created_at=datetime(2023, 12, 31),
        embedding=None,
    )

    async def fake_get_questions(topic_id, concept=None, **kwargs):
        if concept == "concept a":
            return [ignored_cc, q_a]
        if concept == "concept b":
            return [q_b]
        return []

    with (
        patch(
            "app.services.handlers.cluster_check_question_service.TopicQuestionRepository"
        ) as Repo,
        patch(
            "app.services.handlers.cluster_check_question_service.EventRepository"
        ) as EvRepo,
        patch(
            "app.services.handlers.cluster_check_question_service._db_difficulty_for_session",
            new=AsyncMock(return_value=("easy", {"$in": ["basic"]})),
        ),
        patch(
            "app.services.handlers.cluster_check_question_service.pack_matches_taught",
            return_value=True,
        ),
        patch(
            "app.services.handlers.cluster_check_question_service.is_broad_quiz_stem",
            return_value=False,
        ),
        patch(
            "app.services.handlers.cluster_check_question_service.is_meta_quiz_question",
            return_value=False,
        ),
    ):
        Repo.return_value.get_questions = AsyncMock(side_effect=fake_get_questions)
        EvRepo.return_value.get_many = AsyncMock(return_value=[])

        pack = await _pick_cluster_quiz_from_bank(
            ctx,
            session,
            cluster_concepts=["concept a", "concept b"],
            required_type="descriptive",
            taught_ctx={"facts": ["x"]},
        )

    assert pack is not None
    assert pack["bank_id"] == str(q_a.id)
    assert "concept a" in pack["question"].lower()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_cluster_pick_allows_same_stem_as_prior_concept_check():
    """Cluster bank Q must not be skipped just because concept-check asked same text."""
    session = SimpleNamespace(
        id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        used_question_ids=[],  # different bank ids — concept-check row not in used set
        last_question="",
        current_zone=1,
    )
    ctx = MagicMock()
    desc1 = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Do humans have emotions?",
        options=[],
        correct_answer=None,
        explanation="See board",
        difficulty_level="medium",
        question_type="descriptive",
        quiz_stage="cluster_quiz",
        concept="humans vs robots",
        created_at=datetime(2026, 9, 15, 1, 0, 0),
        embedding=None,
    )
    desc2 = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Do robots have emotions?",
        options=[],
        correct_answer=None,
        explanation="See board",
        difficulty_level="medium",
        question_type="descriptive",
        quiz_stage="cluster_quiz",
        concept="humans vs robots",
        created_at=datetime(2026, 9, 15, 1, 1, 0),
        embedding=None,
    )

    async def fake_get_questions(topic_id, concept=None, **kwargs):
        return [desc1, desc2]

    with (
        patch(
            "app.services.handlers.cluster_check_question_service.TopicQuestionRepository"
        ) as Repo,
        patch(
            "app.services.handlers.cluster_check_question_service._db_difficulty_for_session",
            new=AsyncMock(return_value=("easy", {"$in": ["basic"]})),
        ),
    ):
        Repo.return_value.get_questions = AsyncMock(side_effect=fake_get_questions)

        first = await _pick_cluster_quiz_from_bank(
            ctx,
            session,
            cluster_concepts=["humans vs robots"],
            required_type="descriptive",
        )
        assert first is not None
        assert first["bank_id"] == str(desc1.id)

        # Simulate concept-check already logged the same stem in events — must not matter.
        session.used_question_ids = [first["bank_id"]]
        second = await _pick_cluster_quiz_from_bank(
            ctx,
            session,
            cluster_concepts=["humans vs robots"],
            required_type="descriptive",
        )
        assert second is not None
        assert second["bank_id"] == str(desc2.id)


async def test_pick_from_bank_accepts_two_option_authored_mcq():
    """Teacher 2-option MCQs must not be rejected by AI grounding gates."""
    session = SimpleNamespace(
        id=PydanticObjectId(),
        topic_id=PydanticObjectId(),
        organization_id=PydanticObjectId(),
        used_question_ids=[],
        last_question="humans",
        current_zone=1,
    )
    ctx = MagicMock()
    tagged_ok = SimpleNamespace(
        id=PydanticObjectId(),
        question_text="Do humans have emotions?",
        options=["Yes", "No"],
        correct_answer="Yes",
        explanation="Yes",
        difficulty_level="medium",
        question_type="mcq",
        quiz_stage="concept_check",
        concept="humans vs robots",
        embedding=None,
    )

    async def fake_get_questions(*args, **kwargs):
        return [tagged_ok]

    with (
        patch(
            "app.services.handlers.concept_check_question_service.TopicQuestionRepository"
        ) as Repo,
        patch(
            "app.services.handlers.concept_check_question_service.EventRepository"
        ) as EvRepo,
        patch(
            "app.services.handlers.concept_check_question_service._db_difficulty_for_session",
            new=AsyncMock(return_value=("easy", {"$in": ["basic"]})),
        ),
        patch(
            "app.services.handlers.concept_check_question_service.pack_matches_taught",
            return_value=False,
        ),
        patch(
            "app.services.handlers.concept_check_question_service.is_broad_quiz_stem",
            return_value=True,
        ),
    ):
        Repo.return_value.get_questions = AsyncMock(side_effect=fake_get_questions)
        EvRepo.return_value.get_many = AsyncMock(return_value=[])

        pack = await _pick_from_bank(
            ctx,
            session,
            concept="humans vs robots",
            required_type="mcq",
            taught_ctx={"facts": []},
            quiz_stage="concept_check",
        )

    assert pack is not None
    assert pack["source"] == "db"
    assert pack["options"] == ["Yes", "No"]
    assert pack["correct_answer"] == "Yes"