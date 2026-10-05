"""Runtime curriculum manifest — bridge from planning to Session insert."""

from __future__ import annotations

import hashlib
import json
from typing import List, Literal, Optional

from beanie.odm.fields import PydanticObjectId
from pydantic import BaseModel, Field, model_validator

from app.services.curriculum.curriculum_validators import normalize_runtime_key

ManifestVersion = Literal["1.0"]
ResolutionMode = Literal[
    "class_session_full",
    "class_session_item",
    "published_topic_v2",
    "catalog_session_plan",
    "legacy_v1",
]
LaunchKind = Literal["personal", "classroom"]
TopicSource = Literal["teacher", "catalog"]
CurriculumSchemaVersion = Literal["v1", "v2"]


class LaunchContext(BaseModel):
    """Provenance and launch policy metadata (not consumed by Zone 1 / RAG / quiz)."""

    launch_kind: LaunchKind
    resolution_mode: ResolutionMode
    curriculum_schema_version: CurriculumSchemaVersion
    curriculum_revision: int = Field(..., ge=0)
    source_topic_id: PydanticObjectId
    topic_source: TopicSource = "teacher"
    class_session_instance_id: Optional[PydanticObjectId] = None
    class_session_plan_id: Optional[PydanticObjectId] = None
    plan_item_id: Optional[str] = Field(default=None, max_length=64)
    class_id: Optional[str] = Field(default=None, max_length=64)
    subject_id: Optional[str] = Field(default=None, max_length=64)


class RuntimeCurriculumManifest(BaseModel):
    """Session-shaped curriculum slice for insert-time injection only."""

    key_concepts: List[str] = Field(..., min_length=1)
    concept_clusters: Optional[List[List[str]]] = None
    concept_ids_ordered: List[PydanticObjectId] = Field(default_factory=list)
    launch_context: LaunchContext
    manifest_version: ManifestVersion = "1.0"
    manifest_hash: Optional[str] = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_manifest(self) -> RuntimeCurriculumManifest:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw in self.key_concepts:
            key = normalize_runtime_key(raw)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        if not normalized:
            raise ValueError("EMPTY_MANIFEST")
        object.__setattr__(self, "key_concepts", normalized)

        clusters = self.concept_clusters
        if clusters is not None:
            key_set = set(normalized)
            cleaned: List[List[str]] = []
            for group in clusters:
                row: List[str] = []
                for raw in group:
                    k = normalize_runtime_key(raw)
                    if k not in key_set:
                        raise ValueError("CLUSTER_KEY_ORPHAN")
                    if k not in row:
                        row.append(k)
                if row:
                    cleaned.append(row)
            object.__setattr__(self, "concept_clusters", cleaned or None)

        if self.launch_context.resolution_mode in (
            "class_session_full",
            "class_session_item",
        ):
            if self.launch_context.curriculum_schema_version != "v2":
                raise ValueError("V2_REQUIRED")
            if self.launch_context.launch_kind != "classroom":
                raise ValueError("CLASSROOM_CONTEXT_REQUIRED")

        if len(self.concept_ids_ordered) > len(normalized):
            raise ValueError("ID_MAP_MISMATCH")

        if self.manifest_hash is None:
            payload = {
                "key_concepts": normalized,
                "concept_clusters": self.concept_clusters,
            }
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "manifest_hash", digest)

        return self
