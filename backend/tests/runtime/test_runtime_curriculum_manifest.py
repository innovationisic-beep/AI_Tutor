"""Tests for RuntimeCurriculumManifest validation."""

from __future__ import annotations

import pytest
from beanie.odm.fields import PydanticObjectId

from app.models.runtime.runtime_curriculum_manifest import (
    LaunchContext,
    RuntimeCurriculumManifest,
)


def _classroom_context(**overrides) -> LaunchContext:
    base = {
        "launch_kind": "classroom",
        "resolution_mode": "class_session_full",
        "curriculum_schema_version": "v2",
        "curriculum_revision": 1,
        "source_topic_id": PydanticObjectId(),
        "topic_source": "teacher",
        "class_session_instance_id": PydanticObjectId(),
        "class_session_plan_id": PydanticObjectId(),
        "class_id": "class-10a",
        "subject_id": "science",
    }
    base.update(overrides)
    return LaunchContext(**base)


def test_manifest_normalizes_and_dedupes_keys():
    manifest = RuntimeCurriculumManifest(
        key_concepts=[" Concept A ", "concept a", "Concept B"],
        concept_clusters=[["concept a", "concept b"]],
        launch_context=_classroom_context(),
    )
    assert manifest.key_concepts == ["concept a", "concept b"]
    assert manifest.manifest_hash is not None


def test_manifest_rejects_orphan_cluster_key():
    with pytest.raises(ValueError, match="CLUSTER_KEY_ORPHAN"):
        RuntimeCurriculumManifest(
            key_concepts=["concept a"],
            concept_clusters=[["concept a", "missing"]],
            launch_context=_classroom_context(),
        )


def test_manifest_requires_v2_for_classroom():
    with pytest.raises(ValueError, match="V2_REQUIRED"):
        RuntimeCurriculumManifest(
            key_concepts=["concept a"],
            launch_context=_classroom_context(curriculum_schema_version="v1"),
        )


def test_launch_context_fields_present():
    manifest = RuntimeCurriculumManifest(
        key_concepts=["alpha"],
        launch_context=_classroom_context(),
    )
    assert manifest.launch_context.launch_kind == "classroom"
    assert manifest.launch_context.resolution_mode == "class_session_full"
    assert manifest.launch_context.class_id == "class-10a"
