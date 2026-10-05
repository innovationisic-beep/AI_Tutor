from enum import Enum


class GoalType(str, Enum):
    """Long-term learner objective categories."""

    exam_prep = "exam_prep"
    concept_mastery = "concept_mastery"
    syllabus_completion = "syllabus_completion"


class PlanGenerator(str, Enum):
    """Source responsible for creating a learning plan."""

    ai = "ai"
    teacher = "teacher"


class FeedbackType(str, Enum):
    """Student response to AI recommendation quality."""

    accepted = "accepted"
    ignored = "ignored"
    rejected = "rejected"


class AITaskType(str, Enum):
    """AI task category used for usage and cost tracking."""

    explanation = "explanation"
    teachback_evaluation = "teachback_evaluation"
    quiz_generation = "quiz_generation"
    note_generation = "note_generation"
    recommendation_reasoning = "recommendation_reasoning"
