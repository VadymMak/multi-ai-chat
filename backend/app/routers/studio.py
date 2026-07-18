"""
Studio integration router.
Accepts calls from vendshop.shop/studio to:
- GET context from Brain for user messages
- SAVE session summaries to Brain
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.memory.manager import MemoryManager
from app.services.smart_context import build_smart_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/studio-context", tags=["studio"])

# ─────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────
BRAIN_API_KEY = os.getenv("BRAIN_API_KEY", "")


def _check_auth(request: Request) -> None:
    """Simple API key auth for Studio ↔ Brain communication."""
    if not BRAIN_API_KEY:
        return  # Key not configured — allow all (dev mode)
    key = request.headers.get("x-brain-api-key", "")
    if key != BRAIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized — invalid x-brain-api-key")


# ─────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────
class ContextRequest(BaseModel):
    query: str
    project_id: int = 22  # vendly-storefront project


class SaveRequest(BaseModel):
    project_id: int = 22
    content: str
    topics: List[str] = []


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────
@router.post("")
async def get_studio_context(
    req_body: ContextRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Build Brain context for a Studio user message.
    Called by vendshop.shop/api/studio/chat before getAgentDecision.
    Returns up to 2000 chars of relevant context.
    """
    _check_auth(request)

    memory = MemoryManager(db)
    try:
        context = await build_smart_context(
            project_id=req_body.project_id,
            role_id=0,
            query=req_body.query,
            session_id=str(uuid4()),
            db=db,
            memory=memory,
        )
        return {"context": (context or "")[:2000], "project_id": req_body.project_id}
    except Exception as exc:
        logger.error("studio-context GET error: %s", exc)
        return {"context": "", "error": str(exc)}


@router.post("/save")
async def save_studio_summary(
    req_body: SaveRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Save a Studio session summary to Brain.
    Called fire-and-forget by vendshop.shop after successful generation.
    """
    _check_auth(request)

    try:
        now = datetime.now(timezone.utc)
        tags_json = json.dumps(req_body.topics) if req_body.topics else "[]"
        title = f"Studio {now.strftime('%Y-%m-%d %H:%M')}"

        db.execute(
            text("""
                INSERT INTO canon_items
                    (project_id, project_id_int, role_id, type, title, body, tags, created_at, is_active)
                VALUES
                    (:project_id, :project_id_int, NULL, 'SESSION_SUMMARY',
                     :title, :body, cast(:tags AS jsonb), :created_at, TRUE)
            """),
            {
                "project_id": str(req_body.project_id),
                "project_id_int": req_body.project_id,
                "title": title[:256],
                "body": req_body.content[:4000],
                "tags": tags_json,
                "created_at": now,
            },
        )
        db.commit()
        logger.info("studio-context SAVE: project=%s title=%s", req_body.project_id, title)
        return {"saved": True, "title": title}
    except Exception as exc:
        db.rollback()
        logger.error("studio-context SAVE error: %s", exc)
        return {"saved": False, "error": str(exc)}
