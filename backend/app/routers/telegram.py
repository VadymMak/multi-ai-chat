"""
Telegram bot webhook handler — Brain MCP input portal.

POST /api/telegram/webhook

Receives Telegram updates, validates the secret token,
filters by allowed user IDs, and routes messages to Brain.

All heavy AI/DB work is delegated to app.services.brain_assistant;
this file handles only Telegram-specific concerns:
  - file download from Telegram CDN
  - trigger-word detection
  - sendMessage responses
  - background task routing
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
from sqlalchemy import text

from app.config.settings import settings
from app.memory.db import SessionLocal
from app.services import brain_assistant
from app.utils.tracking import bump_access_bg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


# ── Project mapping ───────────────────────────────────────────

def _project_for_user(tg_user_id: int) -> tuple[str, int]:
    """Return (project_id_str, project_id_int) for a Telegram sender."""
    pid = settings.TELEGRAM_USER_PROJECT_MAP.get(
        tg_user_id, settings.TELEGRAM_DEFAULT_PROJECT_ID
    )
    return str(pid), pid


# ── Trigger word patterns ─────────────────────────────────────

# OCR / reminder directives for photos
_PHOTO_REMINDER_RE = re.compile(
    r"^\s*(напомн\w*|напомин\w*|remind\w*|reminder)\b[\s,:\-—]*",
    re.IGNORECASE | re.UNICODE,
)
_PHOTO_OCR_RE = re.compile(
    r"\b(что\s+(тут|здесь|на\s*(фото|фотографии|изображении))?\s*написано"
    r"|прочита[йте]|прочти"
    r"|что\s+написа[лн][ои]?"
    r"|read\s+(it|this|out|aloud|text))\b",
    re.IGNORECASE | re.UNICODE,
)
_PHOTO_SAVE_RE = re.compile(
    r"^\s*(сохрани|запомни|save|запиши)\b", re.IGNORECASE | re.UNICODE
)

# Notes / brain Q&A trigger
_VOICE_TRIGGER_RE = re.compile(
    r"^\s*(вопрос\w*|спрашиваю|найди\s+в\s+заметках|question|ask\w*|find\w*)\b[\s,:\-—]*",
    re.IGNORECASE | re.UNICODE,
)

# AI chat trigger
_CHAT_TRIGGER_RE = re.compile(
    r"^\s*(ответь\w*|ответ|спроси\w*|/chat)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)

# Web search trigger
_WEB_TRIGGER_RE = re.compile(
    r"^\s*(поиск\w*|поищи\w*|погугли\w*|найди\s+в\s+интернете|/web|search\s+web)\b[\s,:\-—.!?]*",
    re.IGNORECASE | re.UNICODE,
)


def _strip_voice_trigger(transcript: str) -> Optional[str]:
    m = _VOICE_TRIGGER_RE.match(transcript)
    return transcript[m.end():].strip() if m else None


def _strip_chat_trigger(text: str) -> Optional[str]:
    m = _CHAT_TRIGGER_RE.match(text)
    return text[m.end():].strip() if m else None


def _strip_web_trigger(text: str) -> Optional[str]:
    m = _WEB_TRIGGER_RE.match(text)
    return text[m.end():].strip() if m else None


# ── Model-alias detection ─────────────────────────────────────

_MODEL_ALIAS_PATS: dict[str, list[str]] = {
    "gpt": [
        r"gpt\w*", r"гпт\w*", r"джипит\w*", r"джи\s+пи\s+ти",
        r"чатgpt\w*", r"чат\s*gpt\w*", r"openai\w*", r"опенаи\w*",
        r"гптшк\w*", r"чатгпт\w*",
    ],
    "claude": [r"claude\w*", r"клод\w*", r"клот\w*", r"клауд\w*", r"клоуд\w*"],
    "grok":   [r"grok\w*", r"грок\w*", r"грук\w*", r"грокк\w*"],
    "glm":    [r"glm[\w.\-]*", r"глм\w*", r"гэлэм\w*", r"джиэлэм\w*", r"глэм\w*"],
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
    "glm":    "🤖 GLM",
}


def _detect_model(text: str) -> tuple[Optional[str], str]:
    for provider, pat in _MODEL_RE.items():
        m = pat.match(text)
        if m:
            return provider, text[m.end():].strip()
    return None, text


# ── Telegram API helpers ──────────────────────────────────────

def _tg_token() -> str:
    return settings.TELEGRAM_BOT_TOKEN.strip()


def _tg_base() -> str:
    return f"https://api.telegram.org/bot{_tg_token()}"


_TG_TRANSIENT = (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TransportError)


class _MediaDownloadError(Exception):
    """Raised when all retry attempts to fetch a Telegram media file fail."""


_TG_RETRY_DELAYS = (1.0, 2.0)


async def _tg_get_file_path(file_id: str) -> str:
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


# ── Content extraction (Telegram-specific) ────────────────────

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
        transcript = await brain_assistant.transcribe(data)
        web_query = _strip_web_trigger(transcript)
        if web_query is not None:
            return web_query, "web", None
        chat_query = _strip_chat_trigger(transcript)
        if chat_query is not None:
            provider, q = _detect_model(chat_query)
            return (q, f"chat:{provider}", None) if provider else (chat_query, "chat", None)
        query = _strip_voice_trigger(transcript)
        if query is not None:
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

        if caption:
            # Reminder directive + photo: OCR image → parse datetime
            if _PHOTO_REMINDER_RE.search(caption):
                return (caption, "ocr_reminder", data)

            # Explicit OCR query: "что написано?", "прочитай"
            if _PHOTO_OCR_RE.search(caption):
                return (caption, "ocr_query", data)

            # Save directive: "сохрани", "запомни"
            if _PHOTO_SAVE_RE.search(caption):
                return (caption, "ocr_save", data)

            # Default: vision chat
            vision_prompt = caption
            for strip_fn in (_strip_chat_trigger, _strip_web_trigger, _strip_voice_trigger):
                stripped = strip_fn(caption)
                if stripped is not None:
                    vision_prompt = stripped
                    break
            if not vision_prompt.strip():
                vision_prompt = "Что на изображении?"
            provider, q = _detect_model(vision_prompt)
            prompt = q.strip() or vision_prompt.strip()
            return (prompt, f"chat:{provider}", data) if provider else (prompt, "chat", data)

        # No caption → OCR first; fallback to describe + save
        return ("", "ocr_save", data)

    return "", "unknown", None


# ── Telegram-specific system prompt variants ──────────────────

_CHAT_SYSTEM_PROMPT = brain_assistant._CHAT_SYSTEM_PROMPT  # reuse from service

_DAUGHTER_SYSTEM_PROMPT = (
    "You are a friendly, educational AI assistant for a young girl. "
    "Use simple, clear language that is easy for children to understand. "
    "Be encouraging, positive, and always family-friendly. "
    "Reply in the same language as her message."
)

_MAX_REPLY_LEN = 4096


# ── Telegram response handlers ────────────────────────────────

async def _answer_from_chat(
    prompt: str,
    chat_id: int,
    tg_user_id: int,
    image_bytes: Optional[bytes] = None,
    preferred_provider: Optional[str] = None,
) -> None:
    """AI general chat — delegates to brain_assistant.chat."""
    if not prompt.strip() and not image_bytes:
        await _tg_send_message(chat_id, "❓ Пустое сообщение. Напиши вопрос после 'ответь'.")
        return

    is_daughter = (
        getattr(settings, "TELEGRAM_DAUGHTER_USER_ID", None) is not None
        and settings.TELEGRAM_DAUGHTER_USER_ID == tg_user_id
    )
    system = _DAUGHTER_SYSTEM_PROMPT if is_daughter else _CHAT_SYSTEM_PROMPT

    try:
        answer, provider_used = await brain_assistant.chat(
            session_key=tg_user_id,
            prompt=prompt,
            preferred_provider=preferred_provider,
            image_bytes=image_bytes,
            system=system,
        )
    except Exception as exc:
        logger.error("[telegram/chat] error user=%d: %s", tg_user_id, exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка при обработке запроса. Попробуй позже.")
        return

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


async def _answer_from_brain(query: str, chat_id: int, sender_pid: int) -> None:
    """Brain Q&A — delegates to brain_assistant.answer_from_notes."""
    if not query.strip():
        await _tg_send_message(chat_id, "❓ Пустой вопрос. Напиши что-нибудь после /ask или ?.")
        return

    db = SessionLocal()
    hits: list = []
    try:
        answer, hits = await brain_assistant.answer_from_notes(db, sender_pid, query)
    except Exception as exc:
        logger.error("[telegram/ask] error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка поиска по заметкам. Попробуй позже.")
        return
    finally:
        bump_access_bg(SessionLocal, "memory_entries", [h["id"] for h in hits])
        db.close()

    if not hits:
        await _tg_send_message(
            chat_id,
            "🔎 Заметки: ничего не нашлось по этому запросу.\n\n"
            "_Если хотел ответ от ИИ — скажи «ответь …» или «спроси Клода/Грока/GPT …»._",
        )
        return

    reply = f"🔎 Заметки:\n{answer}"
    if len(reply) > _MAX_REPLY_LEN:
        reply = reply[: _MAX_REPLY_LEN - 3] + "..."
    await _tg_send_message(chat_id, reply)
    logger.info("[telegram/ask] Answered (hits=%d, chars=%d)", len(hits), len(reply))


async def _answer_with_web(query: str, chat_id: int, tg_user_id: int) -> None:
    """Web search — delegates to brain_assistant.web_answer."""
    logger.info("[telegram/web] search query user=%d q=%r", tg_user_id, query[:80])
    if not query.strip():
        await _tg_send_message(chat_id, "❓ Пустой поисковый запрос.")
        return
    if not settings.TAVILY_API_KEY:
        await _tg_send_message(chat_id, "⚠️ TAVILY_API_KEY не настроен.")
        return

    try:
        answer, sources = await brain_assistant.web_answer(
            session_key=tg_user_id,
            query=query,
        )
    except Exception as exc:
        logger.error("[telegram/web] error user=%d: %s", tg_user_id, exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Ошибка поиска в интернете. Попробуй позже.")
        return

    if sources:
        answer += "\n\nИсточники:\n" + "\n".join(f"• {u}" for u in sources)
    reply = f"🌐 Поиск:\n{answer}"
    if len(reply) > _MAX_REPLY_LEN:
        reply = reply[: _MAX_REPLY_LEN - 3] + "..."
    await _tg_send_message(chat_id, reply)
    logger.info("[telegram/web] replied user=%d chars=%d", tg_user_id, len(reply))


# ── VSCode activity ───────────────────────────────────────────

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
        ago = f"{mins // 60} ч. назад"

    proj = row.project_name or row.folder_identifier or "неизвестно"
    lang = f" ({row.language})" if row.language else ""
    await _tg_send_message(
        chat_id,
        f"🖥 Сейчас открыт: {row.file_path}{lang}\nПроект: {proj}\nОбновлено: {ago}",
    )


# ── Async background task ─────────────────────────────────────

async def _process_update(message: Dict[str, Any]) -> None:
    """Route message to the correct handler. Never raises."""
    chat_id: int = message.get("chat", {}).get("id", 0)
    tg_user_id: int = message.get("from", {}).get("id", 0)
    _pid_str, pid_int = _project_for_user(tg_user_id)

    try:
        content, kind, image_bytes = await _extract_content(message)

        if kind == "now":
            await _report_current_activity(chat_id)
            return

        if not content and not image_bytes:
            logger.info("[telegram] Unsupported message type — skipped")
            return

        if kind == "web":
            await _answer_with_web(content, chat_id, tg_user_id)
            return

        if kind == "chat" or kind.startswith("chat:"):
            preferred = kind.split(":", 1)[1] if ":" in kind else None
            await _answer_from_chat(content, chat_id, tg_user_id, image_bytes, preferred)
            return

        if kind == "ask":
            await _answer_from_brain(content, chat_id, sender_pid=pid_int)
            return

        # ── OCR-based handlers ────────────────────────────────
        if kind == "ocr_query":
            # "что написано?" / "прочитай" + photo → OCR → reply text
            try:
                ocr_text = await brain_assistant.extract_text(image_bytes)
            except Exception as exc:
                await _tg_send_message(chat_id, f"⚠️ Не удалось распознать текст: {exc}")
                return
            reply = f"📝 Текст:\n{ocr_text.strip()}" if ocr_text.strip() else "📝 Текст на изображении не обнаружен."
            await _tg_send_message(chat_id, reply[:_MAX_REPLY_LEN])
            return

        if kind == "ocr_save":
            # Photo (captioned or bare) → OCR → save text; fallback to describe
            try:
                ocr_text = await brain_assistant.extract_text(image_bytes)
            except Exception:
                ocr_text = ""
            if ocr_text.strip():
                caption_prefix = content.strip() if content and not _PHOTO_SAVE_RE.search(content) else ""
                body = f"{caption_prefix}\n{ocr_text}".strip() if caption_prefix else ocr_text.strip()
                result = await brain_assistant.save_note(pid_int, body, "ocr", extra_tags=["photo", "ocr"])
                await _tg_send_message(
                    chat_id, f"✅ Сохранено (OCR): {result['saved_title']}"
                )
            else:
                # No text detected → describe + save
                try:
                    description = await brain_assistant.describe_image(image_bytes)
                except Exception as exc:
                    await _tg_send_message(chat_id, f"⚠️ Не удалось обработать изображение: {exc}")
                    return
                body = f"[screenshot] {description}"
                result = await brain_assistant.save_note(pid_int, body, "photo")
                await _tg_send_message(
                    chat_id, f"✅ Сохранено (фото): {result['saved_title']}"
                )
            return

        if kind == "ocr_reminder":
            # caption="напомни завтра в 9" + photo → OCR body + parse time → save + reply
            try:
                ocr_text = await brain_assistant.extract_text(image_bytes)
            except Exception:
                ocr_text = ""
            directive = (
                f"{content}\nТекст на фото: {ocr_text}" if ocr_text.strip() else content
            )
            try:
                fire_data = await brain_assistant.parse_reminder_text(directive)
            except Exception as exc:
                await _tg_send_message(chat_id, f"⚠️ Не смог разобрать напоминание: {exc}")
                return
            body = ocr_text.strip() or fire_data.get("text", "")
            when = fire_data["fire_at"]
            # Save to Brain with reminder tag so it's searchable
            try:
                await brain_assistant.save_note(
                    pid_int, body, "ocr", extra_tags=["photo", "ocr", "reminder"]
                )
            except Exception:
                pass
            await _tg_send_message(
                chat_id,
                f"🔔 Напоминание разобрано:\n"
                f"⏰ Время: {when}\n"
                f"📝 Текст: {body}\n\n"
                f"Установить будильник можно в мобильном приложении.",
            )
            return

        # Save mode (text / voice / legacy photo)
        result = await brain_assistant.save_note(pid_int, content, kind)
        await _tg_send_message(
            chat_id,
            f"✅ Saved to Brain (project {pid_int}): {result['saved_title']}",
        )

    except _MediaDownloadError as exc:
        logger.warning("[telegram] media download failed: %s", exc)
        await _tg_send_message(
            chat_id,
            "⚠️ Не удалось скачать файл из Telegram, попробуй отправить ещё раз.",
        )
    except Exception as exc:
        logger.error("[telegram] _process_update error: %s", exc, exc_info=True)
        await _tg_send_message(chat_id, "⚠️ Failed to process. Check server logs.")


# ── Webhook endpoint ──────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """
    Telegram webhook receiver.

    1. Validates X-Telegram-Bot-Api-Secret-Token.
    2. Filters by TELEGRAM_ALLOWED_USER_IDS.
    3. Returns 200 immediately — all heavy work runs in background.
    """
    logger.info("[telegram] webhook received")

    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if secret and x_telegram_bot_api_secret_token != secret:
        logger.warning("[telegram] Invalid or missing secret token")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        update: Dict[str, Any] = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    try:
        message: Optional[Dict[str, Any]] = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "no_message"}

        from_id = str(message.get("from", {}).get("id", ""))
        allowed = settings.TELEGRAM_ALLOWED_USER_IDS
        if allowed and from_id not in allowed:
            logger.info("[telegram] User %s not in allowlist — ignored", from_id)
            return {"status": "ignored", "reason": "not_allowed"}

        background_tasks.add_task(_process_update, message)
        logger.info("[telegram] queued update from user=%s", from_id)
        return {"status": "queued"}

    except Exception as exc:
        logger.error("[telegram] webhook dispatch error: %s", exc, exc_info=True)
        return {"status": "error"}
