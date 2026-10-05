"""Tests for canonical_runtime_key helpers."""

import pytest

from app.services.curriculum.curriculum_validators import (
    assign_canonical_runtime_key,
    normalize_runtime_key,
)


def test_normalize_runtime_key():
    assert normalize_runtime_key("  ATP Synthesis  ") == "atp synthesis"


def test_assign_prefers_explicit():
    assert (
        assign_canonical_runtime_key(
            explicit="Custom Key",
            legacy_concept_key="legacy",
            display_name="Display",
        )
        == "custom key"
    )


def test_assign_uses_legacy_before_display():
    assert (
        assign_canonical_runtime_key(
            explicit=None,
            legacy_concept_key="Legacy Key",
            display_name="Display Name",
        )
        == "legacy key"
    )


def test_normalize_empty_raises():
    with pytest.raises(ValueError):
        normalize_runtime_key("   ")
