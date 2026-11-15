from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive

class BlacklistedToken(Base):
    __tablename__ = "blacklisted_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=True)  # old rows only; new rows store token_hash
    token_hash = Column(String(64), unique=True, index=True, nullable=True)  # SHA-256 hex of the token
    blacklisted_at = Column(DateTime, default=now_ist_naive, nullable=False)