"""
app_api.py — REST API for the mobile app.

All endpoints require JWT Bearer auth (token from /api/auth/login).
Registered in main.py under prefix /api/app.

POST /api/app/message  (multipart/form-data)
GET  /api/app/notes
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.brain_assistant import (
    answer_from_notes,
    chat,
    delete_note as delete_note_svc,
    describe_image,
    get_or_create_user_project,
    save_note,
    search_notes,
    transcribe,
    web_answer,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app", tags=["app"])

_VALID_MODES = {"chat", "notes", "web", "save"}
_VALID_MODELS = {"gpt", "claude", "grok"}


def _session_key(user_id: int) -> int:
    """Conversation history key for mobile users.

    Uses negative IDs so mobile history never collides with Telegram user IDs
    (which are always positive and typically 6-10 digits).
    """
    return -user_id


@router.post("/message")
async def message(
    mode: str = Form(..., description="chat | notes | web | save"),
    model: Optional[str] = Form(None, description="gpt | claude | grok (for chat/web mode)"),
    text: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Unified entry-point for the mobile app.

    Resolution order:
      1. If ``audio`` is provided it is transcribed first; the transcript
         becomes ``text`` (overrides any text field).
      2. If ``image`` is provided its bytes are passed to the vision model
         (chat) or described and saved (save mode).
      3. Routes by ``mode`` to the correct Brain service.

    Returns JSON::

        {
          "mode":        str,
          "model_used":  str | null,
          "kind":        "text" | "voice" | "photo",
          "answer":      str | null,
          "sources":     list,
          "saved_title": str | null
        }
    """
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"mode must be one of {sorted(_VALID_MODES)}",
        )
    if model and model not in _VALID_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"model must be one of {sorted(_VALID_MODELS)}",
        )

    project = get_or_create_user_project(db, current_user)
    sk = _session_key(current_user.id)

    prompt: str = text or ""
    kind: str = "text"
    image_bytes: Optional[bytes] = None

    # --- Transcribe audio first ---
    if audio is not None:
        raw = await audio.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty")
        try:
            prompt = await transcribe(raw)
            kind = "voice"
            logger.info("[app/message] user=%d transcribed: %r", current_user.id, prompt[:80])
        except Exception as exc:
            logger.error("[app/message] transcription failed user=%d: %s", current_user.id, exc)
            raise HTTPException(status_code=502, detail=f"Audio transcription failed: {exc}")

    # --- Read image bytes ---
    if image is not None:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty")
        kind = "photo"

    # ── Image present + non-save mode → force vision chat ────────────────────
    # web / notes cannot process images; image always wins except in save mode.
    if image_bytes and mode != "save":
        mode = "chat"
        if not prompt:
            prompt = "Что на изображении?"

    # ── save ─────────────────────────────────────────────────
    if mode == "save":
        if not prompt and not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="Nothing to save: provide text, audio, or image",
            )
        if image_bytes:
            try:
                description = await describe_image(image_bytes)
                prompt = f"{prompt}\n{description}".strip() if prompt else description
            except Exception as exc:
                logger.error("[app/message] image description failed: %s", exc)
                raise HTTPException(status_code=502, detail=f"Image description failed: {exc}")

        result = await save_note(project.id, prompt, kind)
        return {
            "mode": "save",
            "model_used": None,
            "kind": kind,
            "answer": None,
            "sources": [],
            "saved_title": result["saved_title"],
        }

    # ── chat ─────────────────────────────────────────────────
    if mode == "chat":
        if not prompt and not image_bytes:
            raise HTTPException(
                status_code=400,
                detail="Provide text, audio, or image for chat mode",
            )
        try:
            answer, provider_used = await chat(
                session_key=sk,
                prompt=prompt,
                preferred_provider=model,
                image_bytes=image_bytes,
            )
        except Exception as exc:
            logger.error("[app/message] chat failed user=%d: %s", current_user.id, exc)
            raise HTTPException(status_code=502, detail=f"Chat failed: {exc}")

        return {
            "mode": "chat",
            "model_used": provider_used,
            "kind": kind,
            "answer": answer,
            "sources": [],
            "saved_title": None,
        }

    # ── notes (brain Q&A) ─────────────────────────────────────
    if mode == "notes":
        if not prompt:
            raise HTTPException(
                status_code=400,
                detail="Provide a query for notes search (text or audio)",
            )
        try:
            answer, hits = await answer_from_notes(db, project.id, prompt)
        except Exception as exc:
            logger.error("[app/message] notes search failed user=%d: %s", current_user.id, exc)
            raise HTTPException(status_code=502, detail=f"Notes search failed: {exc}")

        if not hits:
            return {
                "mode": "notes",
                "model_used": "gpt-4o",
                "kind": kind,
                "answer": "Ничего не нашлось по этому запросу.",
                "sources": [],
                "saved_title": None,
            }
        return {
            "mode": "notes",
            "model_used": "gpt-4o",
            "kind": kind,
            "answer": answer,
            "sources": hits,
            "saved_title": None,
        }

    # ── web ───────────────────────────────────────────────────
    if mode == "web":
        if not prompt:
            raise HTTPException(
                status_code=400,
                detail="Provide a query for web search (text or audio)",
            )
        try:
            answer, sources = await web_answer(session_key=sk, query=prompt)
        except Exception as exc:
            logger.error("[app/message] web search failed user=%d: %s", current_user.id, exc)
            raise HTTPException(status_code=502, detail=f"Web search failed: {exc}")

        return {
            "mode": "web",
            "model_used": "gpt-4o",
            "kind": kind,
            "answer": answer,
            "sources": sources,
            "saved_title": None,
        }

    # Should be unreachable
    raise HTTPException(status_code=500, detail="Unhandled mode")


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Soft-delete a note that belongs to the current user's project.

    Sets ``canon_items.is_active = False`` and ``memory_entries.deleted = True``
    so the note disappears from both the notes list and semantic search.
    The rows are NOT hard-deleted (reversible).
    Returns ``{"deleted": true, "id": <note_id>}``.
    """
    project = get_or_create_user_project(db, current_user)
    try:
        return await delete_note_svc(db, project.id, note_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(
            "[app/notes] delete failed user=%d note=%d: %s",
            current_user.id, note_id, exc,
        )
        raise HTTPException(status_code=502, detail=f"Delete failed: {exc}")


@router.get("/notes")
async def notes(
    query: str = Query(default="", description="Semantic search query; empty = newest first"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List or semantically search the current user's notes.

    Returns a list of ``{id, title, body, tags, created_at}`` dicts,
    newest first when no query is given.
    """
    project = get_or_create_user_project(db, current_user)
    try:
        return await search_notes(db, project.id, query=query, limit=limit)
    except Exception as exc:
        logger.error("[app/notes] failed user=%d: %s", current_user.id, exc)
        raise HTTPException(status_code=502, detail=f"Notes search failed: {exc}")
