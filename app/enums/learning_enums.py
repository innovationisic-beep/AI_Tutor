from enum import Enum


class SessionMode(str, Enum):
    """Interaction mode selected for a learning session."""

    explorer = "explorer"
    revision = "revision"
    exam = "exam"


class SessionStatus(str, Enum):
    """Lifecycle status of a learning session."""

    in_progress = "in_progress"
    completed = "completed"
    abandoned = "abandoned"


class EventType(str, Enum):
    """Supported interaction events captured during session execution."""

    question = "question"
    answer = "answer"
    pause = "pause"
    rewind = "rewind"
    play = "play"
    hint_request = "hint_request"
    teachback = "teachback"
    subtitle_explanation_request = "subtitle_explanation_request"


class ConfusionTriggerType(str, Enum):
    """Behavioral triggers used to mark confusion signals."""

    slow_response = "slow_response"
    wrong_answer = "wrong_answer"
    repeated_pause = "repeated_pause"
    repeated_rewind = "repeated_rewind"
    multiple_explanation_requests = "multiple_explanation_requests"
