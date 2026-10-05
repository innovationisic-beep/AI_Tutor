"""Visual Teaching engine — schema, capabilities, planner, runtime."""

from app.services.visual_teaching.capabilities import (
    SUPPORTED_VISUAL_CAPABILITIES,
    is_capability_supported,
)
from app.services.visual_teaching.plan_schema import (
    VisualState,
    VisualTeachingPlan,
    apply_visual_state_patch,
    empty_visual_state,
    materialize_beat_states,
)

__all__ = [
    "SUPPORTED_VISUAL_CAPABILITIES",
    "is_capability_supported",
    "VisualState",
    "VisualTeachingPlan",
    "apply_visual_state_patch",
    "empty_visual_state",
    "materialize_beat_states",
]
