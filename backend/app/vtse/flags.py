"""VTSE product path is always on (no env rollout gates).

Authored VTSE → TeachingPlan → VTSECompiler → CIR → TimelinePlannerV3 → ITV3
is the only supported Zone 1 visual teaching path.

Deprecated env flags (removed, ignored if still set):
ENABLE_VTSE, ENABLE_VTSE_ZONE1, ENABLE_VTSE_AUTHORING_ZONE1,
ENABLE_VTSE_PROCESS_LLM, ENABLE_VTSE_COMPARISON_LLM, ENABLE_VTSE_TRAIT_LLM,
ENABLE_TIMELINE_V3_PROD.
"""

from __future__ import annotations


def vtse_enabled() -> bool:
    """Always True — master VTSE path is unconditional."""
    return True


def vtse_zone1_enabled() -> bool:
    """Always True — Zone 1 CIR shell / metadata stamp is unconditional."""
    return True


def vtse_authoring_zone1_enabled() -> bool:
    """Always True — authored TeachingPlan → CIR authoring is unconditional."""
    return True
