"""
Supported-capabilities contract for Visual Teaching.

Permanent VisualState schema may include the full vocabulary; production plans
may only use capabilities listed here for the currently deployed renderer.
Unsupported planner emission → validation failure → skip stage (never silent no-op).
"""

from __future__ import annotations

ALL_VISUAL_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        "highlights",
        "pointer",
        "labels_visible",
        "dim_others",
        "zoom",
        "arrows",
        "enter_effects",
        "sentence_visual_patches",
    }
)

SUPPORTED_VISUAL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "highlights",
        "pointer",
        "labels_visible",
        "dim_others",
        "zoom",
        "arrows",
        "enter_effects",
        "sentence_visual_patches",
    }
)

# Explicit allowlist — unknown types fail validation (never free-form strings).
ALLOWED_ENTER_EFFECT_TYPES: frozenset[str] = frozenset(
    {
        "pulse_highlight",
        "animate_pointer",
        "animate_zoom",
    }
)


def is_capability_supported(name: str) -> bool:
    return str(name or "").strip() in SUPPORTED_VISUAL_CAPABILITIES


def unsupported_in(used: set[str] | frozenset[str] | list[str]) -> list[str]:
    return sorted(str(c) for c in used if not is_capability_supported(str(c)))


def is_enter_effect_allowed(effect_type: str) -> bool:
    return str(effect_type or "").strip() in ALLOWED_ENTER_EFFECT_TYPES
