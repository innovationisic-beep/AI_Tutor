from pydantic import BaseModel


class BaseSchema(BaseModel):
    class Config:
        extra = "forbid"
        validate_assignment = True
        anystr_strip_whitespace = True
