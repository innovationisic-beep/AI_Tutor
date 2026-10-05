"""Create/list/delete learning graph edges with multi-tenant rules."""

from __future__ import annotations

from typing import List, Literal, Optional, Tuple

from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException, status

from app.models.curriculum.prerequisite_graph import PrerequisiteGraph
from app.models.curriculum.topic_progression_map import TopicProgressionMap
from app.models.curriculum.topics import Topic
from app.models.teacher_topic import TeacherTopic


NodeKind = Literal["global_topic", "tenant_topic", "teacher_topic"]


def parse_topic_oid(value: str, field_name: str) -> PydanticObjectId:
    try:
        return PydanticObjectId(value.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}",
        ) from exc


async def resolve_graph_node(
    oid: PydanticObjectId,
) -> Tuple[object, NodeKind]:
    t = await Topic.get(oid)
    if t is not None:
        if t.organization_id is None:
            return t, "global_topic"
        return t, "tenant_topic"
    tt = await TeacherTopic.get(oid)
    if tt is not None:
        return tt, "teacher_topic"
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Topic not found",
    )


def effective_organization_id(node_kind: NodeKind, doc: object) -> Optional[PydanticObjectId]:
    return getattr(doc, "organization_id", None)


async def assert_admin_global_pair(
    topic_id: PydanticObjectId,
    other_id: PydanticObjectId,
) -> None:
    """Both endpoints must be global catalog ``Topic`` (organization_id null)."""
    _, ka = await resolve_graph_node(topic_id)
    _, kb = await resolve_graph_node(other_id)
    if ka != "global_topic" or kb != "global_topic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin graph may only link global catalog topics",
        )


async def assert_teacher_org_pair(
    topic_id: PydanticObjectId,
    other_id: PydanticObjectId,
    user_org_id: PydanticObjectId,
) -> None:
    """Both endpoints must belong to the same tenant (non-null org matching user)."""
    a, ka = await resolve_graph_node(topic_id)
    b, kb = await resolve_graph_node(other_id)
    oa = effective_organization_id(ka, a)
    ob = effective_organization_id(kb, b)
    if oa is None or ob is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot link platform catalog topics in the teacher graph",
        )
    if oa != user_org_id or ob != user_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both topics must belong to your organization",
        )


def _prereq_to_out(row: PrerequisiteGraph) -> dict:
    return {
        "id": str(row.id),
        "topic_id": str(row.topic_id),
        "prerequisite_topic_id": str(row.prerequisite_topic_id),
    }


def _prog_to_out(row: TopicProgressionMap) -> dict:
    return {
        "id": str(row.id),
        "topic_id": str(row.topic_id),
        "recommended_next_topic_id": str(row.recommended_next_topic_id),
        "minimum_mastery_to_recommend": int(
            round(float(row.minimum_mastery_to_recommend))
        ),
    }


async def create_prerequisite_edge(
    *,
    topic_id: PydanticObjectId,
    prerequisite_topic_id: PydanticObjectId,
    organization_id: Optional[PydanticObjectId],
    mode: Literal["admin", "teacher"],
    user_org_id: Optional[PydanticObjectId],
) -> PrerequisiteGraph:
    if topic_id == prerequisite_topic_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A topic cannot be its own prerequisite",
        )
    if mode == "admin":
        await assert_admin_global_pair(topic_id, prerequisite_topic_id)
        org_for_row: Optional[PydanticObjectId] = None
    else:
        if user_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no organization",
            )
        await assert_teacher_org_pair(
            topic_id, prerequisite_topic_id, user_org_id
        )
        org_for_row = user_org_id

    existing = await PrerequisiteGraph.find_one(
        {
            "topic_id": topic_id,
            "prerequisite_topic_id": prerequisite_topic_id,
            "organization_id": org_for_row,
        }
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This prerequisite edge already exists",
        )

    row = PrerequisiteGraph(
        organization_id=org_for_row,
        topic_id=topic_id,
        prerequisite_topic_id=prerequisite_topic_id,
    )
    await row.insert()
    return row


async def create_progression_edge(
    *,
    topic_id: PydanticObjectId,
    recommended_next_topic_id: PydanticObjectId,
    minimum_mastery: float,
    organization_id: Optional[PydanticObjectId],
    mode: Literal["admin", "teacher"],
    user_org_id: Optional[PydanticObjectId],
) -> TopicProgressionMap:
    if topic_id == recommended_next_topic_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A topic cannot recommend itself as the next topic",
        )
    if mode == "admin":
        await assert_admin_global_pair(topic_id, recommended_next_topic_id)
        org_for_row = None
    else:
        if user_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no organization",
            )
        await assert_teacher_org_pair(
            topic_id, recommended_next_topic_id, user_org_id
        )
        org_for_row = user_org_id

    existing = await TopicProgressionMap.find_one(
        {
            "topic_id": topic_id,
            "recommended_next_topic_id": recommended_next_topic_id,
            "organization_id": org_for_row,
        }
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This progression edge already exists",
        )

    row = TopicProgressionMap(
        organization_id=org_for_row,
        topic_id=topic_id,
        recommended_next_topic_id=recommended_next_topic_id,
        minimum_mastery_to_recommend=min(100.0, max(0.0, minimum_mastery)),
    )
    await row.insert()
    return row


async def list_prerequisites_admin(topic_id: PydanticObjectId) -> List[dict]:
    rows = await PrerequisiteGraph.find(
        {"topic_id": topic_id, "organization_id": None}
    ).to_list()
    return [_prereq_to_out(r) for r in rows]


async def list_progression_admin(topic_id: PydanticObjectId) -> List[dict]:
    rows = await TopicProgressionMap.find(
        {"topic_id": topic_id, "organization_id": None}
    ).to_list()
    return [_prog_to_out(r) for r in rows]


async def list_prerequisites_teacher_with_fallback(
    topic_id: PydanticObjectId,
    user_org_id: PydanticObjectId,
) -> List[dict]:
    rows = await PrerequisiteGraph.find(
        {"topic_id": topic_id, "organization_id": user_org_id}
    ).to_list()
    if rows:
        return [_prereq_to_out(r) for r in rows]
    rows = await PrerequisiteGraph.find(
        {"topic_id": topic_id, "organization_id": None}
    ).to_list()
    return [_prereq_to_out(r) for r in rows]


async def list_progression_teacher_with_fallback(
    topic_id: PydanticObjectId,
    user_org_id: PydanticObjectId,
) -> List[dict]:
    rows = await TopicProgressionMap.find(
        {"topic_id": topic_id, "organization_id": user_org_id}
    ).to_list()
    if rows:
        return [_prog_to_out(r) for r in rows]
    rows = await TopicProgressionMap.find(
        {"topic_id": topic_id, "organization_id": None}
    ).to_list()
    return [_prog_to_out(r) for r in rows]


async def delete_prerequisite_admin(edge_id: PydanticObjectId) -> None:
    row = await PrerequisiteGraph.get(edge_id)
    if row is None or row.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prerequisite edge not found",
        )
    await row.delete()


async def delete_progression_admin(edge_id: PydanticObjectId) -> None:
    row = await TopicProgressionMap.get(edge_id)
    if row is None or row.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Progression edge not found",
        )
    await row.delete()


async def delete_prerequisite_teacher(
    edge_id: PydanticObjectId,
    user_org_id: PydanticObjectId,
) -> None:
    row = await PrerequisiteGraph.get(edge_id)
    if row is None or row.organization_id != user_org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prerequisite edge not found",
        )
    await row.delete()


async def delete_progression_teacher(
    edge_id: PydanticObjectId,
    user_org_id: PydanticObjectId,
) -> None:
    row = await TopicProgressionMap.get(edge_id)
    if row is None or row.organization_id != user_org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Progression edge not found",
        )
    await row.delete()
