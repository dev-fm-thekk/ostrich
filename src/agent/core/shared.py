from pydantic import BaseModel

class Window(BaseModel):
    id: str
    app: str
    handle: str
    title: str
    status: str

class LastAction(BaseModel):
    type: str
    window_id: str
    element: str

class ActionState(BaseModel):
    id: str
    type: str
    params: dict
    target: str
    element: str
    window_id: str
    requires_approval: bool
    status: str


