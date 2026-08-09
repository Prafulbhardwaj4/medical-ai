from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class SuggestionReply(Base):
    """A lightweight Q&A thread attached to a Suggestion — Super Admin can
    ask the submitting staff member something, staff can reply free text.
    Not the hospital admin<->staff ChatMessage system; this is scoped to a
    single suggestion and crosses into Super Admin's separate auth."""
    __tablename__ = "suggestion_replies"

    id = Column(Integer, primary_key=True, index=True)
    suggestion_id = Column(Integer, ForeignKey("suggestions.id"), nullable=False)
    sender = Column(String, nullable=False)  # "super_admin" | "staff"
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)