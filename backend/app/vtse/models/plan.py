"""Teaching DSL (TDSL) v0.1 — foundational planning models."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TDSL_VERSION = "0.1"

RepresentationType = Literal["hierarchy", "flow", "comparison", "cycle"]
EdgeRelation = Literal["causes", "part_of", "leads_to", "requires"]
PacingMode = Literal["deliver", "reinforce", "visualize", "reflect", "question", "close"]
PedagogicalRole = Literal[
    "anchor",
    "explain",
    "reinforce",
    "connect",
    "emphasize",
    "compare",
    "reflect",
    "checkpoint",
    "recover",
    "close",
]
RevealStepKind = Literal[
    "show_node",
    "annotate",
    "connect",
    "highlight",
]
InteractionGateKind = Literal[
    "none",
    "student_reflection_wait",
    "student_answer_wait",
    "quiz_wait",
    "teachback_wait",
]


class TeachingStrategyRef(BaseModel):
    """Reference to a registered pedagogical strategy."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(..., min_length=1, max_length=128)
    strategy_version: str = Field(default="1.0.0", max_length=32)
    layout_family: str = Field(default="", max_length=64)


class SemanticNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=256)
    label: str = Field(..., min_length=1, max_length=512)
    summary: str = Field(default="", max_length=4000)
    kind: Literal["concept", "process", "property"] = "concept"
    semantic_role: str = Field(default="", max_length=256)
    group: str = Field(default="", max_length=64)
    preferred_position: str = Field(default="", max_length=64)
    narration: str = Field(default="", max_length=2000)


class SemanticEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_id: str = Field(..., min_length=1, max_length=256, alias="from")
    to: str = Field(..., min_length=1, max_length=256)
    relation: EdgeRelation = "leads_to"


class SemanticGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    representation_type: RepresentationType
    topic: str = Field(..., min_length=1, max_length=512)
    nodes: list[SemanticNode] = Field(default_factory=list)
    edges: list[SemanticEdge] = Field(default_factory=list)
    layout_hints: Optional[dict[str, Any]] = None


class RevealStep(BaseModel):
    """Semantic reveal intent (compiled to Timeline ops in later phases)."""

    model_config = ConfigDict(extra="forbid")

    kind: RevealStepKind
    node_id: Optional[str] = None
    target_id: Optional[str] = None
    text: Optional[str] = None
    from_id: Optional[str] = None
    to_id: Optional[str] = None
    relation: Optional[EdgeRelation] = None
    target_ids: list[str] = Field(default_factory=list)


class RevealScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[RevealStep] = Field(default_factory=list)


class MicroQuestionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(default="", max_length=2000)
    kind: Literal["recall", "explain", "apply", "reflect"] = "reflect"


class BeatInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: InteractionGateKind = "none"
    required: bool = False
    micro_question: Optional[MicroQuestionIntent] = None


class TeachingBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(..., min_length=1, max_length=128)
    index: int = Field(..., ge=0)
    pedagogical_role: PedagogicalRole = "explain"
    pacing_mode: PacingMode = "deliver"
    focus_node_id: Optional[str] = Field(default=None, max_length=256)
    narration_text: str = Field(..., min_length=1, max_length=8000)
    annotation_text: Optional[str] = Field(default=None, max_length=2000)
    highlight_node_ids: list[str] = Field(default_factory=list)
    reveal_script: Optional[RevealScript] = None
    interaction: BeatInteraction = Field(default_factory=BeatInteraction)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionPolicy(BaseModel):
    """Session-level interaction pacing (Phase 1 defaults only)."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(default="explanation_first", max_length=64)
    first_question_after_role: PedagogicalRole = "reflect"
    max_reflect_beats_per_arc: int = Field(default=1, ge=0, le=8)


class AdaptiveHook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: str = Field(..., min_length=1, max_length=128)
    on_signal: Literal[
        "student_answer",
        "wrong_answer",
        "confusion_signal",
        "mastery_signal",
        "skip",
    ]
    replan_from_beat_id: Optional[str] = None
    strategy_override_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeachingPlan(BaseModel):
    """
    Versioned pedagogical plan (TDSL document root).

    Phase 1: primarily round-trips CIR v1 without changing compile output.
    """

    model_config = ConfigDict(extra="forbid")

    tdsl_version: Literal["0.1"] = TDSL_VERSION
    plan_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(default="", max_length=128)
    topic_id: str = Field(default="", max_length=128)
    concept_id: str = Field(default="", max_length=256)
    learning_objective: str = Field(default="", max_length=2000)

    strategy: TeachingStrategyRef
    interaction_policy: InteractionPolicy = Field(default_factory=InteractionPolicy)
    semantic_graph: SemanticGraph
    beats: list[TeachingBeat] = Field(default_factory=list)
    adaptive_hooks: list[AdaptiveHook] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id
