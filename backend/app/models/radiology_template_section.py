from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class RadiologyTemplateSection(Base):
    """A single named finding-section of a radiology template (e.g. 'Liver',
    'Kidneys' under USG Abdomen). Parallels TestCatalogParameter, but holds
    pre-written narrative default text instead of a numeric reference range."""
    __tablename__ = "radiology_template_sections"

    id = Column(Integer, primary_key=True, index=True)
    radiology_template_id = Column(Integer, ForeignKey("radiology_templates.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "Liver", "Gall Bladder", "Kidneys"
    default_finding_text = Column(Text, nullable=False, default="")  # the "normal" default the radiologist pre-writes once, per template (item 2)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)