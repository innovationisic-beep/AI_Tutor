"""Pydantic schemas for structured curriculum APIs (Phase 1)."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

TopicSource = Literal["catalog", "teacher"]
ConceptTeachingStage = Literal["vtse", "story_hook", "visual_teaching", "media"]


class ConceptStoryHookVisualOut(BaseModel):
    """
    Authoring view of a Story Hook visual (teacher/admin routes only).

    ``storage_key`` is echoed so the builder can re-commit existing visuals on
    concept save. It is opaque and must never reach a student surface — the
    runtime exposes only ``asset_key`` plus an authenticated media URL.
    """

    id: str = ""
    asset_key: str = ""
    storage_key: str = ""
    description: str = ""
    teaching_purpose: str = ""
    mime_type: str = ""
    sort_order: int = 0


class ConceptStoryHookVisualIn(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    asset_key: str = Field(default="", max_length=64)
    storage_key: str = Field(..., min_length=1, max_length=512)
    description: str = Field(default="", max_length=600)
    teaching_purpose: str = Field(default="", max_length=600)
    mime_type: str = Field(default="", max_length=100)


class ConceptStoryHookOut(BaseModel):
    title: str = ""
    body: str = ""
    teacher_intent: str = ""
    visuals: List[ConceptStoryHookVisualOut] = Field(default_factory=list)


class ConceptStoryHookIn(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=8000)
    teacher_intent: str = Field(default="", max_length=2000)
    visuals: Optional[List[ConceptStoryHookVisualIn]] = None


class VisualTeachingRegionOut(BaseModel):
    region_id: str = ""
    label: str = ""
    teaching_purpose: str = ""
    sort_order: int = 0
    shape: str = "rect"
    geometry: dict = Field(default_factory=dict)
    focus_point: Optional[dict] = None
    label_box: Optional[dict] = None
    highlight_color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None


class VisualTeachingRegionIn(BaseModel):
    region_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    shape: str = Field(default="rect", max_length=32)
    geometry: dict = Field(default_factory=dict)
    focus_point: Optional[dict] = None
    label_box: Optional[dict] = None
    highlight_color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None


class VisualTeachingAnchorOut(BaseModel):
    anchor_id: str = ""
    label: str = ""
    point: dict = Field(default_factory=dict)


class VisualTeachingAnchorIn(BaseModel):
    anchor_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    point: dict = Field(default_factory=dict)


class VisualTeachingConnectionOut(BaseModel):
    connection_id: str = ""
    from_anchor: str = ""
    to_anchor: str = ""
    label: str = ""
    teaching_purpose: str = ""
    # Internal compatibility default; not exposed in authoring UI.
    kind: str = "flow"
    color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None
    label_box: Optional[dict] = None


class VisualTeachingConnectionIn(BaseModel):
    connection_id: str = Field(default="", max_length=64)
    from_anchor: str = Field(default="", max_length=64)
    to_anchor: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    # Internal compatibility default; authoring does not choose kind.
    kind: str = Field(default="flow", max_length=32)
    color: Optional[str] = None
    label_bg_color: Optional[str] = None
    label_text_color: Optional[str] = None
    label_box: Optional[dict] = None


class VisualTeachingImageOut(BaseModel):
    id: str = ""
    asset_key: str = ""
    storage_key: str = ""
    mime_type: str = ""
    sort_order: int = 0
    title: str = ""
    teaching_purpose: str = ""
    natural_width: int = 0
    natural_height: int = 0
    content_hash: str = ""
    annotations_status: str = "confirmed"
    regions: List[VisualTeachingRegionOut] = Field(default_factory=list)
    anchors: List[VisualTeachingAnchorOut] = Field(default_factory=list)
    connections: List[VisualTeachingConnectionOut] = Field(default_factory=list)


class VisualTeachingImageIn(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    asset_key: str = Field(default="", max_length=64)
    storage_key: str = Field(..., min_length=1, max_length=512)
    mime_type: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=200)
    teaching_purpose: str = Field(default="", max_length=600)
    natural_width: int = Field(default=0, ge=0)
    natural_height: int = Field(default=0, ge=0)
    content_hash: str = Field(default="", max_length=128)
    annotations_status: str = Field(default="confirmed", max_length=32)
    regions: Optional[List[VisualTeachingRegionIn]] = None
    anchors: Optional[List[VisualTeachingAnchorIn]] = None
    connections: Optional[List[VisualTeachingConnectionIn]] = None


class ConceptVisualTeachingOut(BaseModel):
    images: List[VisualTeachingImageOut] = Field(default_factory=list)


class ConceptVisualTeachingIn(BaseModel):
    images: Optional[List[VisualTeachingImageIn]] = None


class ConceptVtseTemplateOut(BaseModel):
    strategy_id: str
    version: int = 1
    payload: dict = Field(default_factory=dict)


class ConceptVtseTemplateIn(BaseModel):
    strategy_id: Optional[str] = None
    version: int = Field(default=1, ge=1)
    payload: Optional[dict] = None


class CurriculumConceptOut(BaseModel):
    id: str
    curriculum_zone_id: str
    curriculum_cluster_id: str
    slug: str
    display_name: str
    canonical_runtime_key: str
    sort_order: int
    difficulty_level: str
    estimated_learning_minutes: Optional[int] = None
    study_points: List[str] = Field(default_factory=list)
    learning_outcomes: List[str] = Field(default_factory=list)
    story_hook: Optional[ConceptStoryHookOut] = None
    visual_teaching: Optional[ConceptVisualTeachingOut] = None
    teaching_sequence: List[ConceptTeachingStage] = Field(default_factory=list)
    teaching_sequence_mode: str = "manual"
    teaching_sequence_auto: List[ConceptTeachingStage] = Field(default_factory=list)
    teaching_sequence_auto_reason: str = ""
    teaching_sequence_auto_status: str = ""
    teaching_sequence_auto_stale: bool = False
    vtse_template: Optional[ConceptVtseTemplateOut] = None
    vtse_visuals: Optional[dict] = None
    status: str
    published_revision: int = 0


class CurriculumClusterOut(BaseModel):
    id: str
    curriculum_zone_id: str
    cluster_number: int
    title: str
    description: str = ""
    study_points: List[str] = Field(default_factory=list)
    learning_outcomes: List[str] = Field(default_factory=list)
    sort_order: int
    estimated_learning_minutes: Optional[int] = None
    status: str
    concepts: List[CurriculumConceptOut] = Field(default_factory=list)


class CurriculumZoneOut(BaseModel):
    id: str
    zone_number: int
    title: str
    description: str = ""
    purpose: str
    allows_vtse: bool
    is_system_zone: bool
    sort_order: int
    status: str
    clusters: List[CurriculumClusterOut] = Field(default_factory=list)


class CurriculumTreeOut(BaseModel):
    topic_id: str
    topic_source: TopicSource
    topic_name: str
    curriculum_schema_version: str
    curriculum_revision: int
    curriculum_published_at: Optional[str] = None
    supports_class_sessions: bool = False
    zones: List[CurriculumZoneOut] = Field(default_factory=list)


class ValidationIssueOut(BaseModel):
    code: str
    message: str
    path: str = ""


class CurriculumValidationOut(BaseModel):
    errors: List[ValidationIssueOut] = Field(default_factory=list)
    warnings: List[ValidationIssueOut] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    ready_to_publish: bool = False


class CurriculumPublishOut(BaseModel):
    topic_id: str
    topic_source: TopicSource
    curriculum_schema_version: str
    curriculum_revision: int
    curriculum_published_at: Optional[str] = None
    republished: Optional[bool] = None
    unpublished: Optional[bool] = None


class ConceptUsageOut(BaseModel):
    concept_id: str
    topic_id: str
    topic_source: TopicSource
    canonical_runtime_key: str
    display_name: str
    note_count: int
    question_count: int
    notes: List[dict] = Field(default_factory=list)
    questions: List[dict] = Field(default_factory=list)
    concept_check: dict = Field(default_factory=dict)
    cluster_quiz: dict = Field(default_factory=dict)


class CreateCurriculumZoneRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    topic_source: TopicSource
    zone_number: int = Field(..., ge=0, le=4)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    sort_order: Optional[int] = Field(default=None, ge=0)


class UpdateCurriculumZoneRequest(BaseModel):
    topic_source: TopicSource
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    sort_order: Optional[int] = Field(default=None, ge=0)


class CreateCurriculumClusterRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    topic_source: TopicSource
    curriculum_zone_id: str = Field(..., min_length=24, max_length=24)
    title: str = Field(..., min_length=1, max_length=200)
    cluster_number: Optional[int] = Field(default=None, ge=1, le=100)
    sort_order: Optional[int] = Field(default=None, ge=0)
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class UpdateCurriculumClusterRequest(BaseModel):
    topic_source: TopicSource
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    study_points: Optional[List[str]] = None
    learning_outcomes: Optional[List[str]] = None
    sort_order: Optional[int] = Field(default=None, ge=0)
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class CreateCurriculumConceptRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    topic_source: TopicSource
    curriculum_cluster_id: str = Field(..., min_length=24, max_length=24)
    display_name: str = Field(..., min_length=1, max_length=500)
    slug: Optional[str] = Field(default=None, max_length=160)
    sort_order: Optional[int] = Field(default=None, ge=0)
    difficulty_level: str = Field(default="medium")
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    study_points: Optional[List[str]] = None
    learning_outcomes: Optional[List[str]] = None
    story_hook: Optional[ConceptStoryHookIn] = None
    visual_teaching: Optional[ConceptVisualTeachingIn] = None
    teaching_sequence: Optional[List[ConceptTeachingStage]] = None
    teaching_sequence_mode: Optional[str] = None
    vtse_template: Optional[ConceptVtseTemplateIn] = None
    vtse_visuals: Optional[dict] = None
    legacy_concept_key: Optional[str] = Field(default=None, max_length=500)
    canonical_runtime_key: Optional[str] = Field(default=None, max_length=500)


class UpdateCurriculumConceptRequest(BaseModel):
    topic_source: TopicSource
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    sort_order: Optional[int] = Field(default=None, ge=0)
    difficulty_level: Optional[str] = None
    estimated_learning_minutes: Optional[int] = Field(default=None, ge=1, le=480)
    study_points: Optional[List[str]] = None
    learning_outcomes: Optional[List[str]] = None
    story_hook: Optional[ConceptStoryHookIn] = None
    visual_teaching: Optional[ConceptVisualTeachingIn] = None
    teaching_sequence: Optional[List[ConceptTeachingStage]] = None
    teaching_sequence_mode: Optional[str] = None
    vtse_template: Optional[ConceptVtseTemplateIn] = None
    vtse_visuals: Optional[dict] = None
    canonical_runtime_key: Optional[str] = Field(default=None, min_length=1, max_length=500)


class PreviewTeachingOrderRequest(BaseModel):
    topic_source: TopicSource
    regenerate: bool = False


class MoveCurriculumConceptRequest(BaseModel):
    topic_source: TopicSource
    target_cluster_id: str = Field(..., min_length=24, max_length=24)
    target_index: int = Field(
        ...,
        ge=0,
        description="0-based insertion index within the destination cluster.",
    )


def zone_to_out(zone: object) -> CurriculumZoneOut:
    from app.services.curriculum.curriculum_validators import allows_vtse_for_zone

    z = zone
    return CurriculumZoneOut(
        id=str(z.id),
        zone_number=z.zone_number,
        title=z.title,
        description=z.description or "",
        purpose=z.purpose,
        allows_vtse=allows_vtse_for_zone(int(z.zone_number)),
        is_system_zone=z.is_system_zone,
        sort_order=z.sort_order,
        status=z.status,
        clusters=[],
    )


def cluster_to_out(cluster: object) -> CurriculumClusterOut:
    c = cluster
    return CurriculumClusterOut(
        id=str(c.id),
        curriculum_zone_id=str(c.curriculum_zone_id),
        cluster_number=c.cluster_number,
        title=c.title,
        description=getattr(c, "description", "") or "",
        study_points=list(getattr(c, "study_points", None) or []),
        learning_outcomes=list(getattr(c, "learning_outcomes", None) or []),
        sort_order=c.sort_order,
        estimated_learning_minutes=c.estimated_learning_minutes,
        status=c.status,
        concepts=[],
    )


def story_hook_to_out(hook: object) -> ConceptStoryHookOut:
    """Project a normalized hook for authoring UIs, hiding ``storage_key``."""
    return ConceptStoryHookOut(
        title=getattr(hook, "title", "") or "",
        body=getattr(hook, "body", "") or "",
        teacher_intent=getattr(hook, "teacher_intent", "") or "",
        visuals=[
            ConceptStoryHookVisualOut(
                id=v.id,
                asset_key=v.asset_key,
                storage_key=v.storage_key,
                description=v.description,
                teaching_purpose=v.teaching_purpose,
                mime_type=v.mime_type,
                sort_order=v.sort_order,
            )
            for v in (getattr(hook, "visuals", None) or [])
        ],
    )


def visual_teaching_to_out(pkg: object) -> ConceptVisualTeachingOut:
    images = []
    for img in getattr(pkg, "images", None) or []:
        images.append(
            VisualTeachingImageOut(
                id=img.id,
                asset_key=img.asset_key,
                storage_key=img.storage_key,
                mime_type=img.mime_type,
                sort_order=img.sort_order,
                title=img.title,
                teaching_purpose=img.teaching_purpose,
                natural_width=img.natural_width,
                natural_height=img.natural_height,
                content_hash=img.content_hash,
                annotations_status=img.annotations_status,
                regions=[
                    VisualTeachingRegionOut(
                        region_id=r.region_id,
                        label=r.label,
                        teaching_purpose=r.teaching_purpose,
                        sort_order=r.sort_order,
                        shape=r.shape,
                        geometry=dict(r.geometry or {}),
                        focus_point=r.focus_point,
                        label_box=getattr(r, "label_box", None),
                        highlight_color=getattr(r, "highlight_color", None),
                        label_bg_color=getattr(r, "label_bg_color", None),
                        label_text_color=getattr(r, "label_text_color", None),
                    )
                    for r in (img.regions or [])
                ],
                anchors=[
                    VisualTeachingAnchorOut(
                        anchor_id=a.anchor_id,
                        label=a.label,
                        point=dict(a.point or {}),
                    )
                    for a in (img.anchors or [])
                ],
                connections=[
                    VisualTeachingConnectionOut(
                        connection_id=c.connection_id,
                        from_anchor=c.from_anchor,
                        to_anchor=c.to_anchor,
                        label=c.label,
                        teaching_purpose=getattr(c, "teaching_purpose", "") or "",
                        kind=c.kind or "flow",
                        color=getattr(c, "color", None),
                        label_bg_color=getattr(c, "label_bg_color", None),
                        label_text_color=getattr(c, "label_text_color", None),
                        label_box=getattr(c, "label_box", None),
                    )
                    for c in (img.connections or [])
                ],
            )
        )
    return ConceptVisualTeachingOut(images=images)


def concept_to_out(concept: object) -> CurriculumConceptOut:
    from app.services.curriculum.concept_teaching_sequence import normalize_story_hook
    from app.services.curriculum.concept_vtse_template import normalize_vtse_template
    from app.services.visual_teaching.authored import normalize_visual_teaching

    c = concept
    hook = normalize_story_hook(getattr(c, "story_hook", None))
    vt_pkg = normalize_visual_teaching(getattr(c, "visual_teaching", None))
    from app.services.curriculum.concept_teaching_sequence import auto_order_is_stale

    seq_raw = list(getattr(c, "teaching_sequence", None) or [])
    allowed = ("vtse", "story_hook", "visual_teaching", "media")
    seq: List[ConceptTeachingStage] = [
        s  # type: ignore[misc]
        for s in seq_raw
        if str(s).strip().lower() in allowed
    ]
    # Soft-read for tree/out: never fail listing on legacy bad docs
    vtse_out: Optional[ConceptVtseTemplateOut] = None
    try:
        tmpl = normalize_vtse_template(getattr(c, "vtse_template", None))
        if tmpl is not None:
            vtse_out = ConceptVtseTemplateOut(
                strategy_id=tmpl.strategy_id,
                version=tmpl.version,
                payload=dict(tmpl.payload or {}),
            )
    except Exception:  # noqa: BLE001
        raw = getattr(c, "vtse_template", None)
        if isinstance(raw, dict) and raw.get("strategy_id"):
            vtse_out = ConceptVtseTemplateOut(
                strategy_id=str(raw.get("strategy_id")),
                version=int(raw.get("version") or 1),
                payload=dict(raw.get("payload") or {}),
            )
    return CurriculumConceptOut(
        id=str(c.id),
        curriculum_zone_id=str(c.curriculum_zone_id),
        curriculum_cluster_id=str(c.curriculum_cluster_id),
        slug=c.slug,
        display_name=c.display_name,
        canonical_runtime_key=c.canonical_runtime_key,
        sort_order=c.sort_order,
        difficulty_level=c.difficulty_level,
        estimated_learning_minutes=c.estimated_learning_minutes,
        study_points=list(getattr(c, "study_points", None) or []),
        learning_outcomes=list(getattr(c, "learning_outcomes", None) or []),
        story_hook=(story_hook_to_out(hook) if hook else None),
        visual_teaching=(visual_teaching_to_out(vt_pkg) if vt_pkg else None),
        teaching_sequence=seq,
        teaching_sequence_mode=str(getattr(c, "teaching_sequence_mode", None) or "manual"),
        teaching_sequence_auto=[
            s  # type: ignore[misc]
            for s in list(getattr(c, "teaching_sequence_auto", None) or [])
            if str(s).strip().lower() in allowed
        ],
        teaching_sequence_auto_reason=str(
            getattr(c, "teaching_sequence_auto_reason", None) or ""
        ),
        teaching_sequence_auto_status=str(
            getattr(c, "teaching_sequence_auto_status", None) or ""
        ),
        teaching_sequence_auto_stale=auto_order_is_stale(c),
        vtse_template=vtse_out,
        vtse_visuals=getattr(c, "vtse_visuals", None),
        status=c.status,
        published_revision=int(c.published_revision or 0),
    )
