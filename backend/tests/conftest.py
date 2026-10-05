"""
Shared test fixtures.

Architecture decisions:
- Each test gets a fresh AsyncMongoMockClient → zero state leakage between tests.
- app.main.connect_to_mongo is patched to a no-op so the FastAPI lifespan does not
  attempt a real MongoDB connection when the AsyncClient transport starts.
- Beanie is initialised with mongomock BEFORE the lifespan runs, so all ODM calls
  inside the app route handlers use the same in-memory database.
- get_current_user is overridden per-test via app.dependency_overrides so every
  route call is pre-authenticated as the test student.

Known mongomock-motor limitations (documented, not hidden):
- Partial unique-index expressions are NOT enforced. The duplicate-session guard
  in insert_in_progress_session_or_return_existing must be tested via explicit
  double-call assertions, not index violation.
- $lookup / $facet aggregation stages are not supported. None are used in the
  code paths covered by these tests.
"""

import os
from datetime import datetime
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from beanie import init_beanie
from beanie.odm.fields import PydanticObjectId
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

# ── Set env vars BEFORE any app module is imported ────────────────────────────
# These must be at module level so they are in place when pytest collects tests.
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-not-real")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/ai_tutor_test")
os.environ.setdefault("REDIS_URL", "")  # empty → no Redis needed in tests

# ── App imports (after env vars are set) ──────────────────────────────────────
from app.core.model_loader import get_document_models  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Database fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def db():
    """
    Initialise Beanie with an in-memory mongomock database.

    The patch on app.main.connect_to_mongo prevents the FastAPI lifespan from
    connecting to a real MongoDB instance when the AsyncClient transport starts up.
    Each invocation creates a fresh client so tests cannot share state.
    """
    client = AsyncMongoMockClient()
    database = client.get_database("test_db")

    # Patch the reference used by the lifespan (imported name in app.main).
    with patch("app.main.connect_to_mongo", new=AsyncMock()):
        await init_beanie(
            database=database,
            document_models=get_document_models(),
        )
        yield database


# ─────────────────────────────────────────────────────────────────────────────
# Domain fixtures  (all depend on `db` to ensure Beanie is ready)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def org(db):
    """Minimal institution organisation."""
    from app.models.organization import Organization

    o = Organization(
        name="Test School",
        organization_type="institution",
        max_students=200,
        max_teachers=20,
        status="active",
    )
    await o.insert()
    return o


@pytest.fixture
async def student_user(db, org):
    """Student User document."""
    from app.models.identification.users import User

    u = User(
        organization_id=org.id,
        email="student@testschool.com",
        password_hash=hash_password("TestPass123!"),
        role="student",
        status="active",
    )
    await u.insert()
    return u


@pytest.fixture
async def teacher_user(db, org):
    """Teacher User document."""
    from app.models.identification.users import User

    u = User(
        organization_id=org.id,
        email="teacher@testschool.com",
        password_hash=hash_password("TeachPass123!"),
        role="teacher",
        status="active",
    )
    await u.insert()
    return u


@pytest.fixture
async def student_profile(db, org, student_user):
    """StudentProfile for the test student (used by _teacher_explain_turn)."""
    from app.models.identification.student_profiles import StudentProfile

    sp = StudentProfile(
        organization_id=org.id,
        user_id=student_user.id,
        full_name="Alice Test",
        grade="10",
        board="CBSE",
        preferred_teaching_style="mixed",
        preferred_depth="standard",
        preferred_voice_speed=1.0,
        learning_speed_score=1.0,
    )
    await sp.insert()
    return sp


@pytest.fixture
def student_token(student_user):
    """Valid JWT for the test student — uses the real security module."""
    return create_access_token({"user_id": str(student_user.id)})


@pytest.fixture
async def topic(db, org):
    """
    Admin-curriculum Topic with four key_concepts.
    total_concepts will be 4 → _is_teacher_progression returns True.
    subject_id uses a fake ObjectId (no Subject document required for these tests).
    """
    from app.models.curriculum.topics import Topic

    t = Topic(
        organization_id=org.id,
        subject_id=PydanticObjectId(),
        topic_name="Photosynthesis",
        topic_slug="photosynthesis",
        topic_description=(
            "The process by which green plants convert light energy into chemical "
            "energy stored as glucose, using carbon dioxide and water."
        ),
        key_concepts=[
            "light reaction",
            "dark reaction",
            "chlorophyll",
            "ATP synthesis",
        ],
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2024",
        curriculum_version="v1",
        status="active",
        is_active=True,
    )
    await t.insert()
    return t


@pytest.fixture
async def teacher_topic(db, org, teacher_user):
    """
    TeacherTopic for the institution flow.
    Uses class_id / subject_id strings matching the organisation structure
    defined in the org fixture.
    """
    from app.models.teacher_topic import TeacherTopic

    tt = TeacherTopic(
        organization_id=org.id,
        teacher_id=teacher_user.id,
        class_id="class-10a",
        subject_id="science",
        topic_name="Photosynthesis",
        key_concepts=[
            "light reaction",
            "dark reaction",
            "chlorophyll",
            "ATP synthesis",
        ],
    )
    await tt.insert()
    return tt


@pytest.fixture
async def admin_user(db, org):
    """Platform admin user for catalog curriculum tests."""
    from app.models.identification.users import User

    u = User(
        organization_id=org.id,
        email="admin@testschool.com",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        status="active",
    )
    await u.insert()
    return u


@pytest.fixture
def admin_token(admin_user):
    return create_access_token({"user_id": str(admin_user.id)})


@pytest.fixture
def teacher_token(teacher_user):
    return create_access_token({"user_id": str(teacher_user.id)})


@pytest.fixture
async def catalog_topic(db):
    """Platform catalog topic (organization_id null) for admin curriculum builder."""
    from app.models.curriculum.topics import Topic

    t = Topic(
        organization_id=None,
        subject_id=PydanticObjectId(),
        topic_name="Global Photosynthesis",
        topic_slug="global-photosynthesis",
        topic_description=(
            "Platform catalog topic for structured curriculum Phase 1 tests."
        ),
        key_concepts=[],
        difficulty_level="medium",
        topic_order=1,
        estimated_time=60,
        default_depth="standard",
        academic_year="2024",
        curriculum_version="v1",
        curriculum_schema_version="v1",
        status="active",
        is_active=True,
    )
    await t.insert()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Session fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def session(db, org, topic, student_user):
    """
    A freshly created in-progress session for the test student on the test topic.
    Uses SessionService directly (no HTTP layer) — faster and more reliable.

    The returned Session object starts at:
        flow_state="idle", current_zone=0, zone0_phase="anchoring",
        total_concepts=4, sus_score=50.0
    """
    from app.repositories.session_repository import SessionRepository
    from app.repositories.topic_repository import TopicRepository
    from app.services.session_service import SessionService

    service = SessionService(SessionRepository(), TopicRepository())
    result = await service.start_session(
        student_id=student_user.id,
        topic_id=topic.id,
        student_organization_id=org.id,
    )
    # start_or_resume_session returns Session (first call) or a resume-prompt dict.
    assert not isinstance(result, dict), (
        "Expected a new Session but got a resume prompt — "
        "check that no existing session exists before this fixture."
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HTTP client fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def client(
    db, student_user, student_token
) -> AsyncGenerator[AsyncClient, None]:
    """
    Async test client for the FastAPI app.

    - The `db` fixture is listed first so Beanie is initialised and
      connect_to_mongo is patched BEFORE the lifespan event runs.
    - get_current_user is overridden to return the test student directly,
      bypassing JWT validation in route handlers.
    - The Authorization header is set so any route that reads the header
      directly (not via Depends) also works.
    - dependency_overrides are cleared after each test.
    """
    from app.core.dependencies import get_current_user

    async def _override_auth():
        return student_user

    app.dependency_overrides[get_current_user] = _override_auth

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {student_token}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# DeepSeek response helpers  (re-used across integration tests)
# ─────────────────────────────────────────────────────────────────────────────

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


# ─────────────────────────────────────────────────────────────────────────────
# pytest-httpx: allow real requests to HuggingFace so model-loading retries
# do not block tests for ~23 seconds each.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def non_mocked_hosts() -> list:
    """Allow sentence-transformers to reach HuggingFace without being intercepted."""
    return ["huggingface.co", "cdn-lfs.huggingface.co"]


def deepseek_response(content: str) -> dict:
    """Build a minimal DeepSeek chat-completion JSON payload."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": int(datetime.utcnow().timestamp()),
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
