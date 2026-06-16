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

import asyncio
import base64
import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.memory.db import SessionLocal
from app.memory.models import CanonItem, MemoryEntry
from app.utils.tracking import bump_access_bg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

_SESSION_ID = "telegram-inbox"


def _project_for_user(tg_user_id: int) -> tuple[str, int]:
    """Return (project_id_str, project_id_int) for a Telegram sender.

    Uses TELEGRAM_USER_PROJECT_MAP; falls back to TELEGRAM_DEFAULT_PROJECT_ID.
    """
    pid = settings.TELEGRAM_USER_PROJECT_MAP.get(
        tg_user_id, settings.TELEGRAM_DEFAULT_PROJECT_ID
    )
    return str(pid), pid

# Trigger words that route a voice message to Q&A instead of saving.
# Matches at the start of the transcript, followed by optional punctuation/space.
# Notes / brain Q&A trigger — "спроси" removed (now routes to AI chat).
# "найди в заметках" stays here; "найди в интернете" = web (handled by _WEB_TRIGGER_RE).
_VOICE_TRIGGER_RE = re.compile(
    r"^\s*(вопрос\w*|спрашиваю|найди\s+в\s+заметках|question|ask\w*|find\w*)\b[\s,:\-—]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_voice_trigger(transcript: str) -> Optional[str]:
    """Return the query text if transcript starts with a notes/brain trigger, else None."""
    m = _VOICE_TRIGGER_RE.match(transcript)
    if not m:
        return None
    return transcript[m.end():].strip()


# AI chat trigger — "спроси" added here to avoid collision with notes search.
_CHAT_TRIGGER_RE = re.compile(
    r"^\s*(ответь\w*|ответ|спроси\w*|/chat)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_chat_trigger(text: str) -> Optional[str]:
    """Return the prompt text if the message starts with a chat trigger, else None."""
    m = _CHAT_TRIGGER_RE.match(text)
    if not m:
        return None
    return text[m.end():].strip()


# Web search triggers. "найди в интернете" is distinct from bare "найди" (brain).
_WEB_TRIGGER_RE = re.compile(
    r"^\s*(поиск\w*|поищи\w*|погугли\w*|найди\s+в\s+интернете|/web|search\s+web)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_web_trigger(text: str) -> Optional[str]:
    """Return query if text starts with a web-search trigger, else None."""
    m = _WEB_TRIGGER_RE.match(text)
    if not m:
        return None
    return text[m.end():].strip()


# ── Model-alias detection ─────────────────────────────────────────
# Matches the start of the *remaining* text after a trigger word is stripped.
# Groups cover natural Russian speech, Whisper transliterations, and English.
_MODEL_ALIAS_PATS: dict[str, list[str]] = {
    "gpt": [
        r"gpt\w*", r"гпт\w*", r"джипит\w*",
        r"джи\s+пи\s+ти", r"чатgpt\w*", r"чат\s*gpt\w*",
        r"openai\w*", r"опенаи\w*", r"гптшк\w*", r"чатгпт\w*",
    ],
    "claude": [r"claude\w*", r"клод\w*", r"клот\w*", r"клауд\w*", r"клоуд\w*"],
    "grok":   [r"grok\w*",  r"грок\w*", r"грук\w*", r"грокк\w*"],
}

_MODEL_RE: dict[str, re.Pattern] = {
    provider: re.compile(
        r"^\s*(?:" + "|".join(pats) + r")\b[\s,\-—.!?]*",
        re.IGNORECASE | re.UNICODE,
    )
    for provider, pats in _MODEL_ALIAS_PATS.items()
}

_MODEL_LABELS: dict[str, str] = {
    "gpt":    "🤖 GPT",
    "claude": "🤖 Claude",
    "grok":   "🤖 Grok",
}


def _detect_model(text: str) -> tuple[Optional[str], str]:
    """
    If text starts with a model alias, return (provider, remaining_query).
    Otherwise return (None, text) — caller keeps existing behaviour.
    """
    for provider, pat in _MODEL_RE.items():
        m = pat.match(text)
        if m:
            return provider, text[m.end():].strip()
    return None, text


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

def _tg_token() -> str:
    # Strip whitespace/newlines — Railway copy-paste often adds trailing \n
    return settings.TELEGRAM_BOT_TOKEN.strip()


def _tg_base() -> str:
    return f"https://api.telegram.org/bot{_tg_token()}"


_TG_TRANSIENT = (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TransportError)


class _MediaDownloadError(Exception):
    """Raised when all retry attempts to fetch a Telegram media file fail."""
_TG_RETRY_DELAYS = (1.0, 2.0)  # seconds between attempts 1→2 and 2→3


async def _tg_get_file_path(file_id: str) -> str:
    """Return the file_path for a given Telegram file_id (3 attempts, backoff)."""
    timeout = httpx.Timeout(60.0, connect=10.0)
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt, delay in enumerate((*_TG_RETRY_DELAYS, None), start=1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{_tg_base()}/getFile", params={"file_id": file_id})
                r.raise_for_status()
                return r.json()["result"]["file_path"]
        except _TG_TRANSIENT as exc:
            last_exc = exc
            logger.warning("[telegram] getFile attempt %d failed: %s", attempt, exc)
            if delay is not None:
                await asyncio.sleep(delay)
        except Exception:
            raise
    raise last_exc


async def _tg_download_file(file_path: str) -> bytes:
    """Download a file from Telegram's CDN (3 attempts, backoff)."""
    url = f"https://api.telegram.org/file/bot{_tg_token()}/{file_path}"
    timeout = httpx.Timeout(60.0, connect=10.0)
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt, delay in enumerate((*_TG_RETRY_DELAYS, None), start=1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                r.raise_for_status()
                return r.content
        except _TG_TRANSIENT as exc:
            last_exc = exc
            logger.warning("[telegram] download attempt %d failed: %s", attempt, exc)
            if delay is not None:
                await asyncio.sleep(delay)
        except Exception:
            raise
    raise last_exc


async def _tg_send_message(chat_id: int, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{_tg_base()}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception as exc:
        logger.warning("[telegram] sendMessage failed: %s", exc)


# ── Content extraction ────────────────────────────────────────────

async def _extract_content(
    message: Dict[str, Any],
) -> tuple[str, str, Optional[bytes]]:
    """Return (content, kind, image_bytes).

    kind ∈ {text, voice, photo, ask, chat, web, now, unknown}
    image_bytes is non-None only for kind="chat" with an attached photo.
    """

    # Plain text
    if "text" in message:
        txt: str = message["text"]
        if txt.startswith("/ask"):
            return txt[4:].strip(), "ask", None
        if txt.startswith("?"):
            return txt[1:].strip(), "ask", None
        low = txt.strip().lower()
        if low == "/now" or low.startswith("что я сейчас"):
            return "", "now", None
        web_query = _strip_web_trigger(txt)
        if web_query is not None:
            return web_query, "web", None
        chat_query = _strip_chat_trigger(txt)
        if chat_query is not None:
            provider, q = _detect_model(chat_query)
            return (q, f"chat:{provider}", None) if provider else (chat_query, "chat", None)
        notes_query = _strip_voice_trigger(txt)
        if notes_query is not None:
            # "спроси <model> ..." → model chat; "спроси ..." → brain search
            provider, q = _detect_model(notes_query)
            return (q, f"chat:{provider}", None) if provider else (notes_query, "ask", None)
        return txt, "text", None

    # Voice / audio → Whisper transcription
    if "voice" in message or "audio" in message:
        media = message.get("voice") or message.get("audio")
        try:
            fp = await _tg_get_file_path(media["file_id"])
            data = await _tg_download_file(fp)
        except _TG_TRANSIENT as exc:
            raise _MediaDownloadError("voice download failed") from exc
        client = _get_openai_client()
        buf = io.BytesIO(data)
        buf.name = "voice.oga"
        result = await asyncio.to_thread(
            lambda: client.audio.transcriptions.create(model="whisper-1", file=buf)
        )
        transcript: str = result.text
        # Priority: web > chat > notes(brain) > save
        web_query = _strip_web_trigger(transcript)
        if web_query is not None:
            return web_query, "web", None
        chat_query = _strip_chat_trigger(transcript)
        if chat_query is not None:
            provider, q = _detect_model(chat_query)
            return (q, f"chat:{provider}", None) if provider else (chat_query, "chat", None)
        query = _strip_voice_trigger(transcript)
        if query is not None:
            # "спроси <model> ..." → model chat; "спроси ..." → brain search
            provider, q = _detect_model(query)
            return (q, f"chat:{provider}", None) if provider else (query, "ask", None)
        return f"[voice transcript] {transcript}", "voice", None

    # Photo
    if "photo" in message:
        largest = message["photo"][-1]
        caption: str = message.get("caption", "")
        try:
            fp = await _tg_get_file_path(largest["file_id"])
            data = await _tg_download_file(fp)
        except _TG_TRANSIENT as exc:
            raise _MediaDownloadError("photo download failed") from exc

        # Chat mode: caption starts with chat trigger — pass raw bytes to AI
        chat_query = _strip_chat_trigger(caption)
        if chat_query is not None:
            provider, q = _detect_model(chat_query)
            return (q, f"chat:{provider}", data) if provider else (chat_query, "chat", data)

        # Default: describe with GPT-4o and save as INBOX note
        b64 = base64.b64encode(data).decode()
        prompt_text = "Describe this image concisely. Focus on the main subject and any visible text."
        if caption:
            prompt_text += f"\n\nCaption: {caption}"
        client = _get_openai_client()
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
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
        )
        description = response.choices[0].message.content.strip()
        full = f"[screenshot] {description}"
        if caption:
            full += f"\nCaption: {caption}"
        return full, "photo", None

    return "", "unknown", None


# ── Brain persistence ─────────────────────────────────────────────

def _write_to_brain(
    db: Session, content: str, kind: str, project_id_str: str, project_id_int: int
) -> MemoryEntry:
    """
    Dual-write:
      1. CanonItem(type=INBOX) — surfaces in build_context_for_query / list_canon_items
         Bypasses ENABLE_CANON flag (same pattern as save_session_summary).
      2. MemoryEntry(chat_session_id=telegram-inbox) — for search_conversation_memory.
    Returns the MemoryEntry so the caller can attach the embedding.
    """
    now = datetime.utcnow()
    title = content.replace("\n", " ").replace("\r", "")[:80]

    item = CanonItem(
        project_id=project_id_str,
        project_id_int=project_id_int,
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
    logger.info("[telegram] CanonItem id=%d type=INBOX kind=%s project=%d", item.id, kind, project_id_int)

    entry = MemoryEntry(
        project_id=project_id_str,
        project_id_int=project_id_int,
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
    logger.info("[telegram] MemoryEntry id=%d session=%s project=%d", entry.id, _SESSION_ID, project_id_int)

    return entry


# ── Sync save helper (DB + embedding) — called via asyncio.to_thread ──

def _save_to_brain_sync(content: str, kind: str, pid_str: str, pid_int: int) -> str:
    """Write CanonItem + MemoryEntry + embedding. Returns title snippet.

    Intentionally synchronous — call with asyncio.to_thread so the
    event loop is never blocked by DB commits or the OpenAI embedding call.
    """
    db = SessionLocal()
    try:
        entry = _write_to_brain(db, content, kind, pid_str, pid_int)
        try:
            from app.services.vector_service import store_message_with_embedding
            store_message_with_embedding(db, entry.id, content)
            logger.info("[telegram] Embedding stored for entry %d", entry.id)
        except Exception as emb_exc:
            logger.warning("[telegram] Embedding skipped: %s", emb_exc)
    finally:
        db.close()
    return content.replace("\n", " ").replace("\r", "")[:80]


# ── AI chat mode — multi-provider, conversation memory ───────────

_CHAT_SYSTEM_PROMPT = (
    "You are a helpful, friendly assistant. "
    "Answer questions concisely and clearly. "
    "Reply in the same language as the user's message. "
    "Be warm and supportive."
)

_DAUGHTER_SYSTEM_PROMPT = (
    "You are a friendly, educational AI assistant for a young girl. "
    "Use simple, clear language that is easy for children to understand. "
    "Be encouraging, positive, and always family-friendly. "
    "Reply in the same language as her message."
)

_CHAT_HISTORY_LIMIT = 10  # last N messages per user


# ── DB helpers (sync — call via asyncio.to_thread) ───────────────

def _load_chat_history_sync(tg_user_id: int) -> list[dict]:
    """Return the last _CHAT_HISTORY_LIMIT turns in chronological order."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT role, content FROM telegram_chat_history
                WHERE tg_user_id = :uid
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"uid": tg_user_id, "lim": _CHAT_HISTORY_LIMIT},
        ).fetchall()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]
    finally:
        db.close()


def _save_chat_turn_sync(tg_user_id: int, role: str, content: str) -> None:
    """Append one turn to telegram_chat_history."""
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO telegram_chat_history (tg_user_id, role, content, created_at)
                VALUES (:uid, :role, :content, NOW())
            """),
            {"uid": tg_user_id, "role": role, "content": content},
        )
        db.commit()
    finally:
        db.close()


# ── Provider completions (sync — call via asyncio.to_thread) ─────

def _inject_image_gpt(messages: list[dict], image_bytes: Optional[bytes]) -> list[dict]:
    """Attach image_bytes to the last user message in OpenAI content-list format."""
    if not image_bytes:
        return messages
    b64 = base64.b64encode(image_bytes).decode()
    msgs = list(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            msgs[i] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": msgs[i]["content"]},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
            break
    return msgs


def _complete_gpt(messages: list[dict], image_bytes: Optional[bytes]) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    client = _get_openai_client()
    msgs = _inject_image_gpt(messages, image_bytes)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=msgs,
        max_tokens=800,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _complete_claude(messages: list[dict], image_bytes: Optional[bytes]) -> str:
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    system = None
    conv_msgs: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            conv_msgs.append(dict(m))

    if image_bytes and conv_msgs and conv_msgs[-1]["role"] == "user":
        b64 = base64.b64encode(image_bytes).decode()
        conv_msgs[-1] = {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": conv_msgs[-1]["content"]},
            ],
        }

    client = Anthropic(
        api_key=api_key,
        http_client=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)),
    )
    model = getattr(settings, "ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-20250514")
    kwargs: dict = {"model": model, "max_tokens": 800, "messages": conv_msgs}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return resp.content[0].text.strip()


def _complete_grok(messages: list[dict], image_bytes: Optional[bytes]) -> str:
    api_key = getattr(settings, "GROK_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROK_API_KEY not configured")
    from openai import OpenAI as _XAI
    client = _XAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
        http_client=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), trust_env=False),
    )
    # grok-4.3 handles both text and vision; override via GROK_MODEL / GROK_VISION_MODEL
    model = settings.GROK_VISION_MODEL if image_bytes else settings.GROK_MODEL
    msgs = _inject_image_gpt(messages, image_bytes)
    resp = client.chat.completions.create(
        model=model,
        messages=msgs,
        max_tokens=800,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _chat_complete_sync(
    messages: list[dict],
    image_bytes: Optional[bytes] = None,
    preferred_provider: Optional[str] = None,
) -> tuple[str, str]:
    """Try providers in order; put preferred first. Returns (answer, provider_used)."""
    base_order = list(settings.TELEGRAM_CHAT_PROVIDER_ORDER or ("gpt", "claude", "grok"))
    if preferred_provider and preferred_provider in base_order:
        order = [preferred_provider] + [p for p in base_order if p != preferred_provider]
    else:
        order = base_order
    errors: list[str] = []

    for provider in order:
        try:
            if provider == "gpt":
                result = _complete_gpt(messages, image_bytes)
            elif provider == "claude":
                result = _complete_claude(messages, image_bytes)
            elif provider == "grok":
                result = _complete_grok(messages, image_bytes)
            else:
                logger.warning("[telegram/chat] Unknown provider %r — skipping", provider)
                continue

            low = (result or "").lower()
            if result and not any(low.startswith(p) for p in ("[openai error]", "[claude error]")):
                logger.info("[telegram/chat] provider=%s succeeded", provider)
                return result, provider
            logger.warning("[telegram/chat] provider=%s bad response: %r", provider, (result or "")[:120])
            errors.append(f"{provider}: bad response")
        except Exception as exc:
            logger.warning(
                "[telegram/chat] provider=%s failed: %s: %s",
                provider, type(exc).__name__, exc,
            )
            errors.append(f"{provider}: {type(exc).__name__}: {exc}")

    logger.error("[telegram/chat] All providers failed: %s", errors)
    return "⚠️ Все AI провайдеры временно недоступны. Попробуй позже.", "none"


def _do_chat_sync(
    prompt: str,
    tg_user_id: int,
    system: str,
    image_bytes: Optional[bytes],
    preferred_provider: Optional[str] = None,
) -> tuple[str, str]:
    """Load history → call AI → save both turns. Returns (answer, provider_used). Sync."""
    history = _load_chat_history_sync(tg_user_id)
    user_content = prompt or "Опиши это изображение."
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_content}]
    answer, provider_used = _chat_complete_sync(messages, image_bytes, preferred_provider)
    _save_chat_turn_sync(tg_user_id, "user", user_content)
    _save_chat_turn_sync(tg_user_id, "assistant", answer)
    return answer, provider_used


async def _answer_from_chat(
    prompt: str,
    chat_id: int,
    tg_user_id: int,
    image_bytes: Optional[bytes] = None,
    preferred_provider: Optional[str] = None,
) -> None:
    """AI general chat: load history → multi-provider → save → reply."""
    if not prompt.strip() and not image_bytes:
        await _tg_send_message(chat_id, "❓ Пустое сообщение. Напиши вопрос после 'ответь'.")
        return

    is_daughter = (
        getattr(settings, "TELEGRAM_DAUGHTER_USER_ID", None) is not None
        and settings.TELEGRAM_DAUGHTER_USER_ID == tg_user_id
    )
    system = _DAUGHTER_SYSTEM_PROMPT if is_daughter else _CHAT_SYSTEM_PROMPT

    try:
        answer, provider_used = await asyncio.to_thread(
            _do_chat_sync, prompt, tg_user_id, system, image_bytes, preferred_provider
        )
    except Exception as exc:
        logger.error("[telegram/chat] error for user=%d: %s", tg_user_id, exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при обработке запроса. Попробуй позже.")
        return

    # Always prefix with mode; show which model answered and flag fallbacks
    if preferred_provider:
        label = _MODEL_LABELS.get(provider_used, "🤖 ИИ")
        if provider_used != preferred_provider:
            wanted = _MODEL_LABELS.get(preferred_provider, preferred_provider)
            label = f"{label} (fallback от {wanted})"
    elif provider_used in _MODEL_LABELS:
        label = _MODEL_LABELS[provider_used]
    else:
        label = "💬 ИИ"
    answer = f"{label}: {answer}"

    if len(answer) > _MAX_REPLY_LEN:
        answer = answer[: _MAX_REPLY_LEN - 3] + "..."
    await _tg_send_message(chat_id, answer)
    logger.info(
        "[telegram/chat] replied user=%d preferred=%s used=%s chars=%d",
        tg_user_id, preferred_provider, provider_used, len(answer),
    )


# ── Brain Q&A (vector search → GPT-4o → reply) ───────────────────

_ANSWER_SYSTEM_PROMPT = (
    "You are the user's personal knowledge base assistant. "
    "Answer the question using ONLY the provided notes. "
    "Reply in the same language as the question. "
    "Be concise and direct. "
    "After the answer, add an 'Источники:' section listing "
    "the matched note snippets (first 100 chars each), their dates, and the project name. "
    "If the notes do not contain a relevant answer, say so honestly."
)

_MIN_SIMILARITY = 0.2
_SEARCH_LIMIT = 5
_MAX_REPLY_LEN = 4096


async def _answer_from_brain(query: str, chat_id: int, sender_pid: int) -> None:
    """Embed query → cosine search over sender's project memory → GPT-4o answer → sendMessage."""
    if not query.strip():
        await _tg_send_message(chat_id, "❓ Пустой вопрос. Напиши что-нибудь после /ask или ?.")
        return

    db = SessionLocal()
    try:
        from app.services.vector_service import create_embedding
        # Sync OpenAI embedding call — run in thread
        query_embedding: list[float] = await asyncio.to_thread(create_embedding, query)

        rows = db.execute(
            text("""
                SELECT m.id, m.raw_text, m.summary, m.timestamp, m.project_id_int,
                       p.name AS project_name,
                       1 - (m.embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM memory_entries m
                JOIN projects p ON m.project_id_int = p.id
                WHERE m.project_id_int = :pid
                  AND m.embedding IS NOT NULL
                  AND m.deleted = FALSE
                ORDER BY m.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :limit
            """),
            {
                "query_embedding": query_embedding,
                "pid": sender_pid,
                "limit": _SEARCH_LIMIT,
            },
        ).fetchall()
    except Exception as exc:
        logger.error("[telegram/ask] Vector search error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка поиска по заметкам. Попробуй позже.")
        return
    finally:
        db.close()

    hits = [r for r in rows if float(r.similarity) >= _MIN_SIMILARITY]
    bump_access_bg(SessionLocal, "memory_entries", [r.id for r in hits])
    if not hits:
        await _tg_send_message(
            chat_id,
            "🔎 Заметки: ничего не нашлось по этому запросу.\n\n"
            "_Если хотел ответ от ИИ — скажи «ответь …» или «спроси Клода/Грока/GPT …»._",
        )
        return

    # Build context block from top hits
    context_parts: list[str] = []
    for i, r in enumerate(hits, 1):
        note_text = (r.raw_text or r.summary or "").strip()
        ts = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else "?"
        proj = r.project_name or f"project {r.project_id_int}"
        context_parts.append(f"[{i}] ({ts}) [{proj}]\n{note_text[:600]}")
    context_block = "\n\n---\n\n".join(context_parts)

    # GPT-4o answer generation — sync SDK call in thread
    try:
        client = _get_openai_client()
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Notes:\n{context_block}\n\nQuestion: {query}",
                    },
                ],
                max_tokens=800,
                temperature=0.3,
            )
        )
        answer = response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("[telegram/ask] GPT-4o error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка генерации ответа. Попробуй позже.")
        return

    answer = f"🔎 Заметки:\n{answer}"
    if len(answer) > _MAX_REPLY_LEN:
        answer = answer[: _MAX_REPLY_LEN - 3] + "..."

    await _tg_send_message(chat_id, answer)
    logger.info("[telegram/ask] Answered (hits=%d, chars=%d)", len(hits), len(answer))


# ── VSCode activity ───────────────────────────────────────────────

async def _report_current_activity(chat_id: int) -> None:
    """Query latest vscode_activity for the configured user and send to Telegram."""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT va.file_path, va.language, va.folder_identifier,
                       va.updated_at, p.name AS project_name
                FROM vscode_activity va
                LEFT JOIN projects p ON va.project_id = p.id
                WHERE va.user_id = :uid
            """),
            {"uid": settings.TELEGRAM_APP_USER_ID},
        ).fetchone()
    except Exception as exc:
        logger.error("[telegram/now] DB error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при получении активности.")
        return
    finally:
        db.close()

    if not row:
        await _tg_send_message(
            chat_id,
            "🖥 Нет данных о текущем файле. Убедись что VS Code Extension работает.",
        )
        return

    now = datetime.utcnow()
    delta = now - row.updated_at.replace(tzinfo=None)
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        ago = "только что"
    elif mins < 60:
        ago = f"{mins} мин. назад"
    else:
        hours = mins // 60
        ago = f"{hours} ч. назад"

    proj = row.project_name or row.folder_identifier or "неизвестно"
    lang = f" ({row.language})" if row.language else ""
    msg = (
        f"🖥 Сейчас открыт: {row.file_path}{lang}\n"
        f"Проект: {proj}\n"
        f"Обновлено: {ago}"
    )
    await _tg_send_message(chat_id, msg)


# ── Tavily web search ─────────────────────────────────────────────

_WEB_SYSTEM_PROMPT = (
    "Answer the user's question using ONLY the provided web search results below. "
    "Identify the location mentioned in the user's question and answer using THAT location's "
    "local currency and units (e.g., Slovakia and other eurozone countries use EUR €, "
    "the UK uses GBP £, the US uses USD $, Ukraine uses UAH ₴ — NEVER default to RUB). "
    "If the web results are from a different country or currency than the location asked about, "
    "either convert to the correct local currency (state it is approximate) OR prefer the results "
    "that match the asked location. "
    "NEVER present a foreign-country price as if it were the local one. "
    "Always answer in the same language as the user's question. "
    "Do NOT add a sources, links, or references section — sources will be appended automatically."
)

# Strip any model-generated sources block so we can append a single code-built one.
_SOURCES_STRIP_RE = re.compile(
    r"\n[\s\n]*(Источники|Sources|Ссылки|Links|References)\s*:.*",
    re.IGNORECASE | re.DOTALL,
)

# Country hints appended to Tavily query to bias results toward the correct region.
# Key = substring found in query (lowercase); value = hint appended to search string.
_COUNTRY_HINTS: list[tuple[str, str]] = [
    ("словак",   "Slovakia EUR €"),
    ("slovak",   "Slovakia EUR €"),
    ("чехи",     "Czech Republic CZK"),
    ("czech",    "Czech Republic CZK"),
    ("польш",    "Poland PLN"),
    ("poland",   "Poland PLN"),
    ("венгри",   "Hungary HUF"),
    ("hungary",  "Hungary HUF"),
    ("австри",   "Austria EUR €"),
    ("austria",  "Austria EUR €"),
    ("германи",  "Germany EUR €"),
    ("german",   "Germany EUR €"),
    ("франци",   "France EUR €"),
    ("france",   "France EUR €"),
    ("итали",    "Italy EUR €"),
    ("italy",    "Italy EUR €"),
    ("испани",   "Spain EUR €"),
    ("spain",    "Spain EUR €"),
    ("украин",   "Ukraine UAH ₴"),
    ("украін",   "Ukraine UAH ₴"),
    ("ukraine",  "Ukraine UAH ₴"),
    ("великобр", "UK GBP £"),
    ("united kingdom", "UK GBP £"),
    ("англи",    "UK GBP £"),
    ("сша",      "USA USD $"),
    ("америк",   "USA USD $"),
    ("united states", "USA USD $"),
    ("канад",    "Canada CAD"),
    ("canada",   "Canada CAD"),
    ("австрали", "Australia AUD"),
    ("australia","Australia AUD"),
    ("япони",    "Japan JPY ¥"),
    ("japan",    "Japan JPY ¥"),
    ("китай",    "China CNY ¥"),
    ("china",    "China CNY ¥"),
]


def _localize_query(query: str) -> str:
    """Append a region/currency hint to the query based on country keywords."""
    low = query.lower()
    for kw, hint in _COUNTRY_HINTS:
        if kw in low:
            return f"{query} {hint}"
    return query


async def _answer_with_web(query: str, chat_id: int, tg_user_id: int) -> None:
    logger.info("[telegram/web] search query user=%d q=%r", tg_user_id, query[:80])
    if not query.strip():
        await _tg_send_message(chat_id, "❓ Пустой поисковый запрос.")
        return
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        await _tg_send_message(chat_id, "⚠️ TAVILY_API_KEY не настроен.")
        return
    localized_query = _localize_query(query)
    if localized_query != query:
        logger.debug("[telegram/web] query localized: %r -> %r", query, localized_query)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": localized_query,
                    "search_depth": settings.TAVILY_SEARCH_DEPTH,
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("[telegram/web] Tavily error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка поиска в интернете. Попробуй позже.")
        return

    results = data.get("results") or []
    tavily_answer = (data.get("answer") or "").strip()
    context_parts: list[str] = []
    if tavily_answer:
        context_parts.append(f"Tavily answer: {tavily_answer}")
    for i, r in enumerate(results[:5], 1):
        title = (r.get("title") or "").strip()
        snippet = (r.get("content") or "").strip()[:500]
        url = (r.get("url") or "").strip()
        context_parts.append(f"[{i}] {title}\n{snippet}\nURL: {url}")
    if not context_parts:
        await _tg_send_message(chat_id, "🌐 Поиск: интернет-поиск не вернул результатов.")
        return

    context_block = "\n\n---\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": _WEB_SYSTEM_PROMPT},
        {"role": "user", "content": f"Web results:\n{context_block}\n\nQuestion: {query}"},
    ]

    def _do_web_complete() -> str:
        answer, _ = _chat_complete_sync(messages)
        _save_chat_turn_sync(tg_user_id, "user", f"[web] {query}")
        _save_chat_turn_sync(tg_user_id, "assistant", answer)
        return answer

    try:
        answer = await asyncio.to_thread(_do_web_complete)
    except Exception as exc:
        logger.error("[telegram/web] completion error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при генерации ответа. Попробуй позже.")
        return

    # Strip any model-generated sources block, then append exactly one code-built section.
    answer = _SOURCES_STRIP_RE.sub("", answer).rstrip()
    source_urls = [r.get("url", "").strip() for r in results[:5] if r.get("url")]
    if source_urls:
        answer += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in source_urls)

    answer = f"🌐 Поиск:\n{answer}"
    if len(answer) > _MAX_REPLY_LEN:
        answer = answer[: _MAX_REPLY_LEN - 3] + "..."
    await _tg_send_message(chat_id, answer)
    logger.info("[telegram/web] replied user=%d chars=%d", tg_user_id, len(answer))


# ── Async background task ─────────────────────────────────────────

async def _process_update(message: Dict[str, Any]) -> None:
    """Route message to the correct handler. Never raises."""
    chat_id: int = message.get("chat", {}).get("id", 0)
    tg_user_id: int = message.get("from", {}).get("id", 0)
    pid_str, pid_int = _project_for_user(tg_user_id)

    try:
        content, kind, image_bytes = await _extract_content(message)

        if kind == "now":
            await _report_current_activity(chat_id)
            return

        if not content and not image_bytes:
            logger.info("[telegram] Unsupported message type — skipped")
            return

        # Tavily web search — real-time internet answer
        if kind == "web":
            await _answer_with_web(content, chat_id, tg_user_id)
            return

        # General AI chat — does NOT save to Brain notes
        # kind="chat" → default chain; kind="chat:<provider>" → prefer that model
        if kind == "chat" or kind.startswith("chat:"):
            preferred = kind.split(":", 1)[1] if ":" in kind else None
            await _answer_from_chat(content, chat_id, tg_user_id, image_bytes, preferred)
            return

        # Brain Q&A — searches notes, does NOT save
        if kind == "ask":
            await _answer_from_brain(content, chat_id, sender_pid=pid_int)
            return

        # Save mode (text / voice / photo) — writes to Brain
        title = await asyncio.to_thread(
            _save_to_brain_sync, content, kind, pid_str, pid_int
        )
        await _tg_send_message(
            chat_id,
            f"✅ Saved to Brain (project {pid_int}): {title}",
        )

    except _MediaDownloadError as exc:
        logger.warning("[telegram] media download failed after retries: %s", exc)
        await _tg_send_message(
            chat_id,
            "⚠️ Не удалось скачать файл из Telegram, попробуй отправить ещё раз.",
        )
    except Exception as exc:
        logger.error("[telegram] _process_update error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Failed to process. Check server logs.")


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
    2. Filters by TELEGRAM_ALLOWED_USER_IDS (returns 200 when not in list).
    3. Returns 200 immediately — ALL heavy work (download/transcribe/embed/DB) in background.
    """
    logger.info("[telegram] webhook received")

    # 1. Secret token check — 403 is intentional and correct here
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if secret and x_telegram_bot_api_secret_token != secret:
        logger.warning("[telegram] Invalid or missing X-Telegram-Bot-Api-Secret-Token")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    # 2. Parse update
    try:
        update: Dict[str, Any] = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    # 3-4. Dispatch — catch-all ensures we always return 200 so Telegram
    # doesn't retry indefinitely on unexpected errors.
    try:
        message: Optional[Dict[str, Any]] = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "no_message"}

        from_id = str(message.get("from", {}).get("id", ""))
        allowed = settings.TELEGRAM_ALLOWED_USER_IDS
        if allowed and from_id not in allowed:
            logger.info("[telegram] User %s not in allowlist — ignored", from_id)
            return {"status": "ignored", "reason": "not_allowed"}

        # Schedule background processing — returns 200 to Telegram immediately
        background_tasks.add_task(_process_update, message)
        logger.info("[telegram] queued update from user=%s", from_id)
        return {"status": "queued"}

    except Exception as exc:
        logger.error("[telegram] webhook dispatch error: %s", exc, exc_info=True)
        return {"status": "error"}
