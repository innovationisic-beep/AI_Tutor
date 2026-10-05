from enum import Enum


class SessionEventType(str, Enum):
    QUESTION = "question"
    ANSWER = "answer"
    PERFORMANCE = "performance"
    PAUSE = "pause"
    REWIND = "rewind"
    PLAY = "play"
    HINT_REQUEST = "hint_request"
    TEACHBACK = "teachback"
    SUBTITLE_EXPLANATION_REQUEST = "subtitle_explanation_request"
