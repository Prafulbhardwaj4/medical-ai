from sqlalchemy import Column, String, DateTime
from app.database import Base


class CaptchaChallenge(Base):
    """Server-side captcha. The answer never leaves the server; the client
    only holds the opaque id. Rows are deleted on first use (single-use) and
    expired rows are purged whenever a new challenge is issued."""
    __tablename__ = "captcha_challenges"

    id = Column(String(64), primary_key=True)
    answer = Column(String(16), nullable=False)  # stored lowercase
    expires_at = Column(DateTime, nullable=False, index=True)  # UTC naive