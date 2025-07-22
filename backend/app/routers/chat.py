from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, validator
from typing import Optional, List
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.manager import MemoryManager

router = APIRouter(prefix="/chat", tags=["Chat"])


# ✅ Request model
class ChatSummarizeRequest(BaseModel):
    role_id: int
    project_id: str
    chat_session_id: Optional[str] = None

    @validator("project_id")
    def validate_project_id(cls, v):
        if not isinstance(v, str) or not v.strip().isalnum():
            raise ValueError("project_id must be a non-empty alphanumeric string")
        return v


# ✅ Response models
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


# ✅ GET /chat/last-session
@router.get("/last-session")
async def get_last_session(db: Session = Depends(get_db)):
    memory = MemoryManager(db)
    try:
        print("📥 Looking up last active chat session...")
        session = memory.get_last_session()
        if not session:
            raise HTTPException(status_code=404, detail="No session found")
        return session
    except Exception as e:
        print(f"❌ Failed to get last session: {e}")
        raise HTTPException(status_code=500, detail="Failed to load last session")


# ✅ GET /chat/stats
@router.get("/stats")
async def get_chat_stats(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project_id format")

    memory = MemoryManager(db)
    try:
        print(f"📥 Fetching stats → role_id={role_id}, project_id={project_id}, session={chat_session_id}")
        messages = memory.retrieve_messages(
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            limit=1000
        )
        token_count = sum(memory.count_tokens(m.get("text") or m.get("content", "")) for m in messages)
        print(f"📊 /chat/stats → Tokens: {token_count}, Messages: {len(messages)}")
        return {
            "token_count": token_count,
            "message_count": len(messages),
            "model": "gpt-4o",
            "over_limit": token_count > 7000
        }
    except Exception as e:
        print(f"❌ Failed to retrieve stats: {e}")
        raise HTTPException(status_code=500, detail=f"Memory retrieval failed: {e}")


# ✅ POST /chat/summarize
@router.post("/summarize")
async def summarize_chat(
    data: ChatSummarizeRequest,
    db: Session = Depends(get_db),
):
    if not isinstance(data.project_id, str) or not data.project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project_id")

    memory = MemoryManager(db)
    try:
        print(f"📥 Summarization request → role_id={data.role_id}, project_id={data.project_id}, session={data.chat_session_id}")
        messages = memory.retrieve_messages(
            role_id=data.role_id,
            project_id=data.project_id,
            chat_session_id=data.chat_session_id,
            limit=1000
        )

        if not messages or len(messages) < 2:
            raise HTTPException(status_code=400, detail="Not enough messages to summarize.")

        combined_text = "\n".join(
            f"{m.get('sender', m.get('role', 'system'))}: {m.get('text', m.get('content', ''))}"
            for m in messages
        )
        trimmed_text = combined_text[:4000]

        print(f"🔍 Summarizing {len(trimmed_text)} characters across {len(messages)} messages...")

        summary = memory.summarize_messages([trimmed_text])

        memory.store_memory(
            role_id=data.role_id,
            project_id=data.project_id,
            chat_session_id=data.chat_session_id,
            summary=summary,
            raw_text=trimmed_text
        )

        # ✅ Audit log insertion
        memory.insert_audit_log(
            project_id=data.project_id,
            role_id=data.role_id,
            chat_session_id=data.chat_session_id,
            provider="internal",
            action="summarize",
            query=trimmed_text[:300]
        )

        print(f"✅ Summary stored and audit logged successfully.")
        return {
            "summary": summary,
            "cleared": False
        }

    except Exception as e:
        print(f"❌ Summarization failed: {e}")
        raise HTTPException(status_code=500, detail=f"Summarization failed: {e}")


# ✅ GET /chat/history
@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    role_id: int = Query(...),
    project_id: str = Query(...),
    chat_session_id: Optional[str] = Query(None),
    limit: int = Query(20),
    db: Session = Depends(get_db),
):
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project_id")

    memory = MemoryManager(db)
    try:
        print(f"📥 History request → role_id={role_id}, project_id={project_id}, session={chat_session_id}")
        raw_messages = memory.retrieve_messages(
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            limit=limit
        )

        messages: List[ChatMessage] = []
        for m in raw_messages:
            try:
                messages.append(ChatMessage(
                    sender=m.get("sender", m.get("role", "system")),
                    text=m.get("text", m.get("content", "")),
                    role_id=int(m.get("role_id", role_id)),
                    project_id=str(m.get("project_id", project_id)),
                    chat_session_id=m.get("chat_session_id", chat_session_id),
                    isTyping=m.get("isTyping", False),
                    isSummary=m.get("isSummary", False)
                ))
            except Exception as err:
                print(f"⚠️ Skipped malformed message: {m} → {err}")

        summaries_raw = memory.load_recent_summaries(
            role_id=role_id,
            project_id=project_id,
            limit=5
        )
        summaries = [ChatSummary(summary=s, timestamp=None) for s in summaries_raw]

        print(f"✅ History retrieved: {len(messages)} messages, {len(summaries)} summaries")
        return ChatHistoryResponse(messages=messages, summaries=summaries)

    except Exception as e:
        print(f"❌ Failed to retrieve history: {e}")
        raise HTTPException(status_code=500, detail="Failed to load chat history.")
