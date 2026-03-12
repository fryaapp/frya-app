from pydantic import BaseModel


class PlannedAction(BaseModel):
    action_type: str
    reversible: bool = False
    requires_approval: bool = True
    payload: dict
