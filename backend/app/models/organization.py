import logging
import re
import uuid
from typing import Any, List, Literal, Optional, cast

from beanie.odm.fields import PydanticObjectId
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pymongo import IndexModel

from app.models.base import TimestampedDocument

logger = logging.getLogger(__name__)

INVITE_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6,8}$")


class OrgItem(BaseModel):
    id: str
    name: str
    curriculum_subject_id: Optional[PydanticObjectId] = None


class OrgClass(BaseModel):
    id: str
    name: str
    subjects: List[OrgItem] = Field(default_factory=list)


class Organization(TimestampedDocument):
    """Tenant root entity for subscription, capacity, and org-defined class/subject structure."""

    name: str = Field(..., min_length=2, max_length=120)
    contact_email: Optional[EmailStr] = Field(default=None)
    organization_type: Literal["personal", "institution"] = Field(default="personal")
    invite_code: Optional[str] = Field(default=None, min_length=6, max_length=8)
    subscription_plan: Literal["free", "basic", "premium"] = Field(default="free")
    max_students: int = Field(..., ge=0)
    max_teachers: int = Field(..., ge=0)
    status: Literal["active", "suspended"] = Field(default="active")
    owner_user_id: Optional[PydanticObjectId] = None
    classes: List[OrgClass] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_classes_strip_legacy_root_subjects(cls, data: Any) -> Any:
        """
        Single source of truth: classes[].subjects[] only.

        Root-level ``subjects`` is not a model field. If present on a stored document,
        log a warning and drop it from the inbound dict (run ``cleanup_org_subjects.py``
        to merge legacy data into classes and unset the key in MongoDB).
        """
        if not isinstance(data, dict):
            return data
        legacy = data.get("subjects")
        if legacy is not None:
            if isinstance(legacy, list) and len(legacy) > 0:
                logger.warning(
                    "Legacy subjects field detected — should not exist; "
                    "run scripts/cleanup_org_subjects.py. document_id=%s",
                    str(data.get("_id") or data.get("id") or ""),
                )
            data = dict(data)
            data.pop("subjects", None)

        classes_raw = data.get("classes")
        if not isinstance(classes_raw, list):
            classes_raw = []
        normalized: list[dict[str, Any]] = []
        for c in classes_raw:
            if not isinstance(c, dict):
                continue
            subs = c.get("subjects")
            if subs is None or not isinstance(subs, list):
                subs = []
            normalized.append(
                {
                    "id": str(c.get("id", "")),
                    "name": str(c.get("name", "")),
                    "subjects": subs,
                }
            )
        out = dict(data)
        out["classes"] = normalized
        if not out.get("organization_type"):
            nm = str(out.get("name") or "")
            out["organization_type"] = (
                "personal" if nm.endswith("_personal") else "institution"
            )
        return out

    @field_validator("classes", mode="before")
    @classmethod
    def coerce_classes(cls, v: object) -> list[OrgClass]:
        if v is None or not isinstance(v, list):
            return []
        out: list[OrgClass] = []
        for item in v:
            if isinstance(item, OrgClass):
                out.append(item)
            elif isinstance(item, dict):
                subs_raw = item.get("subjects") or []
                subs: list[OrgItem] = []
                if isinstance(subs_raw, list):
                    for s in subs_raw:
                        if isinstance(s, OrgItem):
                            subs.append(s)
                        elif isinstance(s, dict):
                            raw_cs = s.get("curriculum_subject_id")
                            curriculum_subject_id: Optional[PydanticObjectId] = None
                            if raw_cs is not None and str(raw_cs).strip():
                                try:
                                    curriculum_subject_id = PydanticObjectId(
                                        str(raw_cs)
                                    )
                                except Exception:
                                    curriculum_subject_id = None
                            subs.append(
                                OrgItem(
                                    id=str(s.get("id", "")),
                                    name=str(s.get("name", "")),
                                    curriculum_subject_id=curriculum_subject_id,
                                )
                            )
                legacy_name = str(item.get("name", ""))
                legacy_id = str(item.get("id", ""))
                out.append(
                    OrgClass(id=legacy_id, name=legacy_name, subjects=subs)
                )
        return out

    @field_validator("organization_type", mode="before")
    @classmethod
    def coerce_organization_type(cls, v: object) -> Literal["personal", "institution"]:
        if v is None or v == "":
            return "personal"
        s = str(v).strip().lower()
        if s not in ("personal", "institution"):
            raise ValueError("organization_type must be 'personal' or 'institution'")
        return cast(Literal["personal", "institution"], s)

    @field_validator("invite_code")
    @classmethod
    def invite_code_uppercase_alphanumeric(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        normalized = v.strip().upper()
        if not INVITE_CODE_PATTERN.match(normalized):
            raise ValueError(
                "invite_code must be 6-8 characters, uppercase letters and numbers only"
            )
        return normalized

    class Settings:
        name = "organizations"
        indexes = [
            IndexModel([("name", 1)], unique=True),
            IndexModel([("invite_code", 1)], unique=True, sparse=True),
        ]
