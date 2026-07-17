from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive

class BlacklistedToken(Base):
    __tablename__ = "blacklisted_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    blacklisted_at = Column(DateTime, default=now_ist_naive, nullable=False)