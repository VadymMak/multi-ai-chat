# File: app/routers/chat.py
from __future__ import annotations

from uuid import uuid4
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.memory.db import get_db  # ✅ use the same get_db as the rest of the app
from app.memory.manager import MemoryManager
from app.memory.utils import safe_text
from app.config.settings import settings  # flags and thresholds

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


def _build_last_session_payload(
    db: Session, *, role_id: int, project_id: str, limit: int
) -> Dict[str, Any]:
    """
    Core implementation shared by /last-session-by-role and /last-session.
    Returns plain Python types.
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


def _empty_payload(project_id: str, role_id: Optional[int]) -> Dict[str, Any]:
    return {
        "project_id": str(project_id) if project_id is not None else "",
        "role_id": int(role_id) if role_id is not None else None,
        "role_name": "",
        "chat_session_id": "",
        "messages": [],
        "summaries": [],
    }


def _extract_and_persist_canon(
    *,
    memory: MemoryManager,
    project_id: str,
    role_id: int,
    source_text: str,
    session_id_for_audit: str,
) -> List[Dict[str, Any]]:
    """
    Best-effort delta extraction + persistence.
    - Respects settings.ENABLE_CANON (default False if missing)
    - Degrades gracefully if MemoryManager doesn't implement the helpers yet.

    Returns a list like: [{"id": 123, "type": "ADR", "title": "Decision X"}]
    """
    saved: List[Dict[str, Any]] = []

    try:
        enable_canon = bool(getattr(settings, "ENABLE_CANON", False))
        if not enable_canon:
            return saved

        max_saved = int(getattr(settings, "CANON_MAX_SAVED", 5))

        if not hasattr(memory, "extract_canon_deltas"):
            return saved

        deltas: List[Dict[str, Any]] = memory.extract_canon_deltas(
            text=source_text,
            project_id=project_id,
            role_id=role_id,
        ) or []

        if not deltas:
            return saved

        for d in deltas[:max_saved]:
            d_type = safe_text(str(d.get("type", "CHANGELOG")).upper()[:32] or "CHANGELOG")
            title = safe_text(d.get("title") or d.get("heading") or "Update")
            body = safe_text(d.get("body") or d.get("content") or "")
            tags = d.get("tags") if isinstance(d.get("tags"), list) else None
            terms = safe_text(d.get("terms") or "")

            item_id = None
            try:
                if hasattr(memory, "store_canon_item"):
                    item_id = memory.store_canon_item(
                        project_id=project_id,
                        role_id=role_id,
                        type=d_type,
                        title=title,
                        body=body,
                        tags=tags,
                        terms=terms,
                    )
                elif hasattr(memory, "save_canon_items"):
                    ids = memory.save_canon_items([{
                        "project_id": project_id,
                        "role_id": role_id,
                        "type": d_type,
                        "title": title,
                        "body": body,
                        "tags": tags,
                        "terms": terms,
                    }]) or []
                    item_id = ids[0] if ids else None
            except Exception as e:
                print(f"[Canon persist error] {e}")

            try:
                if hasattr(memory, "insert_audit_log"):
                    memory.insert_audit_log(
                        project_id, role_id, session_id_for_audit, "internal", "canon_insert",
                        f"{d_type}: {title}"[:300],
                    )
            except Exception:
                pass

            saved.append({
                "id": item_id,
                "type": d_type,
                "title": title,
            })

    except Exception as e:
        print(f"[Canon extractor error] {e}")

    return saved


# ====== ROUTES ======

@router.get("/last-session-by-role")
def get_last_session_by_role(
    role_id: int,
    project_id: str,
    limit: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns the last session for a given role/project (from memory_entries).
    Always returns a consistent shape (messages & summaries arrays).
    """
    try:
        return _build_last_session_payload(
            db, role_id=role_id, project_id=project_id, limit=limit
        )
    except Exception as e:
        print(f"❌ Error in /last-session-by-role: {e}")
        return _empty_payload(project_id, role_id)


@router.get("/last-session")
def get_last_session_legacy(db: Session = Depends(get_db)):
    """
    Legacy endpoint for frontend compatibility.
    Returns most recent known session (from memory_entries).
    """
    try:
        memory = MemoryManager(db)
        last = memory.get_last_session()
        if not last:
            return _empty_payload(project_id="", role_id=None)

        return _build_last_session_payload(
            db,
            role_id=int(last["role_id"]),
            project_id=str(last["project_id"]),
            limit=20,
        )

    except Exception as e:
        print(f"❌ Error in /last-session: {e}")
        return _empty_payload(project_id="", role_id=None)


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns chat history and summaries for the given (optional) session,
    sourced from memory_entries. Always returns a valid shape.
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

        summaries_raw = memory.load_recent_summaries(
            project_id=project_id, role_id=role_id, limit=5
        )
        summaries = [ChatSummary(summary=safe_text(s), timestamp=None) for s in summaries_raw]

        return ChatHistoryResponse(messages=messages, summaries=summaries)

    except Exception as e:
        print(f"❌ Error in /history: {e}")
        return ChatHistoryResponse(messages=[], summaries=[])


# ====== SUMMARIZE (+ optional rotation + canon persist) ======

@router.post("/summarize")
def summarize_chat(req: ChatSummarizeRequest, db: Session = Depends(get_db)):
    """
    Summarize the current chat session, persist a divider message, optionally rotate,
    and (when enabled) extract & persist Canon deltas.
    """
    try:
        project_id = str(req.project_id).strip()
        role_id = int(req.role_id)
        session_id = safe_text(req.chat_session_id or "")

        memory = MemoryManager(db)

        # Resolve session if not provided
        if not session_id:
            last = memory.get_last_session(role_id=role_id, project_id=project_id)
            session_id = _get_last_session_id_from_record(last)

        # Retrieve messages (last 200) to summarize
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

        # Token count to decide auto-rotation
        total_tokens = 0
        try:
            if hasattr(memory, "count_tokens"):
                total_tokens = sum(memory.count_tokens(safe_text(m.get("text", ""))) for m in msgs)
        except Exception:
            total_tokens = 0

        # Summarize
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

        # Persist divider in the *current* session
        try:
            # ✅ MemoryManager in your codebase expects `text` (not `content`)
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
        try:
            threshold = int(getattr(settings, "SUMMARIZE_TRIGGER_TOKENS", 2000))
            if not should_rotate and total_tokens and total_tokens >= threshold:
                should_rotate = True
                try:
                    memory.insert_audit_log(
                        project_id, role_id, session_id or "", "internal", "autosummarize_trigger",
                        f"total_tokens={total_tokens} threshold={threshold}"
                    )
                except Exception:
                    pass
        except Exception:
            pass

        # Best-effort Canon extraction/persist (behind flag, safe no-op otherwise)
        saved: List[Dict[str, Any]] = []
        try:
            source_for_deltas = combined_text if len(combined_text) >= 200 else summary_text
            saved = _extract_and_persist_canon(
                memory=memory,
                project_id=project_id,
                role_id=role_id,
                source_text=source_for_deltas,
                session_id_for_audit=session_id or "",
            )
        except Exception as e:
            print(f"[Canon step error] {e}")

        resp: Dict[str, Any] = {
            "ok": True,
            "project_id": project_id,
            "role_id": role_id,
            "chat_session_id": session_id,
            "divider_message": divider_message,
        }

        if saved:
            resp["saved"] = saved

        if should_rotate:
            new_session_id = str(uuid4())
            resp["new_chat_session_id"] = new_session_id

        return resp

    except Exception as e:
        print(f"❌ Error in /summarize: {e}")
        raise HTTPException(status_code=500, detail="Summarization failed")
