from pydantic import BaseModel
from app.utils.text_safety import SafeTextModel
from typing import Optional


VALID_SUGGESTION_STATUSES = {"sent", "seen", "in_progress", "rejected", "completed"}


class SuggestionIn(SafeTextModel):
    message: str


class SuggestionEditIn(SafeTextModel):
    message: str


class SuggestionStatusIn(SafeTextModel):
    status: str
    rejection_reason: Optional[str] = None


class SuggestionReplyIn(SafeTextModel):
    message: str