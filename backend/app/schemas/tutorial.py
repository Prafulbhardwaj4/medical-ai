from pydantic import BaseModel
from typing import Optional


class TutorialStepOut(BaseModel):
    id: int
    page: str
    step_order: int
    target_selector: str
    title: str
    description: str
    placement: str
    device: str
    click_before: Optional[str] = None

    class Config:
        from_attributes = True


class TutorialStatusOut(BaseModel):
    role: str
    completed: bool