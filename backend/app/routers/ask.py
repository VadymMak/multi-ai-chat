from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator
from typing import Literal, Union, Optional
from sqlalchemy.orm import Session
from uuid import uuid4

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager
from app.memory.db import get_db
from app.prompts.prompt_builder import generate_prompt_from_db

router = APIRouter()


class AskRequest(BaseModel):
    query: str
    provider: Literal["openai", "anthropic", "all"]
    role_id: int
    project_id: Optional[Union[int, str]] = None
    chat_session_id: Optional[str] = None

    @validator("role_id")
    def role_id_positive(cls, value):
        if value <= 0:
            raise ValueError("role_id must be a positive integer")
        return value

    @validator("project_id", pre=True, always=True)
    def project_id_safe(cls, v):
        if v in (None, "default", ""):
            return "0"
        return str(v).strip()


MAX_TOKENS_BEFORE_SUMMARY = 2000


async def check_token_limit_and_summarize(memory: MemoryManager, role_id: int, project_id: str, chat_session_id: Optional[str]):
    try:
        messages = memory.retrieve_messages(
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            limit=1000
        )
        if not messages or len(messages) < 2:
            return

        total_tokens = sum(memory.count_tokens(m["text"]) for m in messages)
        print(f"🔍 Token check → total={total_tokens}, threshold={MAX_TOKENS_BEFORE_SUMMARY}")

        if total_tokens <= MAX_TOKENS_BEFORE_SUMMARY:
            return

        combined_text = "\n".join(f"{m['sender']}: {m['text']}" for m in messages)[:4000]
        summary = memory.summarize_messages([combined_text])
        memory.store_memory(project_id, role_id, summary, combined_text, chat_session_id)
        memory.delete_chat_messages(project_id, role_id, chat_session_id)
        memory.store_chat_message(project_id, role_id, chat_session_id, "system", "📌 New Phase After Summarization")
        print("✅ Auto-summary stored.")
    except Exception as e:
        print(f"❌ Summarization error: {e}")


@router.post("/ask", tags=["Chat"])
async def ask_route(data: AskRequest, db: Session = Depends(get_db)):
    """
    Handles user queries and routes them to selected AI provider(s).
    Stores message history, triggers summarization if needed, and returns replies.
    """
    memory = MemoryManager(db)
    role_id = data.role_id
    project_id = data.project_id or "0"
    chat_session_id = data.chat_session_id or str(uuid4())

    print(f"\n💬 Incoming /ask → role_id={role_id}, project_id={project_id}, session={chat_session_id}, provider={data.provider}")
    print(f"📝 User message: {data.query[:100]}")

    try:
        memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.query)
        memory.insert_audit_log(project_id, role_id, chat_session_id, data.provider, "ask", query=data.query)
        await check_token_limit_and_summarize(memory, role_id, project_id, chat_session_id)

        full_prompt = generate_prompt_from_db(
            db=db,
            project_id=project_id,
            role_id=role_id,
            system_prompt="You are a helpful assistant.",
            youtube_context=[],
            web_context=[],
            starter_reply="",
            user_input=data.query,
            max_memory_tokens=600,
        )

        def store_and_respond(sender: str, text: str):
            memory.store_chat_message(project_id, role_id, chat_session_id, sender, text)
            memory.insert_audit_log(project_id, role_id, chat_session_id, sender, "reply", text[:300])
            return {
                "provider": sender,
                "answer": text,
                "chat_session_id": chat_session_id
            }

        if data.provider == "openai":
            answer = ask_openai([{"role": "user", "content": data.query}], system_prompt=full_prompt) or "[OpenAI Error]"
            return store_and_respond("openai", answer)

        if data.provider == "anthropic":
            answer = ask_claude([{"role": "user", "content": data.query}], system=full_prompt) or "[Claude Error]"
            return store_and_respond("anthropic", answer)

        if data.provider == "all":
            openai_reply = ask_openai([{"role": "user", "content": data.query}], system_prompt=full_prompt) or "[OpenAI Error]"
            claude_reply = ask_claude([{"role": "user", "content": data.query}], system=full_prompt) or "[Claude Error]"

            summary_prompt = f"""Please summarize both AI responses in a fair and balanced way.

OpenAI:
{openai_reply}

Claude:
{claude_reply}
"""
            final_summary = ask_openai(
                [{"role": "user", "content": summary_prompt}],
                system_prompt=full_prompt
            ) or "[Summary Error]"

            memory.store_chat_message(project_id, role_id, chat_session_id, "openai", openai_reply)
            memory.insert_audit_log(project_id, role_id, chat_session_id, "openai", "reply", openai_reply[:300])

            memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_reply)
            memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "reply", claude_reply[:300])

            memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_summary)
            memory.insert_audit_log(project_id, role_id, chat_session_id, "internal", "summary", final_summary[:300])

            return {
                "provider": "all",
                "openai": openai_reply,
                "claude": claude_reply,
                "summary": final_summary,
                "chat_session_id": chat_session_id,
            }

    except Exception as e:
        print(f"❌ Error in ask_route: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=400, detail="Unsupported provider")
