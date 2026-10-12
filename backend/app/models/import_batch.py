from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class ImportBatch(Base):
    """One applied Excel import (medicines or tests). Used for the history list and for undo."""
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # "medicines" / "tests"
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_by_role = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="applied")  # "applied" / "undone"
    summary = Column(Text, nullable=True)  # JSON with the counts
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)
    undone_at = Column(DateTime, nullable=True)
    undone_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)


class ImportBatchItem(Base):
    """One thing an import created or changed. before_json/after_json let undo restore updates."""
    __tablename__ = "import_batch_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=False, index=True)
    entity = Column(String, nullable=False)   # "medicine" / "medicine_batch" / later "test" ...
    entity_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)   # "created" / "updated"
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)


class ImportPreview(Base):
    """The parsed file, kept on the server between 'Preview' and 'Confirm' (expires, single use)."""
    __tablename__ = "import_previews"

    id = Column(String, primary_key=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    kind = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)