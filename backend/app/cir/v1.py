"""CIR v1 — minimal Pydantic models (Zone 1 explanation foundation)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

CIR_VERSION_LITERAL = Literal["1"]
RepresentationTypeV1 = Literal["hierarchy", "flow", "comparison", "cycle"]
NodeKindV1 = Literal["concept", "process", "property"]
EdgeRelationV1 = Literal["causes", "part_of", "leads_to", "requires"]


class CIRLayoutHintsV1(BaseModel):
    """Optional spatial / grouping hints for the compiler (ignored if absent)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    preferred_layout: str = Field(
        default="",
        max_length=64,
        description="e.g. vertical_flow, horizontal_flow, radial — compiler may map loosely",
    )
    grouping: str = Field(
        default="",
        max_length=64,
        description="e.g. cluster, grouped — prefer clustered columns when set",
    )
    emphasis: str = Field(default="", max_length=64)


class CIRNodeV1(BaseModel):
    """Instructional node (concept / process / property)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(..., min_length=1, max_length=256, description="Stable node id")
    label: str = Field(..., min_length=1, max_length=512)
    summary: str = Field(default="", max_length=4000)
    kind: NodeKindV1 = "concept"
    supporting_material: str = Field(default="", max_length=2000)
    narration: str = Field(default="", max_length=2000)
    semantic_role: str = Field(default="", max_length=256)
    visual_weight: str = Field(default="", max_length=32)
    group: str = Field(default="", max_length=64)
    preferred_position: str = Field(
        default="",
        max_length=64,
        description="Optional: root, left_col, right_col, ring — compiler hint only",
    )


class CIREdgeV1(BaseModel):
    """Directed relation between nodes."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_: str = Field(..., min_length=1, max_length=256, alias="from")
    to: str = Field(..., min_length=1, max_length=256)
    relation: EdgeRelationV1


class CIRBeatV1(BaseModel):
    """
    One teaching beat — maps to Timeline V3 beat (ops + narration_segments).

    Compiler uses index order with nodes; optional focus_node_id overrides
    default node alignment when len(beats) != len(nodes).
    """

    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(..., min_length=1, max_length=128)
    index: int = Field(..., ge=0)
    narration_text: str = Field(..., min_length=1, max_length=8000)
    annotation_text: Optional[str] = Field(default=None, max_length=2000)
    highlight_node_ids: list[str] = Field(default_factory=list)
    focus_node_id: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Entity receiving add_entity for this beat when counts differ",
    )


class CIRNarrationSegmentV1(BaseModel):
    """Narration line bound to a beat (subset or mirror of beat narration)."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(..., min_length=1, max_length=128)
    beat_id: str = Field(..., min_length=1, max_length=128)
    text: str = Field(..., min_length=1, max_length=8000)


class CanonicalInstructionalRepresentationV1(BaseModel):
    """
    CIR v1 root — canonical intermediate representation before Timeline V3.

    Intended scope: Zone 1 explanation turns only (foundation).
    """

    model_config = ConfigDict(extra="forbid")

    version: CIR_VERSION_LITERAL = "1"
    representation_type: RepresentationTypeV1
    topic: str = Field(..., min_length=1, max_length=512)
    nodes: list[CIRNodeV1] = Field(default_factory=list)
    edges: list[CIREdgeV1] = Field(default_factory=list)
    beats: list[CIRBeatV1] = Field(default_factory=list)
    narration_segments: list[CIRNarrationSegmentV1] = Field(default_factory=list)
    layout_hints: Optional[CIRLayoutHintsV1] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _non_empty_core(self) -> CanonicalInstructionalRepresentationV1:
        if not self.nodes:
            raise ValueError("nodes must be non-empty for CIR v1")
        if not self.beats:
            raise ValueError("beats must be non-empty for CIR v1")
        return self
