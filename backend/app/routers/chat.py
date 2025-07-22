# File: app/routers/chat.py
from __future__ import annotations

from uuid import uuid4
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator, Field
from sqlalchemy.orm import Session

from app.memory.db import get_db  # ✅ use the same get_db as the rest of the app
from app.memory.manager import MemoryManager
from app.memory.utils import safe_text
from app.config.settings import settings  # flags and thresholds

# ✅ Deterministic YouTube path (same as /ask)
from app.services.youtube_service import search_videos

import asyncio
import re

router = APIRouter(prefix="/chat", tags=["Chat"])


# ====== MODELS ======

class ChatSummarizeRequest(BaseModel):
    role_id: int
    project_id: Union[str, int]
    chat_session_id: Optional[str] = None
    rotate_session: Optional[bool] = False  # frontend can force rotation

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v):
        if v is None:
            raise ValueError("project_id is required")
        if isinstance(v, (int, float)):
            ival = int(v)
            if ival < 1:
                raise ValueError("project_id must be positive")
            return str(ival)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                raise ValueError("project_id must be a non-empty string")
            return s
        raise ValueError("project_id must be a string or integer")


class ChatMessage(BaseModel):
    sender: str
    text: str
    role_id: int
    project_id: str
    chat_session_id: Optional[str] = None
    isTyping: Optional[bool] = False
    isSummary: Optional[bool] = False
    # 🔹 Optional render + sources so the UI can show code/markdown and YouTube after refresh
    render: Optional[Dict[str, Any]] = None
    sources: Dict[str, Any] = Field(default_factory=dict)


class ChatSummary(BaseModel):
    summary: str
    timestamp: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    messages: List[ChatMessage]
    summaries: List[ChatSummary]


# ====== INTERNAL HELPERS ======

def _row_to_message(
    row: Dict[str, Any],
    *,
    fallback_role_id: int,
    fallback_project_id: str,
    fallback_session_id: str,
) -> Optional[ChatMessage]:
    """
    Normalize a DB row/dict into ChatMessage.
    Ensures final-answer rows (sender == 'final') are flagged as summaries.
    """
    text = safe_text(row.get("text", ""))
    if not text.strip():
        return None

    sender = safe_text(row.get("sender", ""))
    role_id = int(row.get("role_id", fallback_role_id))
    project_id = str(row.get("project_id", fallback_project_id))
    chat_session_id = safe_text(row.get("chat_session_id") or fallback_session_id)

    is_summary = bool(
        row.get("isSummary") or row.get("is_summary") or (sender == "final")
    )

    # We don't persist render/sources in DB; they can be (re)attached by routers.
    return ChatMessage(
        sender=sender,
        text=text,
        role_id=role_id,
        project_id=project_id,
        chat_session_id=chat_session_id,
        isTyping=False,
        isSummary=is_summary,
    )


def _get_last_session_id_from_record(rec: Optional[Dict[str, Any]]) -> str:
    """
    MemoryManager.get_last_session(...) may expose 'chat_session_id' or 'session_id'.
    """
    if not rec:
        return ""
    sid = rec.get("chat_session_id") or rec.get("session_id") or ""
    return safe_text(sid)


def _empty_payload(project_id: str, role_id: Optional[int]) -> Dict[str, Any]:
    return {
        "project_id": str(project_id) if project_id is not None else "",
        "role_id": int(role_id) if role_id is not None else None,
        "role_name": "",
        "chat_session_id": "",
        "messages": [],
        "summaries": [],
    }


# ====== YouTube helpers (same logic as in /ask) ======
_YT_PREFIX = re.compile(r"^\s*(?:youtube:|yt:)\s*(.+)$", re.IGNORECASE)
_YT_FIND = re.compile(r"\b(?:find on youtube|search youtube for)\b[:\s]*(.+)$", re.IGNORECASE)

def _detect_youtube_intent(q: str) -> Optional[str]:
    if not q:
        return None
    m = _YT_PREFIX.match(q)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = _YT_FIND.search(q)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None

async def _safe_youtube(topic: str) -> List[Dict[str, str]]:
    """
    Fetch YouTube sidecar using the deterministic service.
    Runs in a background thread to keep the event loop snappy.
    """
    timeout = float(getattr(settings, "YT_SEARCH_TIMEOUT", 6.0))
    maxn = int(getattr(settings, "YT_SEARCH_MAX_RESULTS", 3))
    since_months = int(getattr(settings, "YT_SINCE_MONTHS", 24))
    order = getattr(settings, "YOUTUBE_ORDER", "relevance")
    region = getattr(settings, "YOUTUBE_REGION_CODE", "")

    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(
                search_videos,
                query=topic,
                max_results=maxn,
                since_months=since_months,
                channels=None,
                order=order,
                region=region,
                debug=bool(getattr(settings, "YOUTUBE_DEBUG", False)),
            ),
            timeout=timeout,
        )
    except Exception as e:
        print(f"[YouTube] fetch skipped or failed: {e}")
        return []

    out: List[Dict[str, str]] = []
    seen = set()
    for it in (items or []):
        title = str(it.get("title", "")).strip()
        url = str(it.get("url", "")).strip()
        vid = str(it.get("videoId", "")).strip()
        if not url and vid:
            url = f"https://www.youtube.com/watch?v={vid}"
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title or url, "url": url})
    return out[:maxn]


# ====== BUILD LAST-SESSION (used by two endpoints) ======

def _build_last_session_payload(
    db: Session, *, role_id: int, project_id: str, limit: int
) -> Dict[str, Any]:
    """
    Core implementation shared by /last-session-by-role and /last-session.
    Returns plain Python types (without YouTube enrichment; history endpoint does that).
    """
    project_id = str(project_id).strip()
    print(
        f"📅 Looking up last session (memory_entries) role_id={role_id}, project_id={project_id}, limit={limit}"
    )

    memory = MemoryManager(db)
    last = memory.get_last_session(role_id=role_id, project_id=project_id)  # may be None

    session_id = _get_last_session_id_from_record(last)
    role_name = safe_text((last or {}).get("role_name") or "")

    # Retrieve messages for this session (or empty)
    messages_raw = memory.retrieve_messages(
        project_id=project_id,
        role_id=role_id,
        chat_session_id=session_id if session_id else None,
        limit=int(limit),
    )

    messages: List[ChatMessage] = []
    for m in messages_raw:
        msg = _row_to_message(
            m,
            fallback_role_id=role_id,
            fallback_project_id=project_id,
            fallback_session_id=session_id,
        )
        if msg:
            messages.append(msg)

    summaries_raw = memory.load_recent_summaries(
        project_id=project_id, role_id=role_id, limit=5
    )
    summaries: List[ChatSummary] = [
        ChatSummary(summary=safe_text(s), timestamp=None) for s in summaries_raw
    ]

    return {
        "project_id": project_id,
        "role_id": role_id,
        "role_name": role_name,
        "chat_session_id": session_id,
        "messages": messages,
        "summaries": summaries,
    }


# ====== ROUTES ======

@router.get("/last-session-by-role")
def get_last_session_by_role(
    role_id: int,
    project_id: str,
    limit: int = Query(20, ge=1, le=1000),
    debug: Optional[bool] = Query(default=False, description="Include basic diagnostic info"),
    db: Session = Depends(get_db),
):
    """
    Returns the last session for a given role/project (from memory_entries).
    Always returns a consistent shape (messages & summaries arrays).
    """
    try:
        payload = _build_last_session_payload(
            db, role_id=role_id, project_id=project_id, limit=limit
        )
        if debug:
            payload["debug"] = {
                "messages_count": len(payload.get("messages", [])),
                "summaries_count": len(payload.get("summaries", [])),
                "session_id": payload.get("chat_session_id") or "",
            }
        return payload
    except Exception as e:
        print(f"❌ Error in /last-session-by-role: {e}")
        return _empty_payload(project_id, role_id)


@router.get("/last-session")
def get_last_session_legacy(
    debug: Optional[bool] = Query(default=False, description="Include basic diagnostic info"),
    db: Session = Depends(get_db),
):
    """
    Legacy endpoint for frontend compatibility.
    Returns most recent known session (from memory_entries).
    """
    try:
        memory = MemoryManager(db)
        last = memory.get_last_session()
        if not last:
            return _empty_payload(project_id="", role_id=None)

        payload = _build_last_session_payload(
            db,
            role_id=int(last["role_id"]),
            project_id=str(last["project_id"]),
            limit=20,
        )
        if debug:
            payload["debug"] = {
                "messages_count": len(payload.get("messages", [])),
                "summaries_count": len(payload.get("summaries", [])),
                "session_id": payload.get("chat_session_id") or "",
            }
        return payload

    except Exception as e:
        print(f"❌ Error in /last-session: {e}")
        return _empty_payload(project_id="", role_id=None)


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=1000),
    include_youtube: bool = Query(True, description="If true, rehydrate YouTube cards by re-running the deterministic search for the most recent YouTube-intent user message."),
    db: Session = Depends(get_db),
):
    """
    Returns chat history and summaries for the given (optional) session,
    sourced from memory_entries. Always returns a valid shape.

    With include_youtube=true, we re-run deterministic YouTube search for the most
    recent user message that expressed YouTube intent and attach the results to
    the next assistant message (so <YouTubeMessages /> has data after refresh).
    """
    if not str(project_id).strip():
        raise HTTPException(status_code=400, detail="Invalid project_id")

    try:
        project_id = str(project_id).strip()
        memory = MemoryManager(db)

        msgs = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            limit=int(limit),
        )

        messages: List[ChatMessage] = []
        for m in msgs:
            msg = _row_to_message(
                m,
                fallback_role_id=role_id,
                fallback_project_id=project_id,
                fallback_session_id=chat_session_id or "",
            )
            if msg:
                messages.append(msg)

        # 🔹 Rehydrate YouTube cards after refresh
        if include_youtube and bool(getattr(settings, "ENABLE_YT_IN_CHAT", True)):
            # Find the most recent user turn with YT intent
            last_user_idx = None
            yt_topic: Optional[str] = None
            for i in range(len(messages) - 1, -1, -1):
                m = messages[i]
                if m.sender.lower() == "user":
                    t = m.text or ""
                    topic = _detect_youtube_intent(t)
                    if topic:
                        last_user_idx = i
                        yt_topic = topic
                        break

            # Attach to the next assistant message, if any
            if yt_topic is not None and last_user_idx is not None:
                try:
                    yt_items = await _safe_youtube(yt_topic)
                except Exception as e:
                    print(f"[YT rehydrate] failed: {e}")
                    yt_items = []

                if yt_items:
                    # find next assistant/final message after the user index
                    attach_idx = None
                    for j in range(last_user_idx + 1, len(messages)):
                        if messages[j].sender.lower() in {"assistant", "openai", "anthropic", "final"}:
                            attach_idx = j
                            break
                    if attach_idx is not None:
                        m = messages[attach_idx]
                        # merge into sources.youtube
                        merged = dict(m.sources or {})
                        merged.setdefault("youtube", yt_items)
                        messages[attach_idx] = ChatMessage(
                            **m.model_dump(exclude={"sources"}),
                            sources=merged,
                        )

        summaries_raw = memory.load_recent_summaries(
            project_id=project_id, role_id=role_id, limit=5
        )
        summaries = [ChatSummary(summary=safe_text(s), timestamp=None) for s in summaries_raw]

        return ChatHistoryResponse(messages=messages, summaries=summaries)

    except Exception as e:
        print(f"❌ Error in /history: {e}")
        return ChatHistoryResponse(messages=[], summaries=[])


# ====== SUMMARIZE (+ optional rotation) ======

@router.post("/summarize")
def summarize_chat(
    req: ChatSummarizeRequest,
    debug: Optional[bool] = Query(default=False, description="Include token counts and rotation decision"),
    db: Session = Depends(get_db),
):
    """
    Summarize the current chat session, persist a divider message, and optionally rotate.

    Response (stable with existing frontend):
    {
      "ok": true,
      "project_id": "...",
      "role_id": 0,
      "chat_session_id": "...",
      "divider_message": { sender: "final", text: "...", isSummary: true, ... },
      "new_chat_session_id"?: "..."   # present if rotation is requested/triggered
      "debug"?: { thresholds, token_total, rotated }
    }
    """
    try:
        project_id = str(req.project_id).strip()
        role_id = int(req.role_id)
        session_id = safe_text(req.chat_session_id or "")

        if not project_id:
            raise HTTPException(status_code=400, detail="Invalid project_id")

        memory = MemoryManager(db)

        # Resolve session if not provided
        if not session_id:
            last = memory.get_last_session(role_id=role_id, project_id=project_id)
            session_id = _get_last_session_id_from_record(last)

        # Retrieve messages (last N) to summarize
        msgs = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=session_id or None,
            limit=200,
        )

        combined_text = "\n".join(
            safe_text(m.get("text", ""))
            for m in msgs
            if safe_text(m.get("text", "")).strip()
        )[:8000]

        # Token count to decide auto-rotation (best-effort)
        total_tokens = 0
        try:
            if hasattr(memory, "count_tokens"):
                total_tokens = sum(memory.count_tokens(safe_text(m.get("text", ""))) for m in msgs)
        except Exception:
            total_tokens = 0

        # Summarize (best-effort)
        summary_text = ""
        try:
            if hasattr(memory, "summarize_messages"):
                summary_text = safe_text(memory.summarize_messages([combined_text]))
            elif hasattr(memory, "summarize_text"):
                summary_text = safe_text(memory.summarize_text(combined_text))
        except Exception as e:
            print(f"[Summarizer error] {e}")
            summary_text = ""

        if not summary_text:
            summary_text = "Summary generated."

        # Persist divider in the current session
        try:
            memory.store_chat_message(
                project_id=project_id,
                role_id=role_id,
                chat_session_id=session_id or None,
                sender="final",
                text=summary_text,
            )
            try:
                memory.insert_audit_log(
                    project_id, role_id, session_id or "", "internal", "summary",
                    summary_text[:300]
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[Persist divider error] {e}")

        divider_message = {
            "sender": "final",
            "text": summary_text,
            "role_id": role_id,
            "project_id": project_id,
            "chat_session_id": session_id,
            "isTyping": False,
            "isSummary": True,
        }

        # Determine whether to rotate (explicit flag OR token threshold)
        should_rotate = bool(req.rotate_session)
        rotate_threshold = int(getattr(settings, "SUMMARIZE_TRIGGER_TOKENS", 2000))
        try:
            if not should_rotate and total_tokens and total_tokens >= rotate_threshold:
                should_rotate = True
                try:
                    memory.insert_audit_log(
                        project_id, role_id, session_id or "", "internal", "autosummarize_trigger",
                        f"total_tokens={total_tokens} threshold={rotate_threshold}"
                    )
                except Exception:
                    pass
        except Exception:
            pass

        resp: Dict[str, Any] = {
            "ok": True,
            "project_id": project_id,
            "role_id": role_id,
            "chat_session_id": session_id,
            "divider_message": divider_message,
        }

        if should_rotate:
            new_session_id = str(uuid4())
            resp["new_chat_session_id"] = new_session_id

        if debug:
            resp["debug"] = {
                "thresholds": {"summarize_trigger": rotate_threshold},
                "token_total": total_tokens,
                "rotated": should_rotate,
            }

        return resp

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in /summarize: {e}")
        raise HTTPException(status_code=500, detail="Summarization failed")
