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
    id: Optional[Union[str, int]] = None
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
    attachments: Optional[List[Dict[str, Any]]] = None


class ChatSummary(BaseModel):
    summary: str
    timestamp: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    messages: List[ChatMessage]
    summaries: List[ChatSummary]


# ====== CODING CONTEXT DETECTION ======

def detect_coding_context(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Detect if conversation involves coding/technical content to adjust token limits.
    
    Returns:
        {
            "is_coding": bool,
            "confidence": float (0-1),
            "indicators": List[str],
            "suggested_limit": int
        }
    """
    if not messages:
        return {
            "is_coding": False,
            "confidence": 0.0,
            "indicators": [],
            "suggested_limit": 6000
        }
    
    # Coding indicators with weights
    indicators = {
        "code_blocks": 0,
        "file_extensions": 0,
        "programming_keywords": 0,
        "error_messages": 0,
        "api_patterns": 0,
        "function_signatures": 0,
        "import_statements": 0,
    }
    
    # Patterns to detect
    code_block_pattern = re.compile(r'```[\s\S]*?```', re.MULTILINE)
    file_extension_pattern = re.compile(r'\.(py|js|ts|jsx|tsx|java|cpp|c|h|cs|go|rb|php|swift|kt|rs|sql|html|css|json|xml|yaml|yml)\b', re.IGNORECASE)
    programming_keywords = re.compile(r'\b(function|class|import|export|const|let|var|def|async|await|return|if|else|for|while|try|catch|throw|interface|type|enum)\b', re.IGNORECASE)
    error_pattern = re.compile(r'\b(error|exception|traceback|stack trace|undefined|null pointer|segmentation fault|syntax error)\b', re.IGNORECASE)
    api_pattern = re.compile(r'\b(GET|POST|PUT|DELETE|PATCH|endpoint|REST|API|HTTP|request|response)\b')
    function_signature = re.compile(r'\w+\s*\([^)]*\)\s*[{:]')
    import_statement = re.compile(r'\b(import|from|require|include|use)\s+[\w.]+', re.IGNORECASE)
    
    # Analyze recent messages (weight recent messages more)
    recent_weight = 1.5
    for idx, msg in enumerate(messages[-20:]):  # Last 20 messages
        text = safe_text(msg.get("text", ""))
        weight = recent_weight if idx >= len(messages[-20:]) - 5 else 1.0
        
        # Count indicators
        if code_block_pattern.search(text):
            indicators["code_blocks"] += 1 * weight
        
        if file_extension_pattern.search(text):
            indicators["file_extensions"] += len(file_extension_pattern.findall(text)) * weight
        
        if programming_keywords.search(text):
            indicators["programming_keywords"] += len(programming_keywords.findall(text)) * weight * 0.1
        
        if error_pattern.search(text):
            indicators["error_messages"] += len(error_pattern.findall(text)) * weight
        
        if api_pattern.search(text):
            indicators["api_patterns"] += len(api_pattern.findall(text)) * weight * 0.5
        
        if function_signature.search(text):
            indicators["function_signatures"] += len(function_signature.findall(text)) * weight
        
        if import_statement.search(text):
            indicators["import_statements"] += len(import_statement.findall(text)) * weight
    
    # Calculate confidence score
    score = 0.0
    score += min(indicators["code_blocks"] * 15, 50)  # Code blocks are strong indicators
    score += min(indicators["file_extensions"] * 8, 30)
    score += min(indicators["programming_keywords"] * 0.5, 20)
    score += min(indicators["error_messages"] * 10, 25)
    score += min(indicators["api_patterns"] * 5, 15)
    score += min(indicators["function_signatures"] * 8, 25)
    score += min(indicators["import_statements"] * 8, 20)
    
    confidence = min(score / 100, 1.0)
    is_coding = confidence >= 0.3
    
    # Determine suggested token limit
    if confidence >= 0.7:
        suggested_limit = 12000  # High coding context - need more tokens
    elif confidence >= 0.5:
        suggested_limit = 9000   # Moderate coding context
    elif confidence >= 0.3:
        suggested_limit = 7000   # Light coding context
    else:
        suggested_limit = 6000   # Default for general conversation
    
    # Build indicator list for logging
    active_indicators = [k for k, v in indicators.items() if v > 0]
    
    return {
        "is_coding": is_coding,
        "confidence": round(confidence, 2),
        "indicators": active_indicators,
        "suggested_limit": suggested_limit,
        "indicator_counts": {k: round(v, 1) for k, v in indicators.items() if v > 0}
    }


# ====== INTERNAL HELPERS ======

def _row_to_message(
    row: Dict[str, Any],
    *,
    fallback_role_id: int,
    fallback_project_id: str,
    fallback_session_id: str,
    db: Session = None,  # ✅ ДОБАВЬ параметр
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

    # ✅ ДОБАВЬ: Extract message ID
    message_id = row.get("id")
    if message_id is not None:
        message_id = str(message_id)
    
    # ✅ ДОБАВЬ: Load attachments from DB
    attachments = []
    if db and message_id:
        try:
            from app.memory.models import Attachment
            attachment_records = db.query(Attachment).filter(
                Attachment.message_id == int(message_id)
            ).all()
            
            for att in attachment_records:
                attachments.append({
                    "id": att.id,
                    "name": att.original_filename,
                    "original_filename": att.original_filename,
                    "file_type": att.file_type,
                    "mime": att.mime_type,
                    "url": f"http://localhost:8000/api/uploads/{att.id}",
                    "size": att.file_size,
                    "uploaded_at": att.uploaded_at.isoformat() if att.uploaded_at else None,
                })
        except Exception as e:
            print(f"⚠️ Failed to load attachments for message {message_id}: {e}")

    return ChatMessage(
        id=message_id,  # ✅ УЖЕ ЕСТЬ
        sender=sender,
        text=text,
        role_id=role_id,
        project_id=project_id,
        chat_session_id=chat_session_id,
        isTyping=False,
        isSummary=is_summary,
        attachments=attachments if attachments else None,  # ✅ ДОБАВЬ
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
    Now includes smart coding context detection for dynamic token limits.
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
    messages_data = memory.retrieve_messages(
        project_id=project_id,
        role_id=role_id,
        chat_session_id=session_id if session_id else None,
        limit=int(limit),
        for_display=True,  # ← FULL MESSAGES FOR UI!
    )
    
    # Extract messages from dict response
    messages_raw = messages_data.get("messages", [])
    total_tokens = messages_data.get("total_tokens", 0)
    max_tokens = messages_data.get("max_tokens", 6000)
    
    # 🎯 Detect coding context and adjust token limits
    coding_context = detect_coding_context(messages_raw)
    if coding_context["is_coding"]:
        max_tokens = coding_context["suggested_limit"]
        print(f"🔍 Coding context detected (confidence: {coding_context['confidence']}) - adjusted max_tokens to {max_tokens}")
        print(f"   Indicators: {', '.join(coding_context['indicators'][:5])}")

    messages: List[ChatMessage] = []
    for m in messages_raw:
        msg = _row_to_message(
            m,
            fallback_role_id=role_id,
            fallback_project_id=project_id,
            fallback_session_id=session_id,
            db=db,
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
        "total_tokens": total_tokens,
        "max_tokens": max_tokens,
        "usage_percent": round((total_tokens / max_tokens) * 100, 1) if max_tokens > 0 else 0,
        "message_count": len(messages),
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

        messages_data = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            limit=int(limit),
            for_display=True,  # ← FULL MESSAGES FOR UI!
        )
        
        # Extract messages and token info from dict response
        msgs = messages_data.get("messages", [])
        total_tokens = messages_data.get("total_tokens", 0)
        max_tokens = messages_data.get("max_tokens", 6000)
        
        # 🎯 Detect coding context and adjust token limits
        coding_context = detect_coding_context(msgs)
        if coding_context["is_coding"]:
            max_tokens = coding_context["suggested_limit"]
            print(f"🔍 Coding context detected in history (confidence: {coding_context['confidence']}) - adjusted max_tokens to {max_tokens}")
            print(f"   Indicators: {', '.join(coding_context['indicators'][:5])}")

        messages: List[ChatMessage] = []
        for m in msgs:
            msg = _row_to_message(
                m,
                fallback_role_id=role_id,
                fallback_project_id=project_id,
                fallback_session_id=chat_session_id or "",
                db=db,
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

        # Create response with token info
        response_data = {
            "messages": messages,
            "summaries": summaries,
            "total_tokens": total_tokens,
            "max_tokens": max_tokens,
            "usage_percent": round((total_tokens / max_tokens) * 100, 1) if max_tokens > 0 else 0,
            "message_count": len(messages),
        }
        
        return response_data

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
        messages_data = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=session_id or None,
            limit=200,
        )
        
        # Extract messages from dict response
        msgs = messages_data.get("messages", [])

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
    
# ====== MANUAL SUMMARY ENDPOINT ======

@router.post("/manual-summary")
async def create_manual_summary(
    project_id: str = Query(...),
    role_id: int = Query(...),
    chat_session_id: str = Query(...),
    message_count: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Manually trigger summarization for a session.
    
    Args:
        project_id: Project ID
        role_id: Role ID
        chat_session_id: Session ID to summarize
        message_count: Number of recent messages to include (default: 20)
    
    Returns:
        Summary text and metadata
    """
    print(f"[Manual Summary] project={project_id}, role={role_id}, session={chat_session_id}")
    
    try:
        manager = MemoryManager(db)
        
        # Get recent messages for preview
        messages_data = manager.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            limit=message_count,
            include_summaries=False
        )
        
        messages = messages_data.get("messages", [])
        
        if not messages:
            return {
                "success": False,
                "error": "No messages found to summarize"
            }
        
        # Create summary text
        message_texts = [f"{m['sender']}: {m['text']}" for m in messages]
        summary_text = manager.summarize_messages(message_texts)
        
        # Store summary
        summary_entry = manager.store_memory(
            project_id=project_id,
            role_id=role_id,
            summary=summary_text,
            raw_text=f"Manual summary of {len(messages)} messages",
            chat_session_id=chat_session_id,
            is_ai_to_ai=False
        )
        
        return {
            "success": True,
            "summary_id": summary_entry.id,
            "summary_text": summary_text,
            "message_count": len(messages),
            "tokens_saved": messages_data.get("total_tokens", 0)
        }
        
    except Exception as e:
        print(f"[Manual Summary Error] → {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ====== DEBUG ENDPOINT FOR CONTEXT DETECTION ======

@router.get("/debug/coding-context")
def debug_coding_context(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to test coding context detection on current session.
    Returns detailed analysis of coding indicators and confidence score.
    """
    try:
        memory = MemoryManager(db)
        
        messages_data = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            limit=int(limit),
        )
        
        msgs = messages_data.get("messages", [])
        
        # Run context detection
        coding_context = detect_coding_context(msgs)
        
        # Build detailed response
        return {
            "session_info": {
                "role_id": role_id,
                "project_id": project_id,
                "chat_session_id": chat_session_id or "N/A",
                "messages_analyzed": len(msgs),
            },
            "detection_result": {
                "is_coding": coding_context["is_coding"],
                "confidence": coding_context["confidence"],
                "suggested_limit": coding_context["suggested_limit"],
                "default_limit": 6000,
                "limit_increase": coding_context["suggested_limit"] - 6000,
            },
            "indicators": coding_context.get("indicator_counts", {}),
            "active_indicators": coding_context["indicators"],
            "confidence_thresholds": {
                "light_coding": 0.3,
                "moderate_coding": 0.5,
                "high_coding": 0.7,
            },
            "token_limits": {
                "default": 6000,
                "light_coding": 7000,
                "moderate_coding": 9000,
                "high_coding": 12000,
            },
            "sample_messages": [
                {
                    "sender": m.get("sender", "unknown"),
                    "text_preview": safe_text(m.get("text", ""))[:100] + "..." if len(safe_text(m.get("text", ""))) > 100 else safe_text(m.get("text", "")),
                }
                for m in msgs[-5:]  # Last 5 messages
            ]
        }
        
    except Exception as e:
        print(f"❌ Error in debug endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Debug analysis failed: {str(e)}"
        )


# ====== MESSAGE MANAGEMENT (Edit, Delete, Regenerate) ======

class MessageUpdateRequest(BaseModel):
    """Запрос на редактирование сообщения"""
    text: str


@router.put("/messages/{message_id}")
def update_message(
    message_id: int,  # ✅ Изменено на int
    request: MessageUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Редактирование сообщения (только user messages)
    """
    try:
        # Валидация
        if not request.text or not request.text.strip():
            raise HTTPException(
                status_code=400,
                detail="Message text cannot be empty"
            )
        
        # Поиск сообщения
        from app.memory.models import MemoryEntry as DBMessage
        from app.memory.utils import safe_text
        
        message = db.query(DBMessage).filter(
            DBMessage.id == message_id
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail=f"Message {message_id} not found"
            )
        
        # ✅ Извлекаем sender из raw_text
        raw_text = safe_text(message.raw_text or "")
        sender = "user"
        if ":" in raw_text:
            sender = raw_text.split(":", 1)[0].strip()
        
        # Проверка что это user message
        if sender.lower() != "user":
            raise HTTPException(
                status_code=403,
                detail="Can only edit user messages"
            )
        
        # ✅ Обновление raw_text в правильном формате
        new_text = safe_text(request.text.strip())
        message.raw_text = f"user: {new_text}"
        message.summary = new_text[:2000]  # Обновляем preview
        
        # Обновляем timestamp
        if hasattr(message, 'updated_at'):
            from datetime import datetime
            message.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(message)
        
        print(f"✅ Message {message_id} updated")
        
        return {
            "success": True,
            "message": {
                "id": message.id,
                "text": new_text,
                "sender": "user",
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error updating message {message_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update message: {str(e)}"
        )


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,  # ✅ Изменено на int
    db: Session = Depends(get_db),
):
    """
    Удаление сообщения (soft delete)
    """
    try:
        from app.memory.models import MemoryEntry as DBMessage
        
        # Поиск
        message = db.query(DBMessage).filter(
            DBMessage.id == message_id
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail=f"Message {message_id} not found"
            )
        
        print(f"🗑️ Deleting message {message_id}")
        
        # Soft delete
        if hasattr(message, 'deleted'):
            message.deleted = True
            if hasattr(message, 'updated_at'):
                from datetime import datetime
                message.updated_at = datetime.utcnow()
            db.commit()
        else:
            # Hard delete если нет поля deleted
            db.delete(message)
            db.commit()
        
        print(f"✅ Message {message_id} deleted")
        
        return {
            "success": True,
            "message": f"Message {message_id} deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error deleting message {message_id}: {e}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete message: {str(e)}"
        )


@router.post("/messages/{message_id}/regenerate")
def regenerate_message(
    message_id: int,  # ✅ Изменено на int
    db: Session = Depends(get_db),
):
    """
    Регенерация AI ответа (placeholder)
    """
    try:
        from app.memory.models import MemoryEntry as DBMessage
        from app.memory.utils import safe_text
        
        # Поиск
        message = db.query(DBMessage).filter(
            DBMessage.id == message_id
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=404,
                detail=f"Message {message_id} not found"
            )
        
        # ✅ Извлекаем sender из raw_text
        raw_text = safe_text(message.raw_text or "")
        sender = "assistant"
        if ":" in raw_text:
            sender = raw_text.split(":", 1)[0].strip()
        
        # Проверка что это AI message
        if sender.lower() == "user":
            raise HTTPException(
                status_code=400,
                detail="Cannot regenerate user messages"
            )
        
        print(f"🔄 Regenerate requested for message {message_id}")
        
        return {
            "success": True,
            "message": "Regeneration coming soon!",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error regenerating message {message_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate message: {str(e)}"
        )
