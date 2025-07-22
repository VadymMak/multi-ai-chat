# app/memory/schemas/prompt_template.py

from pydantic import BaseModel
from typing import Optional


class PromptTemplateBase(BaseModel):
    role_id: int
    name: str
    content: str
    is_default: Optional[bool] = False


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateRead(PromptTemplateBase):
    id: int

    class Config:
        orm_mode = True
