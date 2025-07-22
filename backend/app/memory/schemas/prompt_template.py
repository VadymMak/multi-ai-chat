# app/memory/schemas/prompt_template.py
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator, ConfigDict


class PromptTemplateBase(BaseModel):
    role_id: int
    name: str
    content: str
    is_default: bool = False

    @field_validator("role_id")
    @classmethod
    def role_id_positive(cls, v: int) -> int:
        if v is None or int(v) <= 0:
            raise ValueError("role_id must be a positive integer")
        return int(v)

    @field_validator("name")
    @classmethod
    def name_clean(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name cannot be empty")
        if len(s) > 100:
            raise ValueError("name must be at most 100 characters")
        return s

    @field_validator("content")
    @classmethod
    def content_clean(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("content cannot be empty")
        return s


class PromptTemplateCreate(PromptTemplateBase):
    pass


class PromptTemplateRead(PromptTemplateBase):
    id: int
    # Pydantic v2: allow constructing from SQLAlchemy ORM objects
    model_config = ConfigDict(from_attributes=True)
