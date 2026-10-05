"""Learning graph (prerequisite + progression) request/response schemas."""

from pydantic import BaseModel, Field


class CreatePrerequisiteRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    prerequisite_topic_id: str = Field(..., min_length=24, max_length=24)


class CreateProgressionRequest(BaseModel):
    topic_id: str = Field(..., min_length=24, max_length=24)
    recommended_next_topic_id: str = Field(..., min_length=24, max_length=24)
    minimum_mastery_to_recommend: int = Field(
        default=60,
        ge=0,
        le=100,
        description="0–100; stored as float on the document.",
    )


class PrerequisiteEdgeOut(BaseModel):
    id: str
    topic_id: str
    prerequisite_topic_id: str


class ProgressionEdgeOut(BaseModel):
    id: str
    topic_id: str
    recommended_next_topic_id: str
    minimum_mastery_to_recommend: int
