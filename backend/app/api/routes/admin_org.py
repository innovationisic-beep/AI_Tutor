"""Platform admin: create, list, and manage tenant organizations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from app.core.dependencies import get_current_admin
from app.core.security import hash_password
from app.models.identification.users import User
from app.models.organization import Organization
from app.repositories.user_repository import UserRepository, get_user_repository
from app.services.auth_service import allocate_unique_invite_code

router = APIRouter(prefix="/admin", tags=["Admin organizations"])


class CreateOrganizationBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=6)
    max_students: int = Field(..., ge=1)
    max_teachers: int = Field(..., ge=0)
    subscription_plan: Literal["free", "basic", "premium"] = "free"
    status: Literal["active", "inactive"] = "active"


def _to_db_status(v: Literal["active", "inactive"]) -> Literal["active", "suspended"]:
    return "active" if v == "active" else "suspended"


def _to_api_status(v: str) -> Literal["active", "inactive"]:
    return "active" if v == "active" else "inactive"


class OrganizationCreatedOut(BaseModel):
    id: str
    name: str
    contact_email: str | None = None
    login_email: str
    invite_code: str
    subscription_plan: str
    status: Literal["active", "inactive"]
    max_students: int
    max_teachers: int
    created_at: datetime
    updated_at: datetime


class OrganizationAdminRowOut(BaseModel):
    id: str
    name: str
    contact_email: str | None = None
    subscription_plan: str
    status: Literal["active", "inactive"]
    max_students: int
    max_teachers: int
    invite_code: str | None
    created_at: datetime

    @classmethod
    def from_org(cls, org: Organization) -> OrganizationAdminRowOut:
        ce = org.contact_email
        return cls(
            id=str(org.id),
            name=org.name,
            contact_email=str(ce) if ce is not None else None,
            subscription_plan=org.subscription_plan,
            status=_to_api_status(str(org.status)),
            max_students=org.max_students,
            max_teachers=org.max_teachers,
            invite_code=org.invite_code,
            created_at=org.created_at,
        )


class OrganizationDetailOut(OrganizationAdminRowOut):
    updated_at: datetime
    organization_type: str

    @classmethod
    def from_org(cls, org: Organization) -> OrganizationDetailOut:
        base = OrganizationAdminRowOut.from_org(org)
        return cls(
            **base.model_dump(),
            updated_at=org.updated_at,
            organization_type=org.organization_type,
        )


class PatchOrganizationStatusBody(BaseModel):
    status: Literal["active", "inactive"]


async def _get_institution_org(organization_id: str) -> Organization:
    try:
        oid = PydanticObjectId(organization_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid organization id",
        ) from exc
    org = await Organization.get(oid)
    if org is None or org.organization_type != "institution":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org


@router.post(
    "/organization",
    response_model=OrganizationCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: CreateOrganizationBody,
    _admin: User = Depends(get_current_admin),
    user_repository: UserRepository = Depends(get_user_repository),
) -> OrganizationCreatedOut:
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is too short",
        )
    email_normalized = str(body.email).strip().lower()
    existing_user = await user_repository.get_by_email(
        email_normalized, organization_id=None
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    invite_code = await allocate_unique_invite_code()
    contact = body.email
    org = Organization(
        name=name,
        contact_email=contact,
        invite_code=invite_code,
        classes=[],
        subscription_plan=body.subscription_plan,
        status=_to_db_status(body.status),
        max_students=body.max_students,
        max_teachers=body.max_teachers,
        organization_type="institution",
    )
    try:
        await org.insert()
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An organization with this name already exists",
        ) from None
    if org.id is None or org.invite_code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Organization was not persisted correctly",
        )
    try:
        await user_repository.create(
            {
                "organization_id": org.id,
                "email": email_normalized,
                "password_hash": hash_password(body.password),
                "role": "organization",
                "status": "active",
            }
        )
    except DuplicateKeyError:
        await org.delete()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        ) from None
    except Exception:
        await org.delete()
        raise
    row = OrganizationAdminRowOut.from_org(org)
    return OrganizationCreatedOut(
        id=row.id,
        name=row.name,
        contact_email=row.contact_email,
        login_email=email_normalized,
        invite_code=org.invite_code,
        subscription_plan=row.subscription_plan,
        status=row.status,
        max_students=row.max_students,
        max_teachers=row.max_teachers,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.get("/organizations", response_model=List[OrganizationAdminRowOut])
async def list_organizations(
    _admin: User = Depends(get_current_admin),
) -> List[OrganizationAdminRowOut]:
    docs = (
        await Organization.find({"organization_type": "institution"})
        .sort([("name", 1)])
        .to_list()
    )
    return [OrganizationAdminRowOut.from_org(o) for o in docs]


@router.get(
    "/organization/{organization_id}",
    response_model=OrganizationDetailOut,
)
async def get_organization(
    organization_id: str,
    _admin: User = Depends(get_current_admin),
) -> OrganizationDetailOut:
    org = await _get_institution_org(organization_id)
    return OrganizationDetailOut.from_org(org)


@router.patch(
    "/organization/{organization_id}",
    response_model=OrganizationAdminRowOut,
)
async def patch_organization_status(
    organization_id: str,
    body: PatchOrganizationStatusBody,
    _admin: User = Depends(get_current_admin),
) -> OrganizationAdminRowOut:
    org = await _get_institution_org(organization_id)
    org.status = _to_db_status(body.status)
    await org.save()
    return OrganizationAdminRowOut.from_org(org)
