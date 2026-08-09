from pydantic import BaseModel
from typing import Optional


VALID_SUGGESTION_STATUSES = {"sent", "seen", "in_progress", "rejected", "completed"}


class SuggestionIn(BaseModel):
    message: str


class SuggestionStatusIn(BaseModel):
    status: str
    rejection_reason: Optional[str] = None