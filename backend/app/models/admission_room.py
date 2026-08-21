from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionRoom(Base):
    """A physical room within an admission ward type — e.g. General Ward's
    room 101 might have 4 beds while room 102 has 2. Bed labels are generated
    per-room as "{room_number}-{n}" so two rooms in the same ward never
    collide. A ward type's total_beds column is kept in sync as the sum of
    its rooms' beds_count every time a room is added, edited, or deleted —
    see _recompute_total_beds in routers/admissions.py."""
    __tablename__ = "admission_rooms"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    ward_type_id = Column(Integer, ForeignKey("admission_ward_types.id"), nullable=False)
    room_number = Column(String, nullable=False)
    beds_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=now_ist_naive)