"""
brain_assistant.py — shared service layer for all Brain operations.

Used by both telegram.py (background tasks) and app_api.py (REST endpoints).
All public async functions wrap blocking SDK/DB calls in asyncio.to_thread.

Session strategy
----------------
• Functions called from an active HTTP request TAKE a ``db: Session`` param
  so the request session is reused.
• Functions called from background tasks (no open request) CREATE their own
  session internally via SessionLocal() / try / finally.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.memory.db import SessionLocal
from app.memory.models import CanonItem, MemoryEntry, Project

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────
_CHAT_HISTORY_LIMIT = 10
_MIN_SIMILARITY = 0.2

_CHAT_SYSTEM_PROMPT = (
    "You are a helpful, friendly assistant. "
    "Answer questions concisely and clearly. "
    "Reply in the same language as the user's message. "
    "Be warm and supportive."
)

def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

_ANSWER_SYSTEM_PROMPT = (
    "You are the user's personal knowledge base assistant. "
    "Answer the question using ONLY the provided notes. "
    "Reply in the same language as the question. "
    "Be concise and direct. "
    "After the answer add an 'Источники:' section listing the matched note "
    "snippets (first 100 chars each) and their dates. "
    "If the notes do not contain a relevant answer, say so honestly."
)

def _build_web_system_prompt() -> str:
    today = _today_utc()
    return (
        f"Current date: {today} (UTC). Treat this as today. "
        "Answer the user's question using ONLY the provided web search results. "
        "Use the location's local currency (Slovakia→EUR, Ukraine→UAH, UK→GBP, "
        "US→USD — NEVER default to RUB). "
        "Reply in the same language as the user's question. "
        "Do NOT add a sources section — it will be appended automatically."
    )

_SOURCES_STRIP_RE = re.compile(
    r"\n[\s\n]*(Источники|Sources|Ссылки|Links|References)\s*:.*",
    re.IGNORECASE | re.DOTALL,
)

_COUNTRY_HINTS: list[tuple[str, str]] = [
    ("словак", "Slovakia EUR €"), ("slovak", "Slovakia EUR €"),
    ("чехи", "Czech Republic CZK"), ("czech", "Czech Republic CZK"),
    ("польш", "Poland PLN"), ("poland", "Poland PLN"),
    ("венгри", "Hungary HUF"), ("hungary", "Hungary HUF"),
    ("австри", "Austria EUR €"), ("austria", "Austria EUR €"),
    ("германи", "Germany EUR €"), ("german", "Germany EUR €"),
    ("франци", "France EUR €"), ("france", "France EUR €"),
    ("итали", "Italy EUR €"), ("italy", "Italy EUR €"),
    ("испани", "Spain EUR €"), ("spain", "Spain EUR €"),
    ("украин", "Ukraine UAH ₴"), ("украін", "Ukraine UAH ₴"), ("ukraine", "Ukraine UAH ₴"),
    ("великобр", "UK GBP £"), ("united kingdom", "UK GBP £"), ("англи", "UK GBP £"),
    ("сша", "USA USD $"), ("америк", "USA USD $"), ("united states", "USA USD $"),
    ("канад", "Canada CAD"), ("canada", "Canada CAD"),
    ("австрали", "Australia AUD"), ("australia", "Australia AUD"),
    ("япони", "Japan JPY ¥"), ("japan", "Japan JPY ¥"),
    ("китай", "China CNY ¥"), ("china", "China CNY ¥"),
]

# Patterns that signal the answer requires live/current data → route to web
_REALTIME_RE = re.compile(
    r"\b("
    r"weather|погод[аеуыи]|прогноз\w*|forecast|температур[аы]?"
    r"|precipitation|humidity"
    r"|сейчас|сегодня|today|tonight|right\s*now|current(?:ly)?"
    r"|прямо\s+сейчас"
    r"|курс\s+\w+|exchange\s+rate"
    r"|latest\s+news|breaking\s+news|свеж\w+\s+новост\w+"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)


def _is_realtime_query(prompt: str) -> bool:
    return bool(_REALTIME_RE.search(prompt))


def _enrich_web_query(query: str, location: str, today: str) -> str:
    """Append location (if not already in the query) and today's date."""
    parts = [query]
    if location:
        loc_first = location.split()[0].lower()
        if loc_first and loc_first not in query.lower():
            parts.append(location)
    parts.append(today)
    return " ".join(parts)


# ── Lazy OpenAI client ────────────────────────────────────────
_openai_client: Optional[OpenAI] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        _openai_client = OpenAI(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _openai_client


# ── User project helper ───────────────────────────────────────

def get_or_create_user_project(db: Session, user: object) -> Project:
    """Return (or create) the user's default 'brain' project.

    Looks for a project named ``<username> brain``; creates one if absent.
    This gives every registered app user their own isolated Brain namespace.
    """
    brain_name = f"{user.username} brain"  # type: ignore[attr-defined]
    project = (
        db.query(Project)
        .filter(
            Project.user_id == user.id,  # type: ignore[attr-defined]
            Project.name == brain_name,
        )
        .first()
    )
    if project:
        return project
    project = Project(
        name=brain_name,
        user_id=user.id,  # type: ignore[attr-defined]
        description="Personal brain — auto-created by mobile app",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info(
        "[brain] Created project id=%d '%s' for user_id=%d",
        project.id, brain_name, user.id,  # type: ignore[attr-defined]
    )
    return project


# ── save_note ─────────────────────────────────────────────────

def _save_note_sync(
    project_id: int,
    content: str,
    kind: str,
    extra_tags: Optional[list] = None,
) -> dict:
    """Dual-write: CanonItem(INBOX) + MemoryEntry + embedding. Sync."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        pid_str = str(project_id)
        role_id = getattr(settings, "TELEGRAM_ROLE_ID", None)
        title = content.replace("\n", " ").replace("\r", "")[:80]
        tags = extra_tags if extra_tags is not None else ["mobile", kind]

        item = CanonItem(
            project_id=pid_str,
            project_id_int=project_id,
            role_id=role_id,
            type="INBOX",
            title=title,
            body=content,
            tags=tags,
            terms=content[:1000],
            created_at=now,
            is_active=True,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info("[brain/save] CanonItem id=%d kind=%s project=%d", item.id, kind, project_id)

        entry = MemoryEntry(
            project_id=pid_str,
            project_id_int=project_id,
            role_id=role_id,
            chat_session_id="mobile-inbox",
            summary=content[:2000],
            raw_text=content,
            is_summary=True,
            is_ai_to_ai=False,
            timestamp=now,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        try:
            from app.services.vector_service import store_message_with_embedding
            store_message_with_embedding(db, entry.id, content)
        except Exception as exc:
            logger.warning("[brain/save] embedding skipped: %s", exc)

        return {"saved_title": title, "canon_item_id": item.id}
    finally:
        db.close()


async def save_note(
    project_id: int,
    content: str,
    kind: str = "text",
    extra_tags: Optional[list] = None,
) -> dict:
    """Save text/voice/photo to Brain (CanonItem INBOX + MemoryEntry + embedding).

    Creates its own DB session — safe to call from background tasks.
    extra_tags overrides the default ["mobile", kind] tag list.
    Returns ``{"saved_title": str, "canon_item_id": int}``.
    """
    return await asyncio.to_thread(_save_note_sync, project_id, content, kind, extra_tags)


async def delete_note(db: Session, project_id: int, note_id: int) -> dict:
    """Soft-delete a note: set canon_items.is_active=False + memory_entries.deleted=True.

    Verifies the note belongs to ``project_id`` before touching anything.
    Raises ValueError if the note is not found or already deleted.
    Returns ``{"deleted": True, "id": note_id}``.
    """
    item = (
        db.query(CanonItem)
        .filter(
            CanonItem.id == note_id,
            CanonItem.project_id_int == project_id,
            CanonItem.is_active == True,
        )
        .first()
    )
    if not item:
        raise ValueError(f"Note {note_id} not found in project {project_id}")

    item.is_active = False

    db.execute(
        text("""
            UPDATE memory_entries
               SET deleted = TRUE
             WHERE project_id_int = :pid
               AND raw_text     = :body
               AND timestamp    = :ts
               AND deleted      = FALSE
        """),
        {"pid": project_id, "body": item.body, "ts": item.created_at},
    )

    db.commit()
    logger.info("[brain/delete] note id=%d project=%d soft-deleted", note_id, project_id)
    return {"deleted": True, "id": note_id}


# ── transcribe / describe_image ───────────────────────────────

async def transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio via OpenAI Whisper."""
    def _do() -> str:
        client = _get_openai_client()
        buf = io.BytesIO(audio_bytes)
        buf.name = "voice.oga"
        return client.audio.transcriptions.create(model="whisper-1", file=buf).text

    return await asyncio.to_thread(_do)


async def describe_image(image_bytes: bytes, caption: str = "") -> str:
    """Describe an image via GPT-4o vision."""
    def _do() -> str:
        b64 = base64.b64encode(image_bytes).decode()
        prompt = "Describe this image concisely. Focus on the main subject and any visible text."
        if caption:
            prompt += f"\n\nCaption: {caption}"
        client = _get_openai_client()
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()

    return await asyncio.to_thread(_do)


# ── extract_text (OCR) ────────────────────────────────────────

def _extract_text_sync(image_bytes: bytes) -> str:
    """Extract all visible text from image using vision model chain (GPT-4o → Claude → Grok)."""
    ocr_prompt = (
        "Extract ALL text visible in this image verbatim "
        "(handwriting, printed text, labels, numbers, receipts, notes). "
        "Return ONLY the extracted text with zero commentary or formatting. "
        "If there is no text in the image, return an empty string."
    )
    msgs = [{"role": "user", "content": ocr_prompt}]
    result, _ = _chat_complete_sync(msgs, image_bytes=image_bytes, preferred_provider="gpt")
    return result


async def extract_text(image_bytes: bytes) -> str:
    """OCR: extract all text from an image. Falls back GPT-4o → Claude → Grok.

    Returns the raw extracted text (may be empty if no text is in the image).
    """
    return await asyncio.to_thread(_extract_text_sync, image_bytes)


# ── parse_reminder_text ───────────────────────────────────────

def _parse_reminder_sync(directive: str) -> dict:
    """Parse a natural-language reminder string into {fire_at: ISO str, text: str}."""
    now = datetime.now()
    system = (
        f"Today is {now.strftime('%A, %Y-%m-%d %H:%M')}. "
        "Extract a reminder from the user's message. "
        "Return ONLY a JSON object with two keys: "
        '"fire_at" (ISO 8601 datetime, must be in the future) '
        'and "text" (reminder body in the original language, concise). '
        "No markdown, no extra text — pure JSON."
    )
    client = _get_openai_client()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": directive},
        ],
        temperature=0,
        max_tokens=120,
    )
    raw = (resp.choices[0].message.content or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return JSON: {raw!r}")
    return json.loads(match.group())


async def parse_reminder_text(directive: str) -> dict:
    """Parse NL reminder directive → {fire_at: ISO str, text: str}.

    Centralised helper used by /api/app/message (image+reminder),
    /api/app/parse-reminder (text-only), and Telegram.
    """
    return await asyncio.to_thread(_parse_reminder_sync, directive)


# ── Chat history helpers (sync, use telegram_chat_history table) ──
#
# session_key convention:
#   Telegram users:  tg_user_id  (positive, typically 6-10 digit)
#   Mobile users:   -(user.id)  (negative, no collision possible)

def _load_chat_history_sync(session_key: int) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
                SELECT role, content FROM telegram_chat_history
                WHERE tg_user_id = :uid
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"uid": session_key, "lim": _CHAT_HISTORY_LIMIT},
        ).fetchall()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]
    finally:
        db.close()


def _save_chat_turn_sync(session_key: int, role: str, content: str) -> None:
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO telegram_chat_history (tg_user_id, role, content, created_at)
                VALUES (:uid, :role, :content, NOW())
            """),
            {"uid": session_key, "role": role, "content": content},
        )
        db.commit()
    finally:
        db.close()


# ── Provider completions (sync) ───────────────────────────────

def _inject_image_gpt(messages: list[dict], image_bytes: Optional[bytes]) -> list[dict]:
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


def _complete_gpt(messages: list[dict], image_bytes: Optional[bytes] = None) -> str:
    if not getattr(settings, "OPENAI_API_KEY", None):
        raise RuntimeError("OPENAI_API_KEY not configured")
    msgs = _inject_image_gpt(messages, image_bytes)
    resp = _get_openai_client().chat.completions.create(
        model="gpt-4o", messages=msgs, max_tokens=800, temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _complete_claude(messages: list[dict], image_bytes: Optional[bytes] = None) -> str:
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    system = None
    conv: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            conv.append(dict(m))

    if image_bytes and conv and conv[-1]["role"] == "user":
        b64 = base64.b64encode(image_bytes).decode()
        conv[-1] = {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": conv[-1]["content"]},
            ],
        }

    client = Anthropic(
        api_key=api_key,
        http_client=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)),
    )
    model = getattr(settings, "ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-20250514")
    kwargs: dict = {"model": model, "max_tokens": 800, "messages": conv}
    if system:
        kwargs["system"] = system
    return client.messages.create(**kwargs).content[0].text.strip()


def _complete_grok(messages: list[dict], image_bytes: Optional[bytes] = None) -> str:
    api_key = getattr(settings, "GROK_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROK_API_KEY not configured")
    from openai import OpenAI as _XAI
    client = _XAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
        http_client=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), trust_env=False),
    )
    model = settings.GROK_VISION_MODEL if image_bytes else settings.GROK_MODEL
    msgs = _inject_image_gpt(messages, image_bytes)
    return client.chat.completions.create(
        model=model, messages=msgs, max_tokens=800, temperature=0.7,
    ).choices[0].message.content.strip()


def _complete_glm(messages: list[dict], image_bytes: Optional[bytes] = None) -> str:
    api_key = getattr(settings, "GLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("GLM_API_KEY not configured")
    base_url = getattr(settings, "GLM_BASE_URL", "https://api.z.ai/api/anthropic")
    model = getattr(settings, "GLM_MODEL", "glm-5.2")
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    system = None
    conv: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            conv.append(dict(m))

    client = Anthropic(
        api_key=api_key,
        base_url=base_url,
        http_client=httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)),
    )
    kwargs: dict = {"model": model, "max_tokens": 800, "messages": conv}
    if system:
        kwargs["system"] = system
    return client.messages.create(**kwargs).content[0].text.strip()


def _chat_complete_sync(
    messages: list[dict],
    image_bytes: Optional[bytes] = None,
    preferred_provider: Optional[str] = None,
) -> tuple[str, str]:
    """Try providers in (preferred-first) order. Returns (answer, provider_used)."""
    base_order: list[str] = list(settings.TELEGRAM_CHAT_PROVIDER_ORDER or ("gpt", "claude", "grok"))
    if preferred_provider:
        if preferred_provider in base_order:
            order = [preferred_provider] + [p for p in base_order if p != preferred_provider]
        else:
            # e.g. "glm" explicitly requested but not in default order — try it first
            order = [preferred_provider] + list(base_order)
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
            elif provider == "glm":
                result = _complete_glm(messages, image_bytes)
            else:
                logger.warning("[brain/chat] unknown provider %r — skipped", provider)
                continue

            low = (result or "").lower()
            if result and not any(low.startswith(p) for p in ("[openai error]", "[claude error]", "[glm error]")):
                logger.info("[brain/chat] provider=%s succeeded", provider)
                return result, provider

            logger.warning("[brain/chat] provider=%s bad response", provider)
            errors.append(f"{provider}: bad response")
        except Exception as exc:
            logger.warning("[brain/chat] provider=%s failed: %s: %s", provider, type(exc).__name__, exc)
            errors.append(f"{provider}: {exc}")

    logger.error("[brain/chat] all providers failed: %s", errors)
    return "⚠️ Все AI провайдеры временно недоступны. Попробуй позже.", "none"


# ── chat ─────────────────────────────────────────────────────

def _do_chat_sync(
    session_key: int,
    prompt: str,
    system: str,
    image_bytes: Optional[bytes],
    preferred_provider: Optional[str],
) -> tuple[str, str]:
    history = _load_chat_history_sync(session_key)
    user_content = prompt or "Опиши это изображение."
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_content}]
    answer, provider = _chat_complete_sync(messages, image_bytes, preferred_provider)
    _save_chat_turn_sync(session_key, "user", user_content)
    _save_chat_turn_sync(session_key, "assistant", answer)
    return answer, provider


async def chat(
    session_key: int,
    prompt: str,
    preferred_provider: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    system: Optional[str] = None,
    location: str = "",
) -> tuple[str, str]:
    """Multi-provider chat with persistent history. Returns (answer, provider_used).

    session_key: positive int for Telegram (tg_user_id), negative int for mobile (-(user_id)).
    Creates its own DB session internally — safe for background tasks.
    Always injects current date into the system prompt.
    Realtime queries (weather, current prices, news) are auto-routed to web_answer.
    """
    today = _today_utc()
    loc_hint = f" User's location: {location}." if location else ""
    base_sys = system or _CHAT_SYSTEM_PROMPT
    sys_prompt = f"Current date: {today} (UTC). Treat this as today.{loc_hint} {base_sys}"

    # Auto-route realtime queries (weather, current events, etc.) to Tavily web search
    if not image_bytes and _is_realtime_query(prompt) and getattr(settings, "TAVILY_API_KEY", ""):
        logger.info("[brain/chat] realtime intent detected — routing to web: %r", prompt[:80])
        answer, sources = await web_answer(session_key=session_key, query=prompt, location=location)
        if sources:
            answer += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in sources)
        return answer, "web"

    return await asyncio.to_thread(
        _do_chat_sync, session_key, prompt, sys_prompt, image_bytes, preferred_provider
    )


# ── search_notes ─────────────────────────────────────────────

async def search_notes(
    db: Session,
    project_id: int,
    query: str = "",
    limit: int = 20,
) -> list[dict]:
    """Semantic search over the project's notes.

    With no query: returns newest CanonItem(INBOX) entries.
    With query: returns memory_entries ranked by cosine similarity.
    Caller is responsible for db session lifecycle.
    """
    if not query.strip():
        rows = db.execute(
            text("""
                SELECT id, title, body, tags, created_at
                FROM canon_items
                WHERE project_id_int = :pid AND type = 'INBOX' AND is_active = TRUE
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"pid": project_id, "lim": limit},
        ).fetchall()
        return [
            {
                "id": r.id,
                "title": r.title,
                "body": r.body,
                "tags": r.tags or [],
                "created_at": str(r.created_at),
            }
            for r in rows
        ]

    from app.services.vector_service import create_embedding
    query_embedding: list[float] = await asyncio.to_thread(create_embedding, query)

    rows = db.execute(
        text("""
            SELECT m.id, m.raw_text, m.summary, m.timestamp,
                   1 - (m.embedding <=> CAST(:qe AS vector)) AS similarity
            FROM memory_entries m
            WHERE m.project_id_int = :pid
              AND m.embedding IS NOT NULL
              AND m.deleted = FALSE
            ORDER BY m.embedding <=> CAST(:qe AS vector)
            LIMIT :lim
        """),
        {"qe": query_embedding, "pid": project_id, "lim": limit},
    ).fetchall()

    return [
        {
            "id": r.id,
            "title": (r.raw_text or r.summary or "")[:80],
            "body": r.raw_text or r.summary or "",
            "tags": [],
            "created_at": str(r.timestamp),
        }
        for r in rows
        if float(r.similarity) >= _MIN_SIMILARITY
    ]


# ── answer_from_notes (brain Q&A) ────────────────────────────

async def answer_from_notes(
    db: Session,
    project_id: int,
    query: str,
    search_limit: int = 5,
) -> tuple[str, list[dict]]:
    """Semantic search + GPT-4o synthesis. Returns (ai_answer, hits).

    If no relevant notes are found, returns ("", []).
    """
    hits = await search_notes(db, project_id, query, limit=search_limit)
    if not hits:
        return "", []

    context_parts = [
        f"[{i + 1}] ({h['created_at']})\n{h['body'][:600]}"
        for i, h in enumerate(hits)
    ]
    context_block = "\n\n---\n\n".join(context_parts)

    def _do() -> str:
        client = _get_openai_client()
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Notes:\n{context_block}\n\nQuestion: {query}"},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()

    answer = await asyncio.to_thread(_do)
    return answer, hits


# ── web_answer ────────────────────────────────────────────────

def _localize_query(query: str) -> str:
    low = query.lower()
    for kw, hint in _COUNTRY_HINTS:
        if kw in low:
            return f"{query} {hint}"
    return query


async def web_answer(
    session_key: int,
    query: str,
    location: str = "",
) -> tuple[str, list[str]]:
    """Tavily search → AI answer. Returns (answer_text, source_urls).

    Creates its own DB session for history — safe for background tasks.
    Always injects current date; appends location when not already in the query.
    """
    today = _today_utc()
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not configured")

    enriched = _enrich_web_query(query, location, today)
    localized = _localize_query(enriched)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": localized,
                "search_depth": settings.TAVILY_SEARCH_DEPTH,
                "max_results": 5,
                "include_answer": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()

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
        return "Поиск не вернул результатов.", []

    context_block = "\n\n---\n\n".join(context_parts)
    web_sys = _build_web_system_prompt()
    messages = [
        {"role": "system", "content": web_sys},
        {"role": "user", "content": f"Web results:\n{context_block}\n\nQuestion: {query}"},
    ]

    def _do_complete() -> tuple[str, list[str]]:
        raw_answer, _ = _chat_complete_sync(messages)
        _save_chat_turn_sync(session_key, "user", f"[web] {query}")
        _save_chat_turn_sync(session_key, "assistant", raw_answer)
        clean = _SOURCES_STRIP_RE.sub("", raw_answer).rstrip()
        sources = [r.get("url", "").strip() for r in results[:5] if r.get("url")]
        return clean, sources

    return await asyncio.to_thread(_do_complete)
