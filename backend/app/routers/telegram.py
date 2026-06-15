"""
Telegram bot webhook handler — Brain MCP input portal.

POST /api/telegram/webhook

Receives Telegram updates, validates the secret token,
filters by allowed user IDs, and stores messages in Brain:
- canon_items (type=INBOX) — for build_context_for_query / list_canon_items
- memory_entries + pgvector embedding — for search_conversation_memory
  (fixed session id: "telegram-inbox")
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from openai import OpenAI
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.memory.db import SessionLocal
from app.memory.models import CanonItem, MemoryEntry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

_PROJECT_ID_STR = str(settings.TELEGRAM_DEFAULT_PROJECT_ID)
_PROJECT_ID_INT = settings.TELEGRAM_DEFAULT_PROJECT_ID
_SESSION_ID = "telegram-inbox"

# ── Lazy OpenAI client (same pattern as memory.py) ────────────────
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
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


# ── Telegram API helpers ──────────────────────────────────────────

def _tg_base() -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def _tg_get_file_path(file_id: str) -> str:
    """Return the file_path for a given Telegram file_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{_tg_base()}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        return r.json()["result"]["file_path"]


async def _tg_download_file(file_path: str) -> bytes:
    """Download a file from Telegram's CDN."""
    url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def _tg_send_message(chat_id: int, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{_tg_base()}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception as exc:
        logger.warning("[telegram] sendMessage failed: %s", exc)


# ── Content extraction ────────────────────────────────────────────

async def _extract_content(message: Dict[str, Any]) -> tuple[str, str]:
    """Return (content, kind). kind ∈ {text, voice, photo}."""

    # Plain text
    if "text" in message:
        return message["text"], "text"

    # Voice or audio → transcribe with Whisper
    if "voice" in message or "audio" in message:
        media = message.get("voice") or message.get("audio")
        fp = await _tg_get_file_path(media["file_id"])
        data = await _tg_download_file(fp)
        client = _get_openai_client()
        buf = io.BytesIO(data)
        buf.name = "voice.oga"  # Whisper accepts .oga directly
        result = client.audio.transcriptions.create(model="whisper-1", file=buf)
        return f"[voice transcript] {result.text}", "voice"

    # Photo → GPT-4o vision description
    if "photo" in message:
        largest = message["photo"][-1]
        caption: str = message.get("caption", "")
        fp = await _tg_get_file_path(largest["file_id"])
        data = await _tg_download_file(fp)
        b64 = base64.b64encode(data).decode()
        prompt_text = "Describe this image concisely. Focus on the main subject and any visible text."
        if caption:
            prompt_text += f"\n\nCaption: {caption}"
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=500,
        )
        description = response.choices[0].message.content.strip()
        full = f"[screenshot] {description}"
        if caption:
            full += f"\nCaption: {caption}"
        return full, "photo"

    return "", "unknown"


# ── Brain persistence ─────────────────────────────────────────────

def _write_to_brain(db: Session, content: str, kind: str) -> MemoryEntry:
    """
    Dual-write:
      1. CanonItem(type=INBOX) — surfaces in build_context_for_query / list_canon_items
         Bypasses ENABLE_CANON flag (same pattern as save_session_summary).
      2. MemoryEntry(chat_session_id=telegram-inbox) — for search_conversation_memory.
    Returns the MemoryEntry so the caller can attach the embedding.
    """
    now = datetime.utcnow()
    title = content[:80]

    item = CanonItem(
        project_id=_PROJECT_ID_STR,
        project_id_int=_PROJECT_ID_INT,
        role_id=settings.TELEGRAM_ROLE_ID,
        type="INBOX",
        title=title,
        body=content,
        tags=["telegram", kind],
        terms=content[:1000],
        created_at=now,
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("[telegram] CanonItem id=%d type=INBOX kind=%s", item.id, kind)

    entry = MemoryEntry(
        project_id=_PROJECT_ID_STR,
        project_id_int=_PROJECT_ID_INT,
        role_id=settings.TELEGRAM_ROLE_ID,
        chat_session_id=_SESSION_ID,
        summary=content[:2000],
        raw_text=content,
        is_summary=True,
        is_ai_to_ai=False,
        timestamp=now,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("[telegram] MemoryEntry id=%d session=%s", entry.id, _SESSION_ID)

    return entry


# ── Async background task ─────────────────────────────────────────

async def _process_update(message: Dict[str, Any]) -> None:
    """Extract content, persist to Brain, confirm to user. Never raises."""
    chat_id: int = message.get("chat", {}).get("id", 0)
    try:
        content, kind = await _extract_content(message)
        if not content:
            logger.info("[telegram] Unsupported message type — skipped")
            return

        db = SessionLocal()
        try:
            entry = _write_to_brain(db, content, kind)
            try:
                from app.services.vector_service import store_message_with_embedding
                store_message_with_embedding(db, entry.id, content)
                logger.info("[telegram] Embedding stored for entry %d", entry.id)
            except Exception as emb_exc:
                logger.warning("[telegram] Embedding skipped: %s", emb_exc)
        finally:
            db.close()

        title = content[:80]
        await _tg_send_message(
            chat_id,
            f"✅ Saved to Brain (project {_PROJECT_ID_INT}): {title}",
        )

    except Exception as exc:
        logger.error("[telegram] _process_update error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Failed to save. Check server logs.")


# ── Webhook endpoint ──────────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Telegram webhook receiver.

    1. Validates X-Telegram-Bot-Api-Secret-Token (skipped when TELEGRAM_WEBHOOK_SECRET unset).
    2. Filters by TELEGRAM_ALLOWED_USER_IDS (returns ignored 200 when not in list).
    3. Returns 200 immediately; heavy work (download/transcribe/embed) runs in background.
    """
    # 1. Secret token check
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if secret and x_telegram_bot_api_secret_token != secret:
        logger.warning("[telegram] Invalid or missing X-Telegram-Bot-Api-Secret-Token")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    # 2. Parse update
    try:
        update: Dict[str, Any] = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    message: Optional[Dict[str, Any]] = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "ignored", "reason": "no_message"}

    # 3. Allowlist check
    from_id = str(message.get("from", {}).get("id", ""))
    allowed = settings.TELEGRAM_ALLOWED_USER_IDS
    if allowed and from_id not in allowed:
        logger.info("[telegram] User %s not in allowlist — ignored", from_id)
        return {"status": "ignored", "reason": "not_allowed"}

    # 4. Schedule background processing — return 200 to Telegram immediately
    background_tasks.add_task(_process_update, message)
    return {"status": "queued"}
