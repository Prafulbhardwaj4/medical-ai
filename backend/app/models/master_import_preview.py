from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class MasterImportPreview(Base):
    """The parsed master-list Excel file, kept on the server between 'Preview' and 'Confirm'.
    Platform-wide (no hospital). Short-lived, single use, tied to the super admin who uploaded it."""
    __tablename__ = "master_import_previews"

    id = Column(String, primary_key=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)   # "tests" / "medicines"
    file_name = Column(String, nullable=True)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)