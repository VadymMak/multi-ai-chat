"""
app_api.py — REST API for the mobile app.

All endpoints require JWT Bearer auth (token from /api/auth/login).
Registered in main.py under prefix /api/app.

POST /api/app/message          (multipart/form-data)
POST /api/app/parse-reminder   (JSON) — parse NL reminder → {fire_at, text}
GET  /api/app/notes
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.deps import get_current_active_user, get_db
from app.memory.models import User
from app.services.brain_assistant import (
    answer_from_notes,
    chat,
    delete_note as delete_note_svc,
    describe_image,
    extract_text,
    get_or_create_user_project,
    parse_reminder_text,
    save_note,
    search_notes,
    transcribe,
    web_answer,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app", tags=["app"])

_VALID_MODES = {"chat", "notes", "web", "save"}
_VALID_MODELS = {"gpt", "claude", "grok", "glm"}

# ── Directive patterns for image routing ─────────────────────
_REMINDER_RE = re.compile(
    r"^\s*(напомн\w*|напомин\w*|remind\w*|reminder)\b[\s,:\-—]*",
    re.IGNORECASE | re.UNICODE,
)
_OCR_QUERY_RE = re.compile(
    r"\b(что\s+(тут|здесь|на\s*(фото|фотографии|изображении))?\s*написано"
    r"|прочита[йте]|прочти"
    r"|что\s+написа[лн][ои]?"
    r"|read\s+(it|this|out|aloud|text))\b",
    re.IGNORECASE | re.UNICODE,
)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _geolocate_ip(ip: str) -> str:
    """Return 'City, Country' from IP using ipapi.co free tier. Empty string on failure."""
    if not ip or ip in ("127.0.0.1", "::1", ""):
        return ""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"https://ipapi.co/{ip}/json/")
            if r.status_code == 200:
                data = r.json()
                city = data.get("city") or ""
                country = data.get("country_name") or ""
                loc = f"{city}, {country}".strip(", ")
                logger.info("[app/geo] ip=%s → %r", ip, loc)
                return loc
    except Exception as exc:
        logger.debug("[app/geo] geolocate failed ip=%s: %s", ip, exc)
    return ""


def _session_key(user_id: int) -> int:
    """Conversation history key for mobile users.

    Uses negative IDs so mobile history never collides with Telegram user IDs
    (which are always positive and typically 6-10 digits).
    """
    return -user_id


@router.post("/message")
async def message(
    request: Request,
    mode: str = Form(..., description="chat | notes | web | save"),
    model: Optional[str] = Form(None, description="gpt | claude | grok | glm (for chat/web mode)"),
    text: Optional[str] = Form(None),
    location: Optional[str] = Form(None, description="User location hint, e.g. 'Trenčín, Slovakia'"),
    tz: Optional[str] = Form(None, description="IANA timezone, e.g. 'Europe/Bratislava'"),
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

    # ── Resolve location (explicit > IP geo) ─────────────────────────────────
    resolved_location: str = (location or "").strip()
    if not resolved_location and getattr(settings, "ENABLE_IP_GEO", False):
        client_ip = _get_client_ip(request)
        resolved_location = await _geolocate_ip(client_ip)

    # ── Resolve timezone (client-supplied > server default) ───────────────────
    resolved_tz: str = (tz or "").strip() or settings.DEFAULT_TIMEZONE

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

    # ── Reminder detection: text & voice, no image ────────────────────────────
    # Runs after prompt is resolved (transcribed or typed), before any other routing.
    # Image+reminder is handled separately in the image-directive block below.
    if prompt and image is None and _REMINDER_RE.search(prompt):
        try:
            fire_data = await parse_reminder_text(prompt, resolved_tz)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not parse reminder: {exc}")
        body = _REMINDER_RE.sub("", prompt, 1).strip() or fire_data.get("text", "")
        logger.info("[app/message] reminder user=%d tz=%s fire_at=%s", current_user.id, resolved_tz, fire_data["fire_at"])
        return {"kind": "reminder", "fire_at": fire_data["fire_at"], "text": body}

    # --- Read image bytes ---
    if image is not None:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty")
        kind = "photo"

    # ── Image-directive routing ───────────────────────────────────────────────
    if image_bytes:
        # 1. Reminder + photo → OCR body from image, fire_at from caption/voice
        if prompt and _REMINDER_RE.search(prompt):
            try:
                ocr_text = await extract_text(image_bytes)
            except Exception as exc:
                logger.error("[app/message] OCR failed user=%d: %s", current_user.id, exc)
                raise HTTPException(status_code=502, detail=f"OCR failed: {exc}")
            directive = f"{prompt}\nТекст на фото: {ocr_text}" if ocr_text.strip() else prompt
            try:
                fire_data = await parse_reminder_text(directive, resolved_tz)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Could not parse reminder: {exc}")
            body = ocr_text.strip() or fire_data.get("text", "")
            logger.info("[app/message] reminder+photo user=%d tz=%s fire_at=%s", current_user.id, resolved_tz, fire_data["fire_at"])
            return {"kind": "reminder", "fire_at": fire_data["fire_at"], "text": body}

        # 2. Explicit OCR query: "что написано", "прочитай", "read this"
        if _OCR_QUERY_RE.search(prompt or ""):
            try:
                ocr_text = await extract_text(image_bytes)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"OCR failed: {exc}")
            return {
                "mode": "chat",
                "model_used": "gpt-4o",
                "kind": kind,
                "answer": ocr_text.strip() or "Текст на изображении не обнаружен.",
                "sources": [],
                "saved_title": None,
            }

        # 3. Save mode + photo → OCR text as note body; fallback to describe
        if mode == "save":
            try:
                ocr_text = await extract_text(image_bytes)
            except Exception:
                ocr_text = ""
            if ocr_text.strip():
                full = f"{prompt}\n{ocr_text}".strip() if prompt else ocr_text.strip()
                result = await save_note(project.id, full, "ocr", extra_tags=["photo", "ocr"])
            else:
                try:
                    description = await describe_image(image_bytes)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail=f"Image description failed: {exc}")
                full = f"{prompt}\n{description}".strip() if prompt else description
                result = await save_note(project.id, full, kind)
            return {
                "mode": "save",
                "model_used": None,
                "kind": kind,
                "answer": None,
                "sources": [],
                "saved_title": result["saved_title"],
            }

        # 4. Default: force vision chat (web / notes cannot process images)
        mode = "chat"
        if not prompt:
            prompt = "Что на изображении?"

    # ── save (text / voice, no image) ────────────────────────
    if mode == "save":
        if not prompt:
            raise HTTPException(
                status_code=400,
                detail="Nothing to save: provide text, audio, or image",
            )
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
                location=resolved_location,
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
            answer, sources = await web_answer(session_key=sk, query=prompt, location=resolved_location)
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


class _ParseReminderRequest(BaseModel):
    text: str
    tz: Optional[str] = None


@router.post("/parse-reminder")
async def parse_reminder(
    req: _ParseReminderRequest,
    current_user: User = Depends(get_current_active_user),
):
    """Parse a natural-language reminder string → {fire_at: UTC ISO 'Z' str, text: str}.

    Delegates to brain_assistant.parse_reminder_text which injects the current local time
    in the user's timezone so relative ("in 2 minutes") and absolute ("at 9am") phrases
    resolve correctly. fire_at is always returned as UTC with 'Z' suffix.
    """
    resolved_tz = (req.tz or "").strip() or settings.DEFAULT_TIMEZONE
    try:
        data = await parse_reminder_text(req.text, resolved_tz)
        return {"fire_at": data["fire_at"], "text": data["text"]}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse reminder: {exc}")
    except Exception as exc:
        logger.error("[app/parse-reminder] failed user=%d: %s", current_user.id, exc)
        raise HTTPException(status_code=502, detail=f"Parse failed: {exc}")


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
