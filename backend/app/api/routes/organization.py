from typing import List, Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.dependencies import (
    get_current_for_org_structure_read,
    get_current_organization,
)
from app.models.identification.teachers import Teacher
from app.models.identification.users import User
from app.models.organization import OrgItem, Organization
from app.repositories.user_repository import UserRepository, get_user_repository
from app.services.auth_service import AuthService
from app.services.organization_structure_service import OrganizationStructureService

router = APIRouter(prefix="/org", tags=["Organization"])


class InviteClassBrief(BaseModel):
    id: str
    name: str


class OrgByInviteOut(BaseModel):
    organization_name: str
    classes: List[InviteClassBrief]


@router.get("/by-invite/{invite_code}", response_model=OrgByInviteOut)
async def get_organization_by_invite(invite_code: str) -> OrgByInviteOut:
    """
    Public lookup for school signup: resolve institution and class list from invite code.
    Personal workspaces use invite codes for internal join — those are rejected here.
    """
    raw = (invite_code or "").strip().upper()
    if not raw:
        raise HTTPException(status_code=400, detail="Invite code is required")
    org = await Organization.find_one({"invite_code": raw})
    if org is None:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    if org.organization_type != "institution":
        raise HTTPException(
            status_code=400,
            detail="This invite code is not for school enrollment",
        )
    classes = list(org.classes or [])
    classes.sort(key=lambda x: x.name)
    return OrgByInviteOut(
        organization_name=org.name,
        classes=[
            InviteClassBrief(id=str(c.id), name=str(c.name or "")) for c in classes
        ],
    )


class AddNamedBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class AddSubjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    curriculum_subject_id: Optional[str] = None

    @field_validator("curriculum_subject_id")
    @classmethod
    def validate_cs(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        s = str(v).strip()
        if len(s) != 24:
            raise ValueError(
                "curriculum_subject_id must be a 24-character ObjectId string"
            )
        return s


class LinkOrgSubjectCurriculumBody(BaseModel):
    curriculum_subject_id: Optional[str] = None

    @field_validator("curriculum_subject_id")
    @classmethod
    def validate_cs(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        s = str(v).strip()
        if len(s) != 24:
            raise ValueError(
                "curriculum_subject_id must be a 24-character ObjectId string"
            )
        return s


class CreateTeacherBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    assigned_classes: List[str] = Field(default_factory=list)
    assigned_subjects: List[str] = Field(default_factory=list)


class AssignTeacherBody(BaseModel):
    user_id: str = Field(..., min_length=24, max_length=24)
    assigned_classes: List[str] = Field(default_factory=list)
    assigned_subjects: List[str] = Field(default_factory=list)


class UpdateSubjectNameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class OrgTeacherOut(BaseModel):
    id: str
    email: str
    assigned_classes: List[str]
    assigned_subjects: List[str]


class UpdateTeacherBody(BaseModel):
    email: EmailStr
    assigned_classes: List[str] = Field(default_factory=list)
    assigned_subjects: List[str] = Field(default_factory=list)


class OrgClassOut(BaseModel):
    id: str
    name: str
    subjects: List[OrgItem]


class StructureResponse(BaseModel):
    classes: List[OrgClassOut]


def build_structure_response(org: Organization) -> StructureResponse:
    """Serialize org for GET /org/structure; subjects only under each class."""
    classes = list(org.classes or [])
    classes.sort(key=lambda x: x.name)
    out: list[OrgClassOut] = []
    for c in classes:
        subs = list(c.subjects or [])
        subs.sort(key=lambda x: x.name)
        out.append(OrgClassOut(id=c.id, name=c.name, subjects=subs))
    return StructureResponse(classes=out)


class CurriculumLinkResponse(BaseModel):
    success: bool = True
    curriculum_subject_id: Optional[str] = None


@router.post("/class", response_model=OrgClassOut)
async def add_class(
    body: AddNamedBody,
    current: User = Depends(get_current_organization),
) -> OrgClassOut:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        row = await OrganizationStructureService.add_class(org, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OrgClassOut(id=row.id, name=row.name, subjects=list(row.subjects or []))


@router.put("/class/{class_id}", response_model=OrgClassOut)
async def rename_class(
    class_id: str,
    body: AddNamedBody,
    current: User = Depends(get_current_organization),
) -> OrgClassOut:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        row = await OrganizationStructureService.rename_class(org, class_id, body.name)
    except HTTPException:
        raise
    return OrgClassOut(id=row.id, name=row.name, subjects=list(row.subjects or []))


@router.delete("/class/{class_id}")
async def delete_class(
    class_id: str,
    current: User = Depends(get_current_organization),
    force: bool = Query(False, description="Delete class even if it has subjects"),
) -> dict[str, bool]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        await OrganizationStructureService.delete_class(org, class_id, force=force)
    except HTTPException:
        raise
    return {"ok": True}


@router.post("/class/{class_id}/subject", response_model=OrgItem)
async def add_subject_to_class(
    class_id: str,
    body: AddSubjectBody,
    current: User = Depends(get_current_organization),
) -> OrgItem:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    cs: Optional[PydanticObjectId] = None
    if body.curriculum_subject_id:
        try:
            cs = PydanticObjectId(body.curriculum_subject_id)
        except Exception:
            raise HTTPException(
                status_code=400, detail="Invalid curriculum_subject_id"
            ) from None
    try:
        return await OrganizationStructureService.add_subject_to_class(
            org, class_id, body.name, cs
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/class/{class_id}/subject/{subject_id}", response_model=OrgItem)
async def rename_subject(
    class_id: str,
    subject_id: str,
    body: UpdateSubjectNameBody,
    current: User = Depends(get_current_organization),
) -> OrgItem:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        return await OrganizationStructureService.rename_subject_in_class(
            org, class_id, subject_id, body.name
        )
    except HTTPException:
        raise


@router.delete("/class/{class_id}/subject/{subject_id}")
async def delete_subject(
    class_id: str,
    subject_id: str,
    current: User = Depends(get_current_organization),
) -> dict[str, bool]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    try:
        await OrganizationStructureService.delete_subject_from_class(
            org, class_id, subject_id
        )
    except HTTPException:
        raise
    return {"ok": True}


@router.put(
    "/class/{class_id}/subject/{subject_id}/curriculum-link",
    response_model=CurriculumLinkResponse,
)
async def link_org_subject_curriculum(
    class_id: str,
    subject_id: str,
    body: LinkOrgSubjectCurriculumBody,
    current: User = Depends(get_current_organization),
) -> CurriculumLinkResponse:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    cs: Optional[PydanticObjectId] = None
    if body.curriculum_subject_id:
        try:
            cs = PydanticObjectId(body.curriculum_subject_id)
        except Exception:
            raise HTTPException(
                status_code=400, detail="Invalid curriculum_subject_id"
            ) from None
    try:
        item = await OrganizationStructureService.link_class_subject_to_curriculum(
            org, class_id, subject_id, cs
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    out_id: str | None = (
        str(item.curriculum_subject_id) if item.curriculum_subject_id else None
    )
    return CurriculumLinkResponse(
        success=True,
        curriculum_subject_id=out_id,
    )


@router.get("/structure", response_model=StructureResponse)
async def get_structure(
    current: User = Depends(get_current_for_org_structure_read),
) -> StructureResponse:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return build_structure_response(org)


@router.post("/teacher")
async def create_teacher(
    body: CreateTeacherBody,
    current: User = Depends(get_current_organization),
    user_repository: UserRepository = Depends(get_user_repository),
) -> dict[str, str]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    OrganizationStructureService.validate_assignments(
        org, body.assigned_classes, body.assigned_subjects
    )

    auth = AuthService(user_repository)
    try:
        user = await auth.create_teacher_in_organization(
            organization_id=current.organization_id,
            email=body.email,
            password=body.password,
            assigned_classes=body.assigned_classes,
            assigned_subjects=body.assigned_subjects,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"id": str(user.id)}


@router.get("/teachers", response_model=List[OrgTeacherOut])
async def list_org_teachers(
    current: User = Depends(get_current_organization),
    user_repository: UserRepository = Depends(get_user_repository),
) -> List[OrgTeacherOut]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    users = await user_repository.get_users_by_role(
        "teacher", current.organization_id, limit=500
    )
    return [
        OrgTeacherOut(
            id=str(u.id),
            email=str(u.email),
            assigned_classes=list(u.assigned_classes or []),
            assigned_subjects=list(u.assigned_subjects or []),
        )
        for u in users
    ]


@router.put("/teacher/{teacher_id}", response_model=OrgTeacherOut)
async def update_org_teacher(
    teacher_id: str,
    body: UpdateTeacherBody,
    current: User = Depends(get_current_organization),
    user_repository: UserRepository = Depends(get_user_repository),
) -> OrgTeacherOut:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    OrganizationStructureService.validate_assignments(
        org, body.assigned_classes, body.assigned_subjects
    )
    try:
        tid = PydanticObjectId(teacher_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid teacher id") from None
    teacher = await user_repository.get_by_id(tid)
    if teacher is None:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if teacher.organization_id != current.organization_id:
        raise HTTPException(status_code=404, detail="Teacher not in this organization")
    if teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="User is not a teacher")
    email_norm = str(body.email).strip().lower()
    if email_norm != str(teacher.email).strip().lower():
        other = await user_repository.get_by_email(
            email_norm, organization_id=current.organization_id
        )
        if other is not None and other.id != teacher.id:
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists in the organization",
            )
    updated = await user_repository.update(
        teacher.id,
        {
            "email": email_norm,
            "assigned_classes": list(body.assigned_classes),
            "assigned_subjects": list(body.assigned_subjects),
        },
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update teacher")
    return OrgTeacherOut(
        id=str(updated.id),
        email=str(updated.email),
        assigned_classes=list(updated.assigned_classes or []),
        assigned_subjects=list(updated.assigned_subjects or []),
    )


@router.delete("/teacher/{teacher_id}")
async def delete_org_teacher(
    teacher_id: str,
    current: User = Depends(get_current_organization),
    user_repository: UserRepository = Depends(get_user_repository),
) -> dict[str, bool]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    try:
        tid = PydanticObjectId(teacher_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid teacher id") from None
    teacher = await user_repository.get_by_id(tid)
    if teacher is None:
        raise HTTPException(status_code=404, detail="Teacher not found")
    if teacher.organization_id != current.organization_id:
        raise HTTPException(status_code=404, detail="Teacher not in this organization")
    if teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="User is not a teacher")
    profile = await Teacher.find_one(
        {
            "user_id": tid,
            "organization_id": current.organization_id,
        }
    )
    if profile is not None:
        await profile.delete()
    await teacher.delete()
    return {"ok": True}


@router.post("/assign")
async def assign_teacher(
    body: AssignTeacherBody,
    current: User = Depends(get_current_organization),
    user_repository: UserRepository = Depends(get_user_repository),
) -> dict[str, str]:
    if current.organization_id is None:
        raise HTTPException(status_code=400, detail="User has no organization")
    org = await OrganizationStructureService.get_organization(current.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    OrganizationStructureService.validate_assignments(
        org, body.assigned_classes, body.assigned_subjects
    )

    try:
        teacher_oid = PydanticObjectId(body.user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id") from None

    teacher = await user_repository.get_by_id(teacher_oid)
    if teacher is None:
        raise HTTPException(status_code=404, detail="User not found")
    if teacher.organization_id != current.organization_id:
        raise HTTPException(status_code=404, detail="User not found in this organization")
    if teacher.role != "teacher":
        raise HTTPException(status_code=400, detail="User is not a teacher in this organization")

    updated = await user_repository.update(
        teacher.id,
        {
            "assigned_classes": list(body.assigned_classes),
            "assigned_subjects": list(body.assigned_subjects),
        },
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update teacher")
    return {"id": str(updated.id)}
