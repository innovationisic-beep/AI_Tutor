from enum import Enum


class VideoStatus(str, Enum):
    """Lifecycle status for learning videos."""

    draft = "draft"
    approved = "approved"
    archived = "archived"


class NoteType(str, Enum):
    """Classification for reusable topic notes."""

    summary = "summary"
    detailed = "detailed"
    revision = "revision"


class AssignmentType(str, Enum):
    """Supported assignment categories."""

    project = "project"
    essay = "essay"
    problem_set = "problem_set"


class ApprovalStatus(str, Enum):
    """Moderation queue status."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ContentType(str, Enum):
    """Content types supported by moderation queue."""

    video = "video"
    note = "note"
    question = "question"
