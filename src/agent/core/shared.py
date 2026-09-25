from pydantic import BaseModel

class Window(BaseModel):
    id: str
    app_name: str
    wm_string: str
    

class LastAction(BaseModel):
    type: str
    window_id: str
    element: str

class ActionState(BaseModel):
    id: str
    type: str
    params: list[str]
    target: str
    element: str
    window_id: str
    requires_approval: bool
    status: str


