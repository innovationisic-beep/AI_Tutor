"""Shared enums for structured curriculum (Phase 1)."""

from typing import Literal

CurriculumSchemaVersion = Literal["v1", "v2"]
TopicSource = Literal["catalog", "teacher"]
CurriculumEntityStatus = Literal["draft", "published", "archived"]
CurriculumZonePurpose = Literal[
    "curiosity",
    "core_teaching",
    "extension_1",
    "extension_2",
    "extension_3",
]
ContentDifficulty = Literal["basic", "medium", "hard"]
