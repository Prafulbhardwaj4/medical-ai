from pydantic import BaseModel


class TutorialStepOut(BaseModel):
    id: int
    page: str
    step_order: int
    target_selector: str
    title: str
    description: str
    placement: str

    class Config:
        from_attributes = True


class TutorialStatusOut(BaseModel):
    role: str
    completed: bool