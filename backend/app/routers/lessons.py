"""
lessons.py — CRUD API for user lessons (saved AI answers).

All endpoints require JWT auth. Every query is scoped to the current user.
prefix="/api/app/lessons"
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.deps import get_current_active_user, get_db
from app.memory.models import Lesson, User

router = APIRouter(prefix="/app/lessons", tags=["lessons"])


# ── Pydantic schemas ──────────────────────────────────────────

class LessonCreate(BaseModel):
    title: str
    content: str
    tags: Optional[str] = None
    source: Optional[str] = None


class LessonUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None


class LessonOut(BaseModel):
    id: int
    title: str
    content: str
    tags: Optional[str]
    source: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────

def _get_own_or_404(lesson_id: int, user: User, db: Session) -> Lesson:
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id,
        Lesson.user_id == user.id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    return lesson


# ── Endpoints ─────────────────────────────────────────────────

@router.post("", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    body: LessonCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lesson = Lesson(
        user_id=current_user.id,
        title=body.title.strip(),
        content=body.content,
        tags=body.tags,
        source=body.source,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


@router.get("", response_model=List[LessonOut])
async def list_lessons(
    q: Optional[str] = Query(None, description="Full-text search over title + content"),
    tag: Optional[str] = Query(None, description="Filter by tag (exact match in CSV)"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(Lesson).filter(Lesson.user_id == current_user.id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Lesson.title.ilike(like), Lesson.content.ilike(like))
        )

    if tag:
        # tags stored as CSV — match as substring so "python" matches "ai,python,async"
        query = query.filter(Lesson.tags.ilike(f"%{tag}%"))

    lessons = query.order_by(Lesson.created_at.desc()).all()
    return lessons


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return _get_own_or_404(lesson_id, current_user, db)


@router.patch("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int,
    body: LessonUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lesson = _get_own_or_404(lesson_id, current_user, db)
    if body.title is not None:
        lesson.title = body.title.strip()
    if body.content is not None:
        lesson.content = body.content
    if body.tags is not None:
        lesson.tags = body.tags
    lesson.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lesson)
    return lesson


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    lesson = _get_own_or_404(lesson_id, current_user, db)
    db.delete(lesson)
    db.commit()
