import uuid
from typing import Optional

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.models.curriculum.subjects import Subject
from app.models.identification.users import User
from app.models.organization import OrgClass, OrgItem, Organization


class OrganizationStructureService:
    """
    Mutate org structure using **classes[].subjects[] only**.

    There is no root-level ``Organization.subjects``; never read or write it.
    """

    @staticmethod
    async def assert_curriculum_subject_in_org(
        curriculum_subject_id: PydanticObjectId,
        organization_id: PydanticObjectId,
    ) -> None:
        row = await Subject.get(curriculum_subject_id)
        if row is None:
            raise HTTPException(
                status_code=404, detail="Curriculum subject not found"
            )
        if (
            row.organization_id is not None
            and row.organization_id != organization_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Curriculum subject is not in your organization",
            )

    @staticmethod
    async def get_organization(org_id: PydanticObjectId) -> Organization | None:
        return await Organization.get(org_id)

    @staticmethod
    async def add_class(org: Organization, name: str) -> OrgClass:
        trimmed = name.strip()
        if len(trimmed) < 1:
            raise ValueError("name is required")
        if any(c.name.lower() == trimmed.lower() for c in (org.classes or [])):
            raise HTTPException(status_code=400, detail="Class already exists")
        item = OrgClass(id=str(uuid.uuid4()), name=trimmed, subjects=[])
        org.classes = list(org.classes or []) + [item]
        org.classes.sort(key=lambda x: x.name)
        await org.save()
        return item

    @staticmethod
    async def add_subject_to_class(
        org: Organization,
        class_id: str,
        name: str,
        curriculum_subject_id: Optional[PydanticObjectId] = None,
    ) -> OrgItem:
        trimmed = name.strip()
        if len(trimmed) < 1:
            raise ValueError("name is required")
        if curriculum_subject_id is not None:
            await OrganizationStructureService.assert_curriculum_subject_in_org(
                curriculum_subject_id, org.id
            )
        classes = list(org.classes or [])
        idx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        cls_row = classes[idx]
        subs = list(cls_row.subjects or [])
        key = trimmed.lower()
        if any(s.name.strip().lower() == key for s in subs):
            raise HTTPException(
                status_code=400, detail="Subject already exists in this class"
            )
        item = OrgItem(
            id=str(uuid.uuid4()),
            name=trimmed,
            curriculum_subject_id=curriculum_subject_id,
        )
        subs.append(item)
        subs.sort(key=lambda x: x.name)
        classes[idx] = OrgClass(id=cls_row.id, name=cls_row.name, subjects=subs)
        org.classes = classes
        await org.save()
        return item

    @staticmethod
    async def link_class_subject_to_curriculum(
        org: Organization,
        class_id: str,
        subject_id: str,
        curriculum_subject_id: Optional[PydanticObjectId],
    ) -> OrgItem:
        classes = list(org.classes or [])
        idx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        cls_row = classes[idx]
        subs = list(cls_row.subjects or [])
        sidx = next((i for i, s in enumerate(subs) if s.id == subject_id), None)
        if sidx is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        if curriculum_subject_id is not None:
            await OrganizationStructureService.assert_curriculum_subject_in_org(
                curriculum_subject_id, org.id
            )
        old = subs[sidx]
        subs[sidx] = OrgItem(
            id=old.id,
            name=old.name,
            curriculum_subject_id=curriculum_subject_id,
        )
        subs.sort(key=lambda x: x.name)
        classes[idx] = OrgClass(id=cls_row.id, name=cls_row.name, subjects=subs)
        org.classes = classes
        await org.save()
        return subs[sidx]

    @staticmethod
    def validate_assignments(
        org: Organization,
        assigned_classes: list[str],
        assigned_subjects: list[str],
    ) -> None:
        valid_class_ids = {c.id for c in (org.classes or [])}
        valid_subject_ids: set[str] = set()
        for c in org.classes or []:
            for s in c.subjects or []:
                valid_subject_ids.add(s.id)
        for cid in assigned_classes:
            if cid not in valid_class_ids:
                raise HTTPException(status_code=400, detail=f"Invalid class id: {cid}")
        for sid in assigned_subjects:
            if sid not in valid_subject_ids:
                raise HTTPException(
                    status_code=400, detail=f"Invalid subject id: {sid}"
                )

    @staticmethod
    async def subject_assigned_to_teacher(
        organization_id: PydanticObjectId,
        subject_id: str,
    ) -> bool:
        sid = (subject_id or "").strip()
        if not sid:
            return False
        teachers = await User.find(
            {"organization_id": organization_id, "role": "teacher"}
        ).to_list()
        for u in teachers:
            if sid in (u.assigned_subjects or []):
                return True
        return False

    @staticmethod
    async def _strip_class_from_teachers(
        organization_id: PydanticObjectId,
        class_id: str,
        subject_ids_to_remove: set[str],
    ) -> None:
        """Remove class from assigned_classes and drop subjects that belonged to it."""
        cid = (class_id or "").strip()
        teachers = await User.find(
            {"organization_id": organization_id, "role": "teacher"}
        ).to_list()
        for u in teachers:
            new_classes = [c for c in (u.assigned_classes or []) if c != cid]
            new_subs = [
                s
                for s in (u.assigned_subjects or [])
                if s not in subject_ids_to_remove
            ]
            if new_classes != list(u.assigned_classes or []) or new_subs != list(
                u.assigned_subjects or []
            ):
                u.assigned_classes = new_classes
                u.assigned_subjects = new_subs
                await u.save()

    @staticmethod
    async def _remove_subject_from_teacher_assignments(
        organization_id: PydanticObjectId,
        subject_id: str,
    ) -> None:
        sid = (subject_id or "").strip()
        if not sid:
            return
        teachers = await User.find(
            {"organization_id": organization_id, "role": "teacher"}
        ).to_list()
        for u in teachers:
            new_subs = [s for s in (u.assigned_subjects or []) if s != sid]
            if new_subs != list(u.assigned_subjects or []):
                u.assigned_subjects = new_subs
                await u.save()

    @staticmethod
    async def rename_class(org: Organization, class_id: str, name: str) -> OrgClass:
        trimmed = name.strip()
        if len(trimmed) < 1:
            raise HTTPException(status_code=400, detail="name is required")
        classes = list(org.classes or [])
        idx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        if any(
            i != idx and c.name.strip().lower() == trimmed.lower()
            for i, c in enumerate(classes)
        ):
            raise HTTPException(status_code=400, detail="Another class already has this name")
        row = classes[idx]
        updated = OrgClass(
            id=row.id, name=trimmed, subjects=list(row.subjects or [])
        )
        classes[idx] = updated
        org.classes = classes
        org.classes.sort(key=lambda x: x.name)
        await org.save()
        return updated

    @staticmethod
    async def delete_class(
        org: Organization, class_id: str, *, force: bool = False
    ) -> None:
        classes = list(org.classes or [])
        idx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        cls_row = classes[idx]
        subs = list(cls_row.subjects or [])
        if len(subs) > 0 and not force:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Class has subjects. Remove subjects first, or delete with "
                    "force=true to remove the class and all its subjects."
                ),
            )
        subject_ids = {s.id for s in subs}
        classes.pop(idx)
        org.classes = classes
        await org.save()
        await OrganizationStructureService._strip_class_from_teachers(
            org.id, class_id, subject_ids
        )

    @staticmethod
    async def rename_subject_in_class(
        org: Organization,
        class_id: str,
        subject_id: str,
        name: str,
    ) -> OrgItem:
        trimmed = name.strip()
        if len(trimmed) < 1:
            raise HTTPException(status_code=400, detail="name is required")
        classes = list(org.classes or [])
        cidx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if cidx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        cls_row = classes[cidx]
        subs = list(cls_row.subjects or [])
        sidx = next((i for i, s in enumerate(subs) if s.id == subject_id), None)
        if sidx is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        key = trimmed.lower()
        if any(
            i != sidx and s.name.strip().lower() == key for i, s in enumerate(subs)
        ):
            raise HTTPException(
                status_code=400, detail="Another subject in this class already has this name"
            )
        old = subs[sidx]
        renamed = OrgItem(
            id=old.id,
            name=trimmed,
            curriculum_subject_id=old.curriculum_subject_id,
        )
        subs[sidx] = renamed
        subs.sort(key=lambda x: x.name)
        classes[cidx] = OrgClass(
            id=cls_row.id, name=cls_row.name, subjects=subs
        )
        org.classes = classes
        await org.save()
        return renamed

    @staticmethod
    async def delete_subject_from_class(
        org: Organization,
        class_id: str,
        subject_id: str,
    ) -> None:
        if await OrganizationStructureService.subject_assigned_to_teacher(
            org.id, subject_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot delete subject: it is assigned to one or more teachers",
            )
        classes = list(org.classes or [])
        cidx = next((i for i, c in enumerate(classes) if c.id == class_id), None)
        if cidx is None:
            raise HTTPException(status_code=404, detail="Class not found")
        cls_row = classes[cidx]
        subs = list(cls_row.subjects or [])
        sidx = next((i for i, s in enumerate(subs) if s.id == subject_id), None)
        if sidx is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        subs.pop(sidx)
        classes[cidx] = OrgClass(
            id=cls_row.id, name=cls_row.name, subjects=subs
        )
        org.classes = classes
        await org.save()
        await OrganizationStructureService._remove_subject_from_teacher_assignments(
            org.id, subject_id
        )
