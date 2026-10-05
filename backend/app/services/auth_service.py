import secrets
import string
from typing import Literal, Optional, cast

from beanie.odm.fields import PydanticObjectId

from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.identification.organizations import Organization
from app.models.identification.parent_profiles import ParentProfile
from app.models.identification.student_profiles import StudentProfile
from app.models.identification.teachers import Teacher
from app.models.identification.users import User, UserRole
from app.repositories.user_repository import UserRepository

INVITE_CODE_ALPHABET = string.ascii_uppercase + string.digits
INVITE_CODE_LENGTH = 6
INVITE_CODE_MAX_ATTEMPTS = 20

SystemCreatableRole = Literal["admin", "organization", "teacher"]


async def allocate_unique_invite_code() -> str:
    """Generate an upper-case invite code unique across organizations."""
    for _ in range(INVITE_CODE_MAX_ATTEMPTS):
        code = "".join(
            secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH)
        )
        existing = await Organization.find_one({"invite_code": code})
        if existing is None:
            return code
    raise ValueError("Could not generate unique invite code after retries")


class AuthService:
    """Handles user registration, authentication, and JWT generation."""

    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def _insert_student_profile(
        self,
        *,
        organization_id: PydanticObjectId,
        user_id: PydanticObjectId,
        full_name: Optional[str],
        grade: str,
        board: str,
        interests: list[str],
        preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"],
        class_id: Optional[str] = None,
    ) -> None:
        await StudentProfile(
            organization_id=organization_id,
            user_id=user_id,
            full_name=full_name,
            class_id=class_id,
            grade=grade,
            board=board,
            interests=interests,
            preferred_teaching_style=preferred_teaching_style,
            preferred_depth="standard",
            preferred_voice_speed=1.0,
            learning_speed_score=1.0,
            preferred_language="en",
        ).insert()

    async def register_student_individual(
        self,
        *,
        full_name: str,
        email: str,
        password: str,
        grade: str,
        interests: Optional[str],
        preferred_teaching_style: Literal["visual", "practical", "theory", "mixed"],
    ) -> User:
        """Public signup: student in a personal organization with profile preferences."""
        email_normalized = email.strip().lower()
        org_id = await self._get_or_create_personal_organization(email_normalized)
        existing = await self.user_repository.get_by_email(
            email_normalized, organization_id=org_id
        )
        if existing is not None:
            raise ValueError("User with this email already exists in the organization")
        password_hash = hash_password(password)
        user = await self.user_repository.create(
            {
                "organization_id": org_id,
                "email": email_normalized,
                "password_hash": password_hash,
                "role": "student",
            }
        )
        if user.organization_id is None:
            raise ValueError("Organization ID must not be null")
        interest_list = [
            s.strip() for s in (interests or "").split(",") if s.strip()
        ][:50]
        g = (grade or "").strip() or "unknown"
        await self._insert_student_profile(
            organization_id=org_id,
            user_id=user.id,
            full_name=full_name.strip() or None,
            grade=g[:32],
            board="general",
            interests=interest_list,
            preferred_teaching_style=preferred_teaching_style,
            class_id=None,
        )
        return user

    async def register_student_with_invite(
        self,
        *,
        full_name: str,
        email: str,
        password: str,
        invite_code: str,
        class_id: str,
    ) -> User:
        """Public signup: student joins an institution via invite code and class."""
        email_normalized = email.strip().lower()
        code = (invite_code or "").strip().upper()
        if not code:
            raise ValueError("Invite code is required")
        org = await Organization.find_one({"invite_code": code})
        if org is None:
            raise ValueError("Invalid or expired invite code")
        if org.organization_type != "institution":
            raise ValueError("This invite code is not for school enrollment")
        cid = (class_id or "").strip()
        if not cid:
            raise ValueError("Class is required")
        class_row = next((c for c in (org.classes or []) if c.id == cid), None)
        if class_row is None:
            raise ValueError("Class does not belong to this organization")
        if org.id is None:
            raise ValueError("Organization ID must not be null")
        existing = await self.user_repository.get_by_email(
            email_normalized, organization_id=org.id
        )
        if existing is not None:
            raise ValueError("User with this email already exists in the organization")
        password_hash = hash_password(password)
        grade_name = (class_row.name or "unknown").strip() or "unknown"
        user = await self.user_repository.create(
            {
                "organization_id": org.id,
                "email": email_normalized,
                "password_hash": password_hash,
                "role": "student",
                "assigned_classes": [cid],
            }
        )
        await self._insert_student_profile(
            organization_id=org.id,
            user_id=user.id,
            full_name=full_name.strip() or None,
            grade=grade_name[:32],
            board="general",
            interests=[],
            preferred_teaching_style="mixed",
            class_id=cid,
        )
        return user

    async def create_system_user(
        self,
        email: str,
        password: str,
        role: SystemCreatableRole,
    ) -> User:
        """
        Create a non-student user (admin, organization manager, or teacher).
        Admin: no organization_id, no tenant profile.
        Others: personal workspace organization (same pattern as students).
        """
        email_normalized = email.strip().lower()

        if role == "admin":
            existing = await self.user_repository.get_by_email(
                email_normalized, organization_id=None
            )
            if existing is not None:
                raise ValueError("User with this email already exists")
            password_hash = hash_password(password)
            user = await self.user_repository.create(
                {
                    "organization_id": None,
                    "email": email_normalized,
                    "password_hash": password_hash,
                    "role": "admin",
                }
            )
            await self._create_profile_for_user(
                organization_id=None, user_id=user.id, role="admin"
            )
            return user

        org_id = await self._get_or_create_personal_organization(email_normalized)

        existing = await self.user_repository.get_by_email(
            email_normalized, organization_id=org_id
        )
        if existing is not None:
            raise ValueError("User with this email already exists in the organization")

        password_hash = hash_password(password)
        user = await self.user_repository.create(
            {
                "organization_id": org_id,
                "email": email_normalized,
                "password_hash": password_hash,
                "role": cast(UserRole, role),
            }
        )
        if user.organization_id is None:
            raise ValueError("Organization ID must not be null")

        await self._create_profile_for_user(
            organization_id=org_id, user_id=user.id, role=cast(UserRole, role)
        )
        if role == "organization":
            org_doc = await Organization.get(org_id)
            if org_doc is not None:
                org_doc.owner_user_id = user.id
                await org_doc.save()
        return user

    async def create_teacher_in_organization(
        self,
        organization_id: PydanticObjectId,
        email: str,
        password: str,
        assigned_classes: list[str],
        assigned_subjects: list[str],
    ) -> User:
        """Create a teacher user in the given tenant organization (org admin only at route layer)."""
        email_normalized = email.strip().lower()
        existing = await self.user_repository.get_by_email(
            email_normalized, organization_id=organization_id
        )
        if existing is not None:
            raise ValueError("User with this email already exists in the organization")
        password_hash = hash_password(password)
        user = await self.user_repository.create(
            {
                "organization_id": organization_id,
                "email": email_normalized,
                "password_hash": password_hash,
                "role": "teacher",
                "assigned_classes": list(assigned_classes),
                "assigned_subjects": list(assigned_subjects),
            }
        )
        if user.organization_id is None:
            raise ValueError("Organization ID must not be null")
        await self._create_profile_for_user(
            organization_id=organization_id,
            user_id=user.id,
            role="teacher",
        )
        return user

    async def _create_profile_for_user(
        self,
        organization_id: Optional[PydanticObjectId],
        user_id: PydanticObjectId,
        role: UserRole,
    ) -> None:
        """Create role-specific profile documents for new users only (teacher → Teacher, etc.)."""
        if role == "student":
            if organization_id is None:
                raise ValueError("Organization ID must not be null for student")
            await StudentProfile(
                organization_id=organization_id,
                user_id=user_id,
                full_name=None,
                class_id=None,
                grade="unknown",
                board="unknown",
                preferred_teaching_style="mixed",
                preferred_depth="standard",
                preferred_voice_speed=1.0,
                learning_speed_score=1.0,
                preferred_language="en",
            ).insert()
        elif role == "teacher":
            if organization_id is None:
                raise ValueError("Organization ID must not be null for teacher")
            await Teacher(
                organization_id=organization_id,
                user_id=user_id,
            ).insert()
        elif role == "parent":
            if organization_id is None:
                raise ValueError("Organization ID must not be null for parent")
            await ParentProfile(
                organization_id=organization_id,
                user_id=user_id,
                phone_number=None,
                occupation=None,
            ).insert()
        # admin, organization: no separate profile document

    async def _get_or_create_personal_organization(self, email: str) -> PydanticObjectId:
        """Get or create the personal workspace organization for an individual account. Name is unique per email."""
        name = f"{email}_personal"[:120]
        org = await Organization.find_one({"name": name})
        if org is not None:
            if org.id is None:
                raise ValueError("Organization ID must not be null")
            return org.id
        invite_code = await allocate_unique_invite_code()
        new_org = await Organization(
            name=name,
            invite_code=invite_code,
            subscription_plan="free",
            max_students=1,
            max_teachers=0,
            status="active",
            organization_type="personal",
        ).insert()
        if new_org.id is None:
            raise ValueError("Organization ID must not be null")
        return new_org.id

    async def authenticate_user(
        self,
        email: str,
        password: str,
    ) -> Optional[User]:
        """Find user by email, verify password. Returns user if valid, else None."""
        user = await self.user_repository.get_by_email(email.strip().lower())
        if user is None:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def generate_token(self, user: User) -> str:
        """Build JWT payload from user and return access token."""
        payload = {
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role,
        }
        return create_access_token(
            payload,
            expires_minutes=Settings().ACCESS_TOKEN_EXPIRE_MINUTES,
        )
