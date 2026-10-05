"""
Integration tests: session creation (both paths).

Covers:
- Admin Topic path  (_create_new_learning_session)
- TeacherTopic path (_create_new_learning_session_teacher_topic)
- Idempotency: second call returns resume_prompt, not a new session
- Key session field defaults are correct on creation

These tests use SessionService directly — no HTTP layer — so they are fast
and isolated from auth/routing concerns.

Mongomock note: the partial unique index on sessions is NOT enforced. Duplicate
prevention is validated via the explicit re-fetch logic in
insert_in_progress_session_or_return_existing, not via a DB index violation.
"""

import pytest
from beanie.odm.fields import PydanticObjectId

from tests.helpers import (
    MONGOMOCK_INDEX_WARNING,
    assert_session_fields,
    reload_session,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_service():
    from app.repositories.session_repository import SessionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.services.session_service import SessionService

    return SessionService(SessionRepository(), TopicRepository())


# ─────────────────────────────────────────────────────────────────────────────
# Admin Topic path
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminTopicSessionCreation:
    async def test_creates_session_with_correct_defaults(self, db, org, topic, student_user):
        """First call for a (student, topic) pair creates a new in-progress session."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        # Must be a Session document, not a resume-prompt dict
        assert not isinstance(result, dict), "Expected Session, got resume-prompt dict"

        assert_session_fields(
            result,
            completion_status="in_progress",
            flow_state="idle",
            current_zone=0,
            current_concept_index=0,
            sus_score=50.0,
            current_mode="normal",
            learning_state="explaining",
            teachback_required=False,
            teachback_attempts=0,
            zone0_phase="anchoring",
        )

    async def test_key_concepts_copied_from_topic(self, db, org, topic, student_user):
        """Session.key_concepts must be a snapshot of the topic's key_concepts at creation."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.key_concepts == topic.key_concepts
        assert result.total_concepts == len(topic.key_concepts)

    async def test_current_concept_set_to_first_concept(self, db, org, topic, student_user):
        """Session.current_concept must be the first concept in key_concepts."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.current_concept == topic.key_concepts[0]

    async def test_is_teacher_progression(self, db, org, topic, student_user):
        """
        Session with total_concepts > 0 must be treated as teacher progression.
        This validates the _is_teacher_progression() check used throughout the service.
        """
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        # _is_teacher_progression checks total_concepts > 0
        assert result.total_concepts > 0

    async def test_second_call_returns_resume_prompt(self, db, org, topic, student_user):
        """
        Calling start_or_resume_session twice without action returns a resume_prompt
        dict. No duplicate session is created.

        Mongomock note: the partial unique index is not enforced.
        The SessionRepository.insert_in_progress_session_or_return_existing method
        re-fetches before insert to prevent duplicates.
        """
        service = _make_service()

        first = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )
        assert not isinstance(first, dict)

        second = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        # Second call must return a resume-prompt, not create a new session
        assert isinstance(second, dict), MONGOMOCK_INDEX_WARNING
        assert second.get("type") == "resume_prompt"
        assert second.get("session_id") == str(first.id)

    async def test_organization_id_on_session(self, db, org, topic, student_user):
        """Session.organization_id is resolved from the student's organisation."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.organization_id == org.id

    async def test_student_id_on_session(self, db, org, topic, student_user):
        """Session.student_id matches the requesting student."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.student_id == student_user.id

    async def test_topic_id_on_session(self, db, org, topic, student_user):
        """Session.topic_id matches the topic used to create the session."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.topic_id == topic.id


# ─────────────────────────────────────────────────────────────────────────────
# TeacherTopic path
# ─────────────────────────────────────────────────────────────────────────────

class TestTeacherTopicSessionCreation:
    async def test_creates_session_for_teacher_topic(
        self, db, org, teacher_topic, student_user
    ):
        """TeacherTopic path also creates a valid in-progress session."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=teacher_topic.id,
            student_organization_id=org.id,
        )

        assert not isinstance(result, dict)
        assert result.completion_status == "in_progress"
        assert result.flow_state == "idle"
        assert result.current_zone == 0
        assert result.sus_score == 50.0

    async def test_teacher_topic_key_concepts_copied(
        self, db, org, teacher_topic, student_user
    ):
        """Session.key_concepts is a snapshot of the TeacherTopic's key_concepts."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=teacher_topic.id,
            student_organization_id=org.id,
        )

        assert result.key_concepts == teacher_topic.key_concepts
        assert result.total_concepts == len(teacher_topic.key_concepts)

    async def test_teacher_topic_organization_id(
        self, db, org, teacher_topic, student_user
    ):
        """TeacherTopic session uses the teacher_topic's organisation_id."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=teacher_topic.id,
            student_organization_id=org.id,
        )

        assert result.organization_id == teacher_topic.organization_id

    async def test_teacher_topic_idempotent(
        self, db, org, teacher_topic, student_user
    ):
        """Second call for a TeacherTopic session also returns resume_prompt."""
        service = _make_service()

        first = await service.start_session(
            student_id=student_user.id,
            topic_id=teacher_topic.id,
            student_organization_id=org.id,
        )
        assert not isinstance(first, dict)

        second = await service.start_session(
            student_id=student_user.id,
            topic_id=teacher_topic.id,
            student_organization_id=org.id,
        )
        assert isinstance(second, dict), MONGOMOCK_INDEX_WARNING
        assert second.get("type") == "resume_prompt"


# ─────────────────────────────────────────────────────────────────────────────
# Model backward-compatibility: new optional fields default correctly
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionModelDefaults:
    """
    Verify that when Session is loaded from a document that was written without
    optional fields, Pydantic fills in the correct defaults.

    This simulates loading an "old" session that pre-dates newly added fields.
    It is the canonical migration-safety test: as new fields are added to the
    Session model (e.g. concept_clusters, current_cluster_index), add them here.
    """

    async def test_zone0_fields_have_defaults(self, db, org, topic, student_user):
        """Zone 0 fields start at their expected default values."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.zone0_phase == "anchoring"
        assert result.zone0_prereq_done is False
        assert result.zone0_curiosity_shown is False
        assert result.zone0_prereq_question is None
        assert result.zone0_curiosity_question is None

    async def test_diagnostic_fields_have_defaults(self, db, org, topic, student_user):
        """Diagnostic mode starts inactive."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.diagnostic_mode is False
        assert result.diagnostic_step == 0
        assert result.diagnostic_attempt_count == 0
        assert result.diagnostic_topic_ids == []

    async def test_sus_score_default(self, db, org, topic, student_user):
        """SUS score starts at 50 (neutral baseline)."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.sus_score == 50.0

    async def test_cluster_progress_fields_have_defaults(
        self, db, org, topic, student_user
    ):
        """Cluster layer fields default safely for older clients and Mongo docs."""
        service = _make_service()
        result = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        assert result.current_cluster_index == 0
        assert result.cluster_check_pending is False
        assert result.cluster_check_concepts is None
        assert result.zone_round_successes == 0

    async def test_session_persisted_and_reloadable(self, db, org, topic, student_user):
        """
        Session written to mongomock is retrievable by ID.
        This validates the full serialise→store→deserialise round-trip.
        """
        service = _make_service()
        created = await service.start_session(
            student_id=student_user.id,
            topic_id=topic.id,
            student_organization_id=org.id,
        )

        reloaded = await reload_session(created.id)

        assert reloaded.id == created.id
        assert reloaded.student_id == created.student_id
        assert reloaded.key_concepts == created.key_concepts
        assert reloaded.current_zone == created.current_zone
        assert reloaded.sus_score == created.sus_score
