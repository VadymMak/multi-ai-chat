# app/routers/memory.py
from datetime import datetime
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, ConfigDict
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.models import MemoryEntry, Role
from app.memory.manager import MemoryManager

router = APIRouter(prefix="/memory", tags=["Memory"])


# ---------- Schemas ----------

class MemoryIn(BaseModel):
    role_id: int
    project_id: Union[int, str]
    summary: str = Field(..., max_length=1000)
    raw_text: str
    chat_session_id: Optional[str] = None
    is_ai_to_ai: bool = False  # optional, for provenance

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v):
        return "0" if v in (None, "", "default") else str(v).strip()


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Pydantic v2
    id: int
    timestamp: datetime
    summary: str
    project_id: str


# ---------- Create a memory record (long-term, is_summary=True) ----------

@router.post("", response_model=MemoryOut)
def save_memory(item: MemoryIn, db: Session = Depends(get_db)):
    # Validate role exists (clear 404 instead of silent FK-ish failure)
    role = db.get(Role, item.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    mm = MemoryManager(db)

    # Use MemoryManager to handle token counting & safe fields
    entry = mm.store_memory(
        project_id=item.project_id,          # normalized to str by validator
        role_id=item.role_id,
        summary=item.summary,
        raw_text=item.raw_text,
        chat_session_id=item.chat_session_id,
        is_ai_to_ai=item.is_ai_to_ai,
    )
    return entry


# ---------- Get last N memories for a role (optionally filter by project) ----------

@router.get("/{role_id}", response_model=List[MemoryOut])
def list_memory(
    role_id: int,
    limit: int = Query(5, ge=1, le=200),
    project_id: Optional[str] = Query(None, description="Optional project filter"),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    q = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.role_id == role_id, MemoryEntry.is_summary == True)  # noqa: E712
    )
    if project_id:
        q = q.filter(MemoryEntry.project_id == str(project_id).strip())

    entries = (
        q.order_by(MemoryEntry.timestamp.desc())
        .limit(limit)
        .all()
    )
    return entries
