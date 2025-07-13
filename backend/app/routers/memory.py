# app/routers/memory.py
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.memory.models import MemoryEntry, Role
from tiktoken import encoding_for_model   # pip install tiktoken

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryIn(BaseModel):
    role_id: int
    summary: str = Field(..., max_length=1000)
    raw_text: str


class MemoryOut(BaseModel):
    id: int
    timestamp: datetime
    summary: str

    class Config:
        orm_mode = True


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    enc = encoding_for_model(model)
    return len(enc.encode(text))


# ----------  Сохранить новую запись памяти  ----------
@router.post("/", response_model=MemoryOut)
def save_memory(item: MemoryIn, db: Session = Depends(get_db)):
    role = db.query(Role).get(item.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    tokens = count_tokens(item.raw_text)
    entry = MemoryEntry(
        role_id=item.role_id,
        tokens=tokens,
        summary=item.summary,
        raw_text=item.raw_text,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ----------  Получить последние N записей по роли  ----------
@router.get("/{role_id}", response_model=List[MemoryOut])
def list_memory(role_id: int, limit: int = 5, db: Session = Depends(get_db)):
    role = db.query(Role).get(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    entries = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.role_id == role_id)
        .order_by(MemoryEntry.timestamp.desc())
        .limit(limit)
        .all()
    )
    return entries
