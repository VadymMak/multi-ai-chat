# app/routers/memory.py
import json
import logging
from datetime import datetime
from typing import List, Optional, Union

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator, ConfigDict
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.models import CanonItem, MemoryEntry, Role, User
from app.memory.manager import MemoryManager
from app.deps import get_current_active_user

logger = logging.getLogger(__name__)

# ── Lazy OpenAI client ────────────────────────────────────────────
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        from app.config.settings import settings
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _openai_client = OpenAI(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _openai_client

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


# ══════════════════════════════════════════════════════════════════
# Session Memory — save / retrieve AI session summaries
# ══════════════════════════════════════════════════════════════════

_SESSION_SUMMARY_PROMPT = """\
Summarize this development session in 3-5 bullet points.
Focus on: decisions made, problems solved, code created, next steps.
Be concise but specific. Include file names and technical details.

Session content:
{content}"""


# ---------- Schemas ----------

class SaveSessionSummaryRequest(BaseModel):
    """Request to summarize and persist a development session."""
    project_id: int
    session_content: str = Field(..., min_length=10)
    topics: List[str] = Field(default_factory=list)


class SaveSessionSummaryResponse(BaseModel):
    """Result of saving a session summary."""
    success: bool
    summary_id: Optional[int]
    summary: str


class SessionSummaryOut(BaseModel):
    """A single session summary entry."""
    id: int
    title: str
    body: str
    tags: Optional[List[str]]
    created_at: datetime


# ---------- POST /memory/save-session-summary ----------

@router.post("/save-session-summary", response_model=SaveSessionSummaryResponse)
async def save_session_summary(
    request: SaveSessionSummaryRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Summarize a development session with GPT-4o-mini and save it to canon_items
    as type='SESSION_SUMMARY'.

    The summary is stored with:
    - title:  'Session YYYY-MM-DD HH:MM'
    - body:   3-5 bullet-point summary from GPT-4o-mini
    - tags:   caller-supplied topics list
    - terms:  space-joined topics for full-text search

    The entry is then searchable via list_canon_items(type='session_summary')
    and will appear in build_context_for_query results.
    """
    try:
        # 1. Call GPT-4o-mini to summarize
        client = _get_openai_client()
        prompt = _SESSION_SUMMARY_PROMPT.format(
            content=request.session_content[:8000]
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        summary_text: str = response.choices[0].message.content.strip()
        estimated_tokens = len(summary_text.split())

        print(
            f"📝 [SessionMemory] GPT-4o-mini summary generated "
            f"(~{estimated_tokens} tokens) for project {request.project_id}"
        )

        # 2. Save to canon_items via ORM (bypasses ENABLE_CANON flag)
        now = datetime.utcnow()
        title = f"Session {now.strftime('%Y-%m-%d %H:%M')}"

        item = CanonItem(
            project_id=str(request.project_id),
            project_id_int=request.project_id,
            role_id=None,
            type="SESSION_SUMMARY",
            title=title[:256],
            body=summary_text,
            tags=request.topics or None,
            terms=" ".join(request.topics)[:1000] if request.topics else None,
            created_at=now,
            is_active=True,
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        print(
            f"💾 [SessionMemory] Saved to canon_items id={item.id} "
            f"project={request.project_id} topics={request.topics}"
        )

        return SaveSessionSummaryResponse(
            success=True,
            summary_id=item.id,
            summary=summary_text,
        )

    except Exception as e:
        logger.error("save_session_summary error: %s", e)
        print(f"❌ [SessionMemory] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------- GET /memory/session-summaries/{project_id} ----------

@router.get("/session-summaries/{project_id}", response_model=List[SessionSummaryOut])
async def get_session_summaries(
    project_id: int,
    limit: int = Query(5, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Return the last N session summaries for a project, newest first.

    Query params:
    - limit (default 5, max 50)
    """
    try:
        items = (
            db.query(CanonItem)
            .filter(
                CanonItem.project_id == str(project_id),
                CanonItem.type == "SESSION_SUMMARY",
                CanonItem.is_active == True,  # noqa: E712
            )
            .order_by(CanonItem.created_at.desc())
            .limit(limit)
            .all()
        )

        print(
            f"📋 [SessionMemory] Returning {len(items)} summaries "
            f"for project {project_id}"
        )

        return [
            SessionSummaryOut(
                id=item.id,
                title=item.title,
                body=item.body,
                tags=item.tags if isinstance(item.tags, list) else [],
                created_at=item.created_at,
            )
            for item in items
        ]

    except Exception as e:
        logger.error("get_session_summaries error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))