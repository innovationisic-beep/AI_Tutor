"""Shared login and /users/me payload shapes."""

from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel, EmailStr, Field

from app.models.identification.users import User
from app.models.organization import Organization


class AuthUserOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    organization_id: Optional[str] = None
    assigned_classes: list[str] = Field(default_factory=list)
    assigned_subjects: list[str] = Field(default_factory=list)


class OrganizationOut(BaseModel):
    id: str
    name: str
    organization_type: str


def build_auth_user_out(user: User) -> AuthUserOut:
    return AuthUserOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        organization_id=str(user.organization_id) if user.organization_id else None,
        assigned_classes=list(user.assigned_classes or []),
        assigned_subjects=list(user.assigned_subjects or []),
    )


async def load_org_context_for_user(user: User) -> Tuple[Optional[OrganizationOut], bool]:
    if user.organization_id is None:
        return None, False
    org = await Organization.get(user.organization_id)
    if org is None:
        return None, False
    out = OrganizationOut(
        id=str(org.id),
        name=org.name,
        organization_type=org.organization_type,
    )
    return out, org.organization_type == "institution"
