from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, validator
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.memory.utils import safe_text

router = APIRouter(prefix="/chat", tags=["Chat"])


# ====== MODELS ======

class ChatSummarizeRequest(BaseModel):
    role_id: int
    project_id: str
    chat_session_id: Optional[str] = None

    @validator("project_id")
    def validate_project_id(cls, v):
        if not isinstance(v, str) or not v.strip().isalnum():
            raise ValueError("project_id must be a non-empty alphanumeric string")
        return v


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


# ====== ROUTES ======

@router.get("/last-session-by-role")
def get_last_session_by_role(
    role_id: int,
    project_id: str,
    limit: int = Query(20),
    db: Session = Depends(get_db)
):
    """
    Returns last session for given role/project.
    Always returns a consistent shape with messages & summaries arrays.
    """
    try:
        print(f"📅 Looking up last session for role_id={role_id}, project_id={project_id}")

        row = db.execute(sql_text("""
            SELECT cm.project_id, cm.role_id, cm.chat_session_id, r.name AS role_name
            FROM chat_messages cm
            JOIN roles r ON cm.role_id = r.id
            WHERE cm.project_id = :project_id 
              AND cm.role_id = :role_id
              AND cm.chat_session_id IS NOT NULL
            ORDER BY cm.timestamp DESC
            LIMIT 1
        """), {
            "project_id": project_id,
            "role_id": role_id
        }).mappings().first()

        session_id = ""
        role_name = ""

        if row:
            session_id = safe_text(row["chat_session_id"] or "")
            role_name = safe_text(row["role_name"] or "")
            print(f"✅ Found session in chat_messages → {dict(row)}")
        else:
            print("⚠️ No chat_messages found — checking memory_entries...")
            memory = MemoryManager(db)
            session = memory.get_last_session(role_id=role_id, project_id=project_id)
            if session and session.get("chat_session_id"):
                session_id = session["chat_session_id"]
                role_name = session.get("role_name", "")
            else:
                print("ℹ️ No previous session found, returning empty result")
                return {
                    "project_id": project_id,
                    "role_id": role_id,
                    "role_name": "",
                    "chat_session_id": "",
                    "messages": [],
                    "summaries": []
                }

        # Fetch messages
        messages: List[ChatMessage] = []
        if session_id:
            result = db.execute(sql_text("""
                SELECT sender, text, role_id, project_id, chat_session_id, is_summary, timestamp
                FROM chat_messages
                WHERE project_id = :project_id 
                  AND role_id = :role_id
                  AND chat_session_id = :chat_session_id
                ORDER BY timestamp ASC
                LIMIT :limit
            """), {
                "project_id": project_id,
                "role_id": role_id,
                "chat_session_id": session_id,
                "limit": int(limit)
            }).mappings().all()

            messages = [
                ChatMessage(
                    sender=safe_text(row["sender"]),
                    text=safe_text(row["text"] or ""),
                    role_id=row["role_id"],
                    project_id=str(row["project_id"]),
                    chat_session_id=safe_text(row["chat_session_id"] or ""),
                    isTyping=False,
                    isSummary=bool(row["is_summary"])
                )
                for row in result if row["text"] and row["text"].strip()
            ]

        memory = MemoryManager(db)
        summaries_raw = memory.load_recent_summaries(role_id=role_id, project_id=project_id, limit=5)
        summaries = [ChatSummary(summary=safe_text(s), timestamp=None) for s in summaries_raw]

        return {
            "project_id": project_id,
            "role_id": role_id,
            "role_name": role_name,
            "chat_session_id": session_id,
            "messages": messages,
            "summaries": summaries
        }

    except Exception as e:
        print(f"❌ Error in /last-session-by-role: {e}")
        return {
            "project_id": project_id,
            "role_id": role_id,
            "role_name": "",
            "chat_session_id": "",
            "messages": [],
            "summaries": []
        }


@router.get("/last-session")
def get_last_session_legacy(db: Session = Depends(get_db)):
    """
    Legacy endpoint for frontend compatibility.
    Returns most recent known session for any role/project.
    """
    try:
        row = db.execute(sql_text("""
            SELECT role_id, project_id
            FROM chat_messages
            WHERE chat_session_id IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1
        """)).mappings().first()

        if not row:
            return {
                "chat_session_id": "",
                "role_id": None,
                "project_id": None,
                "role_name": "",
                "messages": [],
                "summaries": []
            }

        return get_last_session_by_role(
            role_id=row["role_id"],
            project_id=str(row["project_id"]),
            db=db
        )

    except Exception as e:
        print(f"❌ Error in fallback /last-session: {e}")
        return {
            "chat_session_id": "",
            "role_id": None,
            "project_id": None,
            "role_name": "",
            "messages": [],
            "summaries": []
        }


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    limit: int = Query(20),
    db: Session = Depends(get_db),
):
    """
    Returns chat history and summaries for the given session.
    Always returns a valid shape — never 404.
    """
    if not project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project_id")

    try:
        print(f"📅 Fetching history for role_id={role_id}, project_id={project_id}, session={chat_session_id}")

        result = db.execute(sql_text("""
            SELECT sender, text, role_id, project_id, chat_session_id, is_summary, timestamp
            FROM chat_messages
            WHERE project_id = :project_id 
              AND role_id = :role_id
              AND (:chat_session_id IS NULL OR chat_session_id = :chat_session_id)
            ORDER BY timestamp ASC
            LIMIT :limit
        """), {
            "project_id": project_id,
            "role_id": role_id,
            "chat_session_id": chat_session_id,
            "limit": int(limit)
        }).mappings().all()

        messages = [
            ChatMessage(
                sender=safe_text(row["sender"]),
                text=safe_text(row["text"] or ""),
                role_id=row["role_id"],
                project_id=str(row["project_id"]),
                chat_session_id=safe_text(row["chat_session_id"] or ""),
                isTyping=False,
                isSummary=bool(row["is_summary"])
            )
            for row in result if row["text"] and row["text"].strip()
        ]

        memory = MemoryManager(db)
        summaries_raw = memory.load_recent_summaries(role_id=role_id, project_id=project_id, limit=5)
        summaries = [ChatSummary(summary=safe_text(s), timestamp=None) for s in summaries_raw]

        return ChatHistoryResponse(messages=messages, summaries=summaries)

    except Exception as e:
        print(f"❌ Error in /history: {e}")
        return ChatHistoryResponse(messages=[], summaries=[])
