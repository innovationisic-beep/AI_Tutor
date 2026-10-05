"""CRUD APIs for curriculum zones, clusters, and concepts (Phase 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from beanie.odm.fields import PydanticObjectId
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.api.schemas.curriculum_structure import (
    CreateCurriculumClusterRequest,
    CreateCurriculumConceptRequest,
    CreateCurriculumZoneRequest,
    ConceptUsageOut,
    MoveCurriculumConceptRequest,
    PreviewTeachingOrderRequest,
    UpdateCurriculumClusterRequest,
    UpdateCurriculumConceptRequest,
    UpdateCurriculumZoneRequest,
    cluster_to_out,
    concept_to_out,
    zone_to_out,
)
from app.core.dependencies import get_current_teacher_or_admin, get_current_user
from app.models.identification.users import User
from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
from app.services.curriculum.concept_teaching_sequence import (
    dedupe_asset_key,
    normalize_asset_key,
    normalize_story_hook,
)
from app.services.storage.story_hook_storage import (
    ALLOWED_IMAGE_MIME_TYPES,
    MAX_IMAGE_BYTES,
    get_story_hook_storage,
)
from app.services.storage import visual_teaching_storage as vt_storage
from app.services.visual_teaching.authored import (
    content_hash_bytes,
    normalize_visual_teaching,
)
from app.services.curriculum.curriculum_cluster_service import CurriculumClusterService
from app.services.curriculum.curriculum_concept_service import CurriculumConceptService
from app.services.curriculum.curriculum_zone_service import CurriculumZoneService
from app.services.curriculum.concept_usage_service import ConceptUsageService
from app.services.curriculum.topic_context_service import resolve_topic_context

router = APIRouter(prefix="/curriculum", tags=["Curriculum structure"])


def _oid(value: str, *, label: str = "id") -> PydanticObjectId:
    try:
        return PydanticObjectId(value.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label}",
        ) from exc


@router.post("/zones", status_code=status.HTTP_201_CREATED)
async def create_curriculum_zone(
    body: CreateCurriculumZoneRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    ctx = await resolve_topic_context(
        _oid(body.topic_id, label="topic_id"),
        body.topic_source,
        current_user,
    )
    zone = await CurriculumZoneService().create(
        ctx,
        zone_number=body.zone_number,
        title=body.title,
        description=body.description,
        sort_order=body.sort_order,
    )
    return zone_to_out(zone).model_dump()


@router.get("/zones/{zone_id}")
async def get_curriculum_zone(
    zone_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    zid = _oid(zone_id, label="zone_id")
    zone = await CurriculumZoneService().get(zid, await _ctx_for_zone(zid, topic_source, current_user))
    return zone_to_out(zone).model_dump()


async def _ctx_for_zone(
    zone_id: PydanticObjectId,
    topic_source: str,
    user: User,
):
    from app.repositories.curriculum_zone_repository import CurriculumZoneRepository

    zone = await CurriculumZoneRepository().get_by_id(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Curriculum zone not found")
    return await resolve_topic_context(zone.topic_id, topic_source, user)


@router.put("/zones/{zone_id}")
async def update_curriculum_zone(
    zone_id: str,
    body: UpdateCurriculumZoneRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    zid = _oid(zone_id, label="zone_id")
    ctx = await _ctx_for_zone(zid, body.topic_source, current_user)
    zone = await CurriculumZoneService().update(
        zid,
        ctx,
        title=body.title,
        description=body.description,
        sort_order=body.sort_order,
    )
    return zone_to_out(zone).model_dump()


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_curriculum_zone(
    zone_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    zid = _oid(zone_id, label="zone_id")
    ctx = await _ctx_for_zone(zid, topic_source, current_user)
    await CurriculumZoneService().delete(zid, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/clusters", status_code=status.HTTP_201_CREATED)
async def create_curriculum_cluster(
    body: CreateCurriculumClusterRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    ctx = await resolve_topic_context(
        _oid(body.topic_id, label="topic_id"),
        body.topic_source,
        current_user,
    )
    cluster = await CurriculumClusterService().create(
        ctx,
        curriculum_zone_id=_oid(body.curriculum_zone_id, label="curriculum_zone_id"),
        title=body.title,
        cluster_number=body.cluster_number,
        sort_order=body.sort_order,
        estimated_learning_minutes=body.estimated_learning_minutes,
    )
    return cluster_to_out(cluster).model_dump()


async def _ctx_for_cluster(
    cluster_id: PydanticObjectId,
    topic_source: str,
    user: User,
):
    from app.repositories.curriculum_cluster_repository import CurriculumClusterRepository

    cluster = await CurriculumClusterRepository().get_by_id(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Curriculum cluster not found")
    return await resolve_topic_context(cluster.topic_id, topic_source, user)


@router.get("/clusters/{cluster_id}")
async def get_curriculum_cluster(
    cluster_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(cluster_id, label="cluster_id")
    ctx = await _ctx_for_cluster(cid, topic_source, current_user)
    cluster = await CurriculumClusterService().get(cid, ctx)
    return cluster_to_out(cluster).model_dump()


@router.put("/clusters/{cluster_id}")
async def update_curriculum_cluster(
    cluster_id: str,
    body: UpdateCurriculumClusterRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    cid = _oid(cluster_id, label="cluster_id")
    ctx = await _ctx_for_cluster(cid, body.topic_source, current_user)
    cluster = await CurriculumClusterService().update(
        cid,
        ctx,
        title=body.title,
        description=body.description,
        study_points=body.study_points,
        learning_outcomes=body.learning_outcomes,
        sort_order=body.sort_order,
        estimated_learning_minutes=body.estimated_learning_minutes,
    )
    return cluster_to_out(cluster).model_dump()


@router.delete("/clusters/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_curriculum_cluster(
    cluster_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(cluster_id, label="cluster_id")
    ctx = await _ctx_for_cluster(cid, topic_source, current_user)
    await CurriculumClusterService().delete(cid, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/concepts", status_code=status.HTTP_201_CREATED)
async def create_curriculum_concept(
    body: CreateCurriculumConceptRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    ctx = await resolve_topic_context(
        _oid(body.topic_id, label="topic_id"),
        body.topic_source,
        current_user,
    )
    concept = await CurriculumConceptService().create(
        ctx,
        curriculum_cluster_id=_oid(body.curriculum_cluster_id, label="curriculum_cluster_id"),
        display_name=body.display_name,
        slug=body.slug,
        sort_order=body.sort_order,
        difficulty_level=body.difficulty_level,
        estimated_learning_minutes=body.estimated_learning_minutes,
        study_points=body.study_points,
        learning_outcomes=body.learning_outcomes,
        story_hook=body.story_hook,
        visual_teaching=body.visual_teaching,
        teaching_sequence=body.teaching_sequence,
        teaching_sequence_mode=body.teaching_sequence_mode,
        vtse_template=body.vtse_template,
        vtse_visuals=body.vtse_visuals,
        legacy_concept_key=body.legacy_concept_key,
        canonical_runtime_key=body.canonical_runtime_key,
    )
    return concept_to_out(concept).model_dump()


async def _ctx_for_concept(
    concept_id: PydanticObjectId,
    topic_source: str,
    user: User,
):
    from app.repositories.curriculum_concept_repository import CurriculumConceptRepository

    concept = await CurriculumConceptRepository().get_by_id(concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="Curriculum concept not found")
    return await resolve_topic_context(concept.topic_id, topic_source, user)


@router.get("/concepts/{concept_id}")
async def get_curriculum_concept(
    concept_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    concept = await CurriculumConceptService().get(cid, ctx)
    return concept_to_out(concept).model_dump()


@router.put("/concepts/{concept_id}")
async def update_curriculum_concept(
    concept_id: str,
    body: UpdateCurriculumConceptRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, body.topic_source, current_user)
    concept = await CurriculumConceptService().update(
        cid,
        ctx,
        display_name=body.display_name,
        sort_order=body.sort_order,
        difficulty_level=body.difficulty_level,
        estimated_learning_minutes=body.estimated_learning_minutes,
        study_points=body.study_points,
        learning_outcomes=body.learning_outcomes,
        story_hook=body.story_hook,
        visual_teaching=body.visual_teaching,
        teaching_sequence=body.teaching_sequence,
        teaching_sequence_mode=body.teaching_sequence_mode,
        vtse_template=body.vtse_template,
        vtse_visuals=body.vtse_visuals,
        canonical_runtime_key=body.canonical_runtime_key,
    )
    return concept_to_out(concept).model_dump()


@router.post("/concepts/{concept_id}/teaching-order/preview")
async def preview_teaching_order(
    concept_id: str,
    body: PreviewTeachingOrderRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, body.topic_source, current_user)
    concept = await CurriculumConceptService().get(cid, ctx)
    mode = str(getattr(concept, "teaching_sequence_mode", None) or "manual").strip().lower()
    if mode != "auto":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TEACHING_SEQUENCE_MODE_MANUAL",
                "message": "Save Teaching order as Auto before previewing.",
            },
        )
    from app.services.pedagogy.stage_order_planner import resolve_auto_teaching_order

    await resolve_auto_teaching_order(concept, regenerate=bool(body.regenerate))
    await concept.save()
    return concept_to_out(concept).model_dump()


@router.post("/concepts/{concept_id}/move")
async def move_curriculum_concept(
    concept_id: str,
    body: MoveCurriculumConceptRequest,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    """Move or reorder a structured v2 concept within the same zone."""
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, body.topic_source, current_user)
    concept = await CurriculumConceptService().move(
        cid,
        ctx,
        target_cluster_id=_oid(body.target_cluster_id, label="target_cluster_id"),
        target_index=body.target_index,
    )
    return concept_to_out(concept).model_dump()


@router.get("/concepts/{concept_id}/usage", response_model=ConceptUsageOut)
async def get_curriculum_concept_usage(
    concept_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    return await ConceptUsageService().get_usage(ctx, cid)


@router.post(
    "/concepts/{concept_id}/story-hook/visuals",
    status_code=status.HTTP_201_CREATED,
)
async def upload_story_hook_visual(
    concept_id: str,
    topic_source: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    """
    Upload one Story Hook image and return its metadata draft.

    The binary is committed to storage immediately; the returned
    ``storage_key`` becomes durable only when the caller saves the concept with
    the visual attached. Uncommitted keys are swept by
    ``story_hook_visual_gc``.
    """
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    concept = await CurriculumConceptService().get(cid, ctx)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_IMAGE_TYPE",
                "message": (
                    "Story Hook visuals must be JPEG, PNG or WebP images "
                    f"(received '{content_type or 'unknown'}')."
                ),
            },
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_IMAGE", "message": "Uploaded image is empty"},
        )
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "IMAGE_TOO_LARGE",
                "message": (
                    f"Story Hook visuals must be {MAX_IMAGE_BYTES // (1024 * 1024)} MB or smaller."
                ),
            },
        )

    existing = normalize_story_hook(concept.story_hook)
    taken = [v.asset_key for v in (existing.visuals if existing else [])]
    # Client filenames are never trusted as paths — only as a slug seed.
    suggested = dedupe_asset_key(
        normalize_asset_key(
            Path(file.filename or "").stem, fallback=f"visual_{len(taken) + 1}"
        ),
        taken,
    )

    storage = get_story_hook_storage()
    storage_key = await storage.save(
        data=data,
        content_type=content_type,
        key_hint=concept.slug or "story-hook",
    )
    return {
        "id": uuid4().hex,
        "asset_key": suggested,
        "storage_key": storage_key,
        "mime_type": content_type,
        "size_bytes": len(data),
    }


@router.get("/concepts/{concept_id}/story-hook/visuals/{asset_key}")
async def get_story_hook_visual(
    concept_id: str,
    asset_key: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Stream a Story Hook visual by ``asset_key``.

    Authenticated for students too (they render these mid-lesson). Teacher-owned
    curricula are restricted to the owning organization; ``storage_key`` is never
    accepted from the client.
    """
    cid = _oid(concept_id, label="concept_id")
    concept = await CurriculumConceptRepository().get_by_id(cid)
    if concept is None or getattr(concept, "deleted_at", None) is not None:
        raise HTTPException(status_code=404, detail="Curriculum concept not found")
    if str(getattr(concept, "topic_source", "")) == "teacher":
        org = getattr(concept, "organization_id", None)
        if org is not None and org != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")

    hook = normalize_story_hook(concept.story_hook)
    wanted = normalize_asset_key(asset_key)
    visual = next(
        (v for v in (hook.visuals if hook else []) if v.asset_key == wanted),
        None,
    )
    if visual is None:
        raise HTTPException(status_code=404, detail="Story Hook visual not found")

    storage = get_story_hook_storage()
    if not await storage.exists(visual.storage_key):
        raise HTTPException(status_code=404, detail="Story Hook visual not found")
    return StreamingResponse(
        storage.open_read(visual.storage_key),
        media_type=visual.mime_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post(
    "/concepts/{concept_id}/visual-teaching/images",
    status_code=status.HTTP_201_CREATED,
)
async def upload_visual_teaching_image(
    concept_id: str,
    topic_source: str,
    file: UploadFile = File(...),
    replace_asset_key: Optional[str] = None,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    """
    Upload one Visual Teaching image and return metadata draft.

    Binary is committed immediately; durable only after concept save attaches it.
    When ``replace_asset_key`` is set (replacing an existing image), the response
    always has ``annotations_status=stale`` — client cannot claim confirmed.
    """
    from app.services.visual_teaching.image_probe import safe_probe

    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    concept = await CurriculumConceptService().get(cid, ctx)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in vt_storage.ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_IMAGE_TYPE",
                "message": (
                    "Visual Teaching images must be JPEG, PNG or WebP "
                    f"(received '{content_type or 'unknown'}')."
                ),
            },
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_IMAGE", "message": "Uploaded image is empty"},
        )
    if len(data) > vt_storage.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "IMAGE_TOO_LARGE",
                "message": (
                    f"Visual Teaching images must be "
                    f"{vt_storage.MAX_IMAGE_BYTES // (1024 * 1024)} MB or smaller."
                ),
            },
        )

    existing = normalize_visual_teaching(getattr(concept, "visual_teaching", None))
    taken = [img.asset_key for img in (existing.images if existing else [])]
    replace_key = normalize_asset_key(replace_asset_key) if replace_asset_key else ""
    is_replace = bool(replace_key and replace_key in taken)
    if is_replace:
        suggested = replace_key
    else:
        suggested = dedupe_asset_key(
            normalize_asset_key(
                Path(file.filename or "").stem, fallback=f"image_{len(taken) + 1}"
            ),
            taken,
        )
    width, height = safe_probe(data, content_type)
    if width <= 0 or height <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IMAGE",
                "message": (
                    "Uploaded file is not a readable JPEG, PNG, or WebP image."
                ),
            },
        )
    storage = vt_storage.get_visual_teaching_storage()
    storage_key = await storage.save(
        data=data,
        content_type=content_type,
        key_hint=concept.slug or "visual-teaching",
    )
    return {
        "id": uuid4().hex,
        "asset_key": suggested,
        "storage_key": storage_key,
        "mime_type": content_type,
        "size_bytes": len(data),
        "natural_width": width,
        "natural_height": height,
        "content_hash": content_hash_bytes(data),
        # Server-authoritative: replace always stale; new upload starts confirmed.
        "annotations_status": "stale" if is_replace else "confirmed",
    }


@router.post(
    "/concepts/{concept_id}/vtse-visuals/images",
    status_code=status.HTTP_201_CREATED,
)
async def upload_vtse_visual_image(
    concept_id: str,
    topic_source: str,
    file: UploadFile = File(...),
    replace_asset_key: Optional[str] = None,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> dict:
    """Upload one VTSE image. Durable only after the concept save attaches it."""
    from app.services.storage import visual_teaching_storage as vt_storage_mod
    from app.services.visual_teaching.image_probe import safe_probe
    from app.services.vtse_visuals.authored import normalize_vtse_visuals

    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    concept = await CurriculumConceptService().get(cid, ctx)
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in vt_storage_mod.ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_IMAGE_TYPE",
                "message": "VTSE images must be JPEG, PNG or WebP.",
            },
        )
    data = await file.read()
    if not data or len(data) > vt_storage_mod.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IMAGE", "message": "VTSE image is empty or too large."},
        )
    existing = normalize_vtse_visuals(getattr(concept, "vtse_visuals", None))
    taken = [str(img.get("asset_key") or "") for img in (existing or {}).get("images") or []]
    replace_key = normalize_asset_key(replace_asset_key) if replace_asset_key else ""
    is_replace = bool(replace_key and replace_key in taken)
    suggested = replace_key if is_replace else dedupe_asset_key(
        normalize_asset_key(Path(file.filename or "").stem, fallback=f"vtse_{len(taken) + 1}"),
        taken,
    )
    width, height = safe_probe(data, content_type)
    if width <= 0 or height <= 0:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IMAGE", "message": "Uploaded file is not a readable image."},
        )
    storage = vt_storage_mod.get_vtse_visuals_storage()
    storage_key = await storage.save(
        data=data,
        content_type=content_type,
        key_hint=concept.slug or "vtse-visual",
    )
    from app.services.visual_teaching.authored import content_hash_bytes

    return {
        "id": uuid4().hex,
        "asset_key": suggested,
        "storage_key": storage_key,
        "mime_type": content_type,
        "natural_width": width,
        "natural_height": height,
        "content_hash": content_hash_bytes(data),
        "annotations_status": "stale" if is_replace else "confirmed",
    }


@router.get("/concepts/{concept_id}/vtse-visuals/images/{asset_key}")
async def get_vtse_visual_image(
    concept_id: str,
    asset_key: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a VTSE image by asset_key. Clients never address storage_key."""
    from app.services.storage.visual_teaching_storage import get_vtse_visuals_storage
    from app.services.vtse_visuals.authored import normalize_vtse_visuals

    cid = _oid(concept_id, label="concept_id")
    concept = await CurriculumConceptRepository().get_by_id(cid)
    if concept is None or getattr(concept, "deleted_at", None) is not None:
        raise HTTPException(status_code=404, detail="Curriculum concept not found")
    if str(getattr(concept, "topic_source", "")) == "teacher":
        org = getattr(concept, "organization_id", None)
        if org is not None and org != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")
    pkg = normalize_vtse_visuals(getattr(concept, "vtse_visuals", None))
    wanted = normalize_asset_key(asset_key)
    image = next(
        (
            img
            for img in (pkg or {}).get("images") or []
            if str(img.get("asset_key") or "") == wanted
        ),
        None,
    )
    if image is None:
        raise HTTPException(status_code=404, detail="VTSE image not found")
    storage = get_vtse_visuals_storage()
    storage_key = str(image.get("storage_key") or "")
    if not await storage.exists(storage_key):
        raise HTTPException(status_code=404, detail="VTSE image not found")
    return StreamingResponse(
        storage.open_read(storage_key),
        media_type=str(image.get("mime_type") or "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/concepts/{concept_id}/visual-teaching/images/{asset_key}")
async def get_visual_teaching_image(
    concept_id: str,
    asset_key: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a Visual Teaching image by asset_key (no client storage_key)."""
    cid = _oid(concept_id, label="concept_id")
    concept = await CurriculumConceptRepository().get_by_id(cid)
    if concept is None or getattr(concept, "deleted_at", None) is not None:
        raise HTTPException(status_code=404, detail="Curriculum concept not found")
    if str(getattr(concept, "topic_source", "")) == "teacher":
        org = getattr(concept, "organization_id", None)
        if org is not None and org != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Curriculum concept not found")

    pkg = normalize_visual_teaching(getattr(concept, "visual_teaching", None))
    wanted = normalize_asset_key(asset_key)
    image = next(
        (img for img in (pkg.images if pkg else []) if img.asset_key == wanted),
        None,
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Visual Teaching image not found")

    storage = vt_storage.get_visual_teaching_storage()
    if not await storage.exists(image.storage_key):
        raise HTTPException(status_code=404, detail="Visual Teaching image not found")
    return StreamingResponse(
        storage.open_read(image.storage_key),
        media_type=image.mime_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/concepts/{concept_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_curriculum_concept(
    concept_id: str,
    topic_source: str,
    current_user: User = Depends(get_current_teacher_or_admin),
) -> Response:
    if topic_source not in ("catalog", "teacher"):
        raise HTTPException(status_code=400, detail="topic_source must be catalog or teacher")
    cid = _oid(concept_id, label="concept_id")
    ctx = await _ctx_for_concept(cid, topic_source, current_user)
    await CurriculumConceptService().delete(cid, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
