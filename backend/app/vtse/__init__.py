"""
VTSE — Visual Teaching Strategy Engine (Phase 1 infrastructure shell).

Planning layer only; Timeline V3 remains the execution kernel.
"""

from app.vtse.compiler.vtse_compiler import VTSECompiler, VTSECompileResult
from app.vtse.flags import vtse_authoring_zone1_enabled, vtse_enabled, vtse_zone1_enabled
from app.vtse.models.plan import TeachingPlan
from app.vtse.pipeline import apply_vtse_shell_to_cir_dict, stamp_timeline_vtse_metadata
from app.vtse.registry.strategy_registry import (
    STRATEGY_IDS,
    get_strategy,
    resolve_strategy_id_for_representation,
)

__all__ = [
    "TeachingPlan",
    "VTSECompiler",
    "VTSECompileResult",
    "apply_vtse_shell_to_cir_dict",
    "stamp_timeline_vtse_metadata",
    "vtse_enabled",
    "vtse_zone1_enabled",
    "vtse_authoring_zone1_enabled",
    "STRATEGY_IDS",
    "get_strategy",
    "resolve_strategy_id_for_representation",
]
