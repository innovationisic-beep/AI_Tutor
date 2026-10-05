"""
Aggregate all Beanie document models for init_beanie().

Usage:
    from beanie import init_beanie
    from app.models import BEANIE_DOCUMENT_MODELS

    await init_beanie(database=db, document_models=BEANIE_DOCUMENT_MODELS)
"""

from app.models.content import (
    Assignment,
    ContentApprovalQueue,
    StudentNote,
    TopicNote,
    TopicQuestionBank,
    Video,
    VideoSubtitle,
)
from app.models.curriculum import (
    PrerequisiteGraph,
    Subject,
    Topic,
    TopicProgressionMap,
)
from app.models.identification import (
    Organization,
    ParentProfile,
    ParentStudentMapping,
    StudentProfile,
    Teacher,
    TeacherStudentMapping,
    User,
)
from app.models.intelligence import (
    AIGenerationLog,
    LearningPlan,
    PerformanceMetrics,
    RecommendationFeedback,
    StudentGoalProfile,
)
from app.models.learning import SessionSummary
from app.models.learning_execution import (
    ConfusionLog,
    KnowledgeGap,
    MasteryRecord,
    RecommendationLog,
    Session,
    SessionEvent,
    TeachbackEvaluation,
)

BEANIE_DOCUMENT_MODELS = [
    Organization,
    User,
    StudentProfile,
    Teacher,
    TeacherStudentMapping,
    ParentProfile,
    ParentStudentMapping,
    Subject,
    Topic,
    PrerequisiteGraph,
    TopicProgressionMap,
    Video,
    VideoSubtitle,
    TopicNote,
    StudentNote,
    TopicQuestionBank,
    ContentApprovalQueue,
    Assignment,
    Session,
    SessionEvent,
    MasteryRecord,
    KnowledgeGap,
    ConfusionLog,
    RecommendationLog,
    TeachbackEvaluation,
    SessionSummary,
    LearningPlan,
    StudentGoalProfile,
    PerformanceMetrics,
    RecommendationFeedback,
    AIGenerationLog,
]

__all__ = [
    "BEANIE_DOCUMENT_MODELS",
    "Organization",
    "User",
    "StudentProfile",
    "Teacher",
    "TeacherStudentMapping",
    "ParentProfile",
    "ParentStudentMapping",
    "Subject",
    "Topic",
    "PrerequisiteGraph",
    "TopicProgressionMap",
    "Video",
    "VideoSubtitle",
    "TopicNote",
    "StudentNote",
    "TopicQuestionBank",
    "ContentApprovalQueue",
    "Assignment",
    "Session",
    "SessionEvent",
    "MasteryRecord",
    "KnowledgeGap",
    "ConfusionLog",
    "RecommendationLog",
    "TeachbackEvaluation",
    "SessionSummary",
    "LearningPlan",
    "StudentGoalProfile",
    "PerformanceMetrics",
    "RecommendationFeedback",
    "AIGenerationLog",
]
