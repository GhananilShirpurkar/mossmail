from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class State(StrEnum):
    REVIEW = "Needs review"
    DEFER = "Safe to defer"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    thread_id: str
    sender: str
    sender_name: str
    recipients: list[str]
    subject: str
    body: str
    received_at: AwareDatetime
    references: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    trusted_bulk: bool = False
    has_attachments: bool = False
    parse_uncertain: bool = False
    follow_up: bool = False
    deadline: AwareDatetime | None = None
    revision: int = 0


class Score(BaseModel):
    risk: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    method: str
    evidence: list[str]


class Override(BaseModel):
    state: State
    revision: int


class Decision(BaseModel):
    state: State
    score: Score
    reasons: list[str]
    action: str
    review_at: datetime | None = None
    protected: bool = False
    overridden: bool = False


class SummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=450)
    proposed_action: str = Field(min_length=1, max_length=240)


class Summary(SummaryPayload):
    source: Literal["local_ai", "demo_fallback"]
    model: str | None = None
    note: str
