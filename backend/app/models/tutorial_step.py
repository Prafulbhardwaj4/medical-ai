from sqlalchemy import Column, Integer, String, Text, Boolean
from app.database import Base


class TutorialStep(Base):
    """One highlighted step in a role's tutorial — admin/dev-authored
    content, not per-hospital data. A step targets one element (via a
    stable data-tutorial-id attribute added to that element in the page's
    own HTML, never a CSS class/ID that might get renamed later for
    unrelated reasons) on one page, for one role, in a fixed order."""
    __tablename__ = "tutorial_steps"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, nullable=False, index=True)  # "patient" | "doctor" | "nurse" | "receptionist" | ... — matches Doctor.role values, plus "patient" for the portal
    page = Column(String, nullable=False)  # page filename without .html, e.g. "my-health", "dashboard"
    step_order = Column(Integer, nullable=False)  # order within this role+page
    target_selector = Column(String, nullable=False)  # e.g. "[data-tutorial-id='book-appointment-btn']"
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    placement = Column(String, nullable=False, default="bottom")  # "top" | "bottom" | "left" | "right" — tooltip position relative to target
    is_active = Column(Boolean, default=True, nullable=False)