from enum import Enum


class CurriculumStatus(str, Enum):
    """Lifecycle state for curriculum entities."""

    draft = "draft"
    active = "active"
    archived = "archived"
