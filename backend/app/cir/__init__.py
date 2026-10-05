"""
Canonical Instructional Representation (CIR) — foundation only.

Zone 1 explanation turns: schema, validation, optional compile to Timeline V3.
Runtime and SessionService are unchanged; invalid CIR falls back to existing paths.
"""

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.examples_photosynthesis import photosynthesis_cir_v1
from app.cir.template_emit import (
    cir_v1_dict_from_template_steps,
    cir_v1_from_planner_steps,
)
from app.cir.validate import validate_cir_v1
from app.cir.v1 import (
    CIRBeatV1,
    CIRLayoutHintsV1,
    CanonicalInstructionalRepresentationV1,
    CIREdgeV1,
    CIRNarrationSegmentV1,
    CIRNodeV1,
)

__all__ = [
    "CIRBeatV1",
    "CIRLayoutHintsV1",
    "CIREdgeV1",
    "CIRNarrationSegmentV1",
    "CIRNodeV1",
    "CanonicalInstructionalRepresentationV1",
    "compile_cir_v1_to_timeline",
    "cir_v1_dict_from_template_steps",
    "cir_v1_from_planner_steps",
    "photosynthesis_cir_v1",
    "validate_cir_v1",
]
