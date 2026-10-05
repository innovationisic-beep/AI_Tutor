"""Unit tests for curriculum validators."""

import pytest

from app.services.curriculum.curriculum_validators import (
    allows_vtse_for_zone,
    is_system_zone_for_number,
    next_cluster_number,
    normalize_slug,
    purpose_for_zone_number,
)


def test_normalize_slug():
    assert normalize_slug("Concept A") == "concept-a"
    assert normalize_slug("  ATP Synthesis  ") == "atp-synthesis"


def test_normalize_slug_empty_raises():
    with pytest.raises(ValueError):
        normalize_slug("   ")


def test_purpose_for_zone_numbers():
    assert purpose_for_zone_number(0) == "curiosity"
    assert purpose_for_zone_number(1) == "core_teaching"
    assert purpose_for_zone_number(4) == "extension_3"


def test_allows_vtse_zones_1_and_2():
    assert allows_vtse_for_zone(1) is True
    assert allows_vtse_for_zone(2) is True
    assert allows_vtse_for_zone(0) is False
    assert allows_vtse_for_zone(3) is False


def test_is_system_zone_only_zone_0():
    assert is_system_zone_for_number(0) is True
    assert is_system_zone_for_number(1) is False


def test_next_cluster_number():
    assert next_cluster_number([]) == 1
    assert next_cluster_number([1, 2]) == 3
