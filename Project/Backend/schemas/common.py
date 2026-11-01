from typing import Any
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    email: str
    password: str = Field(min_length=8, max_length=200)


class StatusUpdate(BaseModel):
    status: str


class SendExamRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=100)
    candidate_ids: list[int] | None = None


class ShortlistRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1, max_length=100)


class AnswerRequest(BaseModel):
    text: str = Field(default="", max_length=3000)


class IntegrityEvent(BaseModel):
    event_type: str
    question_order: int | None = None
    occurred_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class EventsRequest(BaseModel):
    events: list[IntegrityEvent] = Field(default_factory=list)
    typing_stats: list[dict[str, Any]] = Field(default_factory=list)
