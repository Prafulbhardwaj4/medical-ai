from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from app.database import Base

class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    room_number = Column(String, nullable=True)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)