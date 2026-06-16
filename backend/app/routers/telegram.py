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
_VOICE_TRIGGER_RE = re.compile(
    r"^\s*(вопрос|спроси|спрашиваю|найди|question|ask|find)\b[\s,:\-—]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_voice_trigger(transcript: str) -> Optional[str]:
    """Return the query text if transcript starts with a trigger word, else None."""
    m = _VOICE_TRIGGER_RE.match(transcript)
    if not m:
        return None
    return transcript[m.end():].strip()


# Trigger words that route text/voice/photo-caption to the AI chat mode.
_CHAT_TRIGGER_RE = re.compile(
    r"^\s*(ответь|ответ|/chat)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_chat_trigger(text: str) -> Optional[str]:
    """Return the prompt text if the message starts with a chat trigger, else None."""
    m = _CHAT_TRIGGER_RE.match(text)
    if not m:
        return None
    return text[m.end():].strip()


# Web search triggers: "поиск" or "/web". No overlap with brain/chat triggers.
_WEB_TRIGGER_RE = re.compile(
    r"^\s*(поиск|/web)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_web_trigger(text: str) -> Optional[str]:
    """Return query if text starts with a web-search trigger, else None."""
    m = _WEB_TRIGGER_RE.match(text)
    if not m:
        return None
    return text[m.end():].strip()


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


async def _tg_get_file_path(file_id: str) -> str:
    """Return the file_path for a given Telegram file_id."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{_tg_base()}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        return r.json()["result"]["file_path"]


async def _tg_download_file(file_path: str) -> bytes:
    """Download a file from Telegram's CDN."""
    url = f"https://api.telegram.org/file/bot{_tg_token()}/{file_path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


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
            return chat_query, "chat", None
        return txt, "text", None

    # Voice / audio → Whisper transcription
    if "voice" in message or "audio" in message:
        media = message.get("voice") or message.get("audio")
        fp = await _tg_get_file_path(media["file_id"])
        data = await _tg_download_file(fp)
        client = _get_openai_client()
        buf = io.BytesIO(data)
        buf.name = "voice.oga"
        result = await asyncio.to_thread(
            lambda: client.audio.transcriptions.create(model="whisper-1", file=buf)
        )
        transcript: str = result.text
        # Priority: Q&A (brain) > web search > chat > save
        query = _strip_voice_trigger(transcript)
        if query is not None:
            return query, "ask", None
        web_query = _strip_web_trigger(transcript)
        if web_query is not None:
            return web_query, "web", None
        chat_query = _strip_chat_trigger(transcript)
        if chat_query is not None:
            return chat_query, "chat", None
        return f"[voice transcript] {transcript}", "voice", None

    # Photo
    if "photo" in message:
        largest = message["photo"][-1]
        caption: str = message.get("caption", "")
        fp = await _tg_get_file_path(largest["file_id"])
        data = await _tg_download_file(fp)

        # Chat mode: caption starts with chat trigger — pass raw bytes to AI
        chat_query = _strip_chat_trigger(caption)
        if chat_query is not None:
            return chat_query, "chat", data

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
    model = getattr(settings, "GROK_MODEL", "grok-3")
    if image_bytes:
        model = "grok-2-vision-1212"
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
) -> str:
    """Try providers in TELEGRAM_CHAT_PROVIDER_ORDER, fall through on error."""
    order = settings.TELEGRAM_CHAT_PROVIDER_ORDER or ("gpt", "claude", "grok")
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
                return result
            errors.append(f"{provider}: bad response")
        except Exception as exc:
            logger.warning("[telegram/chat] provider=%s error: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    logger.error("[telegram/chat] All providers failed: %s", errors)
    return "⚠️ Все AI провайдеры временно недоступны. Попробуй позже."


def _do_chat_sync(
    prompt: str,
    tg_user_id: int,
    system: str,
    image_bytes: Optional[bytes],
) -> str:
    """Load history → call AI → save both turns. Returns answer. Sync."""
    history = _load_chat_history_sync(tg_user_id)
    user_content = prompt or "Опиши это изображение."
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_content}]
    answer = _chat_complete_sync(messages, image_bytes)
    _save_chat_turn_sync(tg_user_id, "user", user_content)
    _save_chat_turn_sync(tg_user_id, "assistant", answer)
    return answer


async def _answer_from_chat(
    prompt: str,
    chat_id: int,
    tg_user_id: int,
    image_bytes: Optional[bytes] = None,
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
        answer = await asyncio.to_thread(_do_chat_sync, prompt, tg_user_id, system, image_bytes)
    except Exception as exc:
        logger.error("[telegram/chat] error for user=%d: %s", tg_user_id, exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при обработке запроса. Попробуй позже.")
        return

    if len(answer) > _MAX_REPLY_LEN:
        answer = answer[: _MAX_REPLY_LEN - 3] + "..."
    await _tg_send_message(chat_id, answer)
    logger.info("[telegram/chat] replied to user=%d chars=%d", tg_user_id, len(answer))


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
                SELECT m.raw_text, m.summary, m.timestamp, m.project_id_int,
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
    if not hits:
        await _tg_send_message(
            chat_id,
            "🔍 Ничего не нашлось в заметках по этому запросу. Попробуй другие слова.",
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
    "Reply in the same language as the user's question. "
    "Be concise and factual. "
    "After the answer, include a 'Источники:' section listing the URLs of the sources you used."
)


async def _answer_with_web(query: str, chat_id: int, tg_user_id: int) -> None:
    logger.info("[telegram/web] search query user=%d q=%r", tg_user_id, query[:80])
    if not query.strip():
        await _tg_send_message(chat_id, "❓ Пустой поисковый запрос.")
        return
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        await _tg_send_message(chat_id, "⚠️ TAVILY_API_KEY не настроен.")
        return
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
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
        await _tg_send_message(chat_id, "🔍 Интернет-поиск не вернул результатов.")
        return

    context_block = "\n\n---\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": _WEB_SYSTEM_PROMPT},
        {"role": "user", "content": f"Web results:\n{context_block}\n\nQuestion: {query}"},
    ]

    def _do_web_complete() -> str:
        answer = _chat_complete_sync(messages)
        _save_chat_turn_sync(tg_user_id, "user", f"[web] {query}")
        _save_chat_turn_sync(tg_user_id, "assistant", answer)
        return answer

    try:
        answer = await asyncio.to_thread(_do_web_complete)
    except Exception as exc:
        logger.error("[telegram/web] completion error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при генерации ответа. Попробуй позже.")
        return

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
        if kind == "chat":
            await _answer_from_chat(content, chat_id, tg_user_id, image_bytes)
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
