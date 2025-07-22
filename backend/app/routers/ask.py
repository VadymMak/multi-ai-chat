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

router = APIRouter()  # ✅ API prefix here

# ✅ Request model
class AskRequest(BaseModel):
    query: str
    provider: Literal["openai", "anthropic", "all"]
    role_id: int
    project_id: Optional[Union[int, str]] = None
    chat_session_id: Optional[str] = None

    @validator("role_id")
    def role_id_must_be_positive(cls, value):
        if value <= 0:
            raise ValueError("role_id must be a positive integer")
        return value

    @validator("project_id", pre=True, always=True)
    def validate_project_id(cls, v):
        if v in (None, "default", ""):
            return "0"
        try:
            return str(v).strip()
        except Exception:
            raise ValueError("Invalid project_id format")


MAX_TOKENS_BEFORE_SUMMARY = 2000


# ✅ Token check + auto-summarize if too long
async def check_token_limit_and_summarize(
    memory: MemoryManager,
    role_id: int,
    project_id: str,
    chat_session_id: Optional[str] = None
) -> None:
    try:
        messages = memory.retrieve_messages(
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            limit=1000
        )
        if not messages or len(messages) < 2:
            return

        token_count = sum(memory.count_tokens(m["text"]) for m in messages)
        print(f"🔍 Token check → total={token_count}, threshold={MAX_TOKENS_BEFORE_SUMMARY}")

        if token_count <= MAX_TOKENS_BEFORE_SUMMARY:
            return

        combined_text = "\n".join([f"{m['sender']}: {m['text']}" for m in messages])[:4000]
        summary = memory.summarize_messages([combined_text])
        memory.store_memory(
            role_id=role_id,
            project_id=project_id,
            chat_session_id=chat_session_id,
            summary=summary,
            raw_text=combined_text
        )

        memory.delete_chat_messages(project_id, role_id, chat_session_id)
        memory.store_chat_message(project_id, role_id, chat_session_id, "system", "📌 New Phase After Summarization")

        print("✅ Auto-summary stored and history cleared.")
    except Exception as e:
        print(f"❌ Token limit/summarization error: {e}")


# ✅ POST /ask
@router.post("/ask")
async def ask_route(data: AskRequest, db: Session = Depends(get_db)):
    memory = MemoryManager(db)

    role_id = data.role_id
    project_id = data.project_id
    chat_session_id = data.chat_session_id or str(uuid4())

    if not project_id.strip():
        raise HTTPException(status_code=400, detail="Invalid project_id")

    # ✅ Log user input
    memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.query)
    memory.insert_audit_log(project_id, role_id, chat_session_id, data.provider, "ask", query=data.query)

    await check_token_limit_and_summarize(memory, role_id, project_id, chat_session_id)

    # ✅ Generate prompt
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

    def store_and_return(sender: str, content: str):
        memory.store_chat_message(project_id, role_id, chat_session_id, sender, content)
        memory.insert_audit_log(project_id, role_id, chat_session_id, sender, "reply", content[:300])
        return {
            "provider": sender,
            "answer": content,
            "chat_session_id": chat_session_id
        }

    # ✅ Handle OpenAI
    if data.provider == "openai":
        answer = ask_openai(messages=[{"role": "user", "content": data.query}], system_prompt=full_prompt) or "[OpenAI Error] Empty response"
        return store_and_return("openai", answer)

    # ✅ Handle Claude
    if data.provider == "anthropic":
        answer = ask_claude(messages=[{"role": "user", "content": data.query}], system=full_prompt) or "[Claude Error] Empty response"
        return store_and_return("anthropic", answer)

    # ✅ Handle BOTH → summary
    if data.provider == "all":
        openai_answer = ask_openai(messages=[{"role": "user", "content": data.query}], system_prompt=full_prompt) or "[OpenAI Error] Empty response"
        claude_answer = ask_claude(messages=[{"role": "user", "content": data.query}], system=full_prompt) or "[Claude Error] Empty response"

        summary_prompt = f"""Please summarize both AI responses in a fair and neutral way.

OpenAI said:
{openai_answer}

Claude said:
{claude_answer}
"""
        summary = ask_openai(
            messages=[{"role": "user", "content": summary_prompt}],
            system_prompt=full_prompt,
        ) or "[Summary Error]"

        memory.store_chat_message(project_id, role_id, chat_session_id, "openai", openai_answer)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "openai", "reply", openai_answer[:300])

        memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_answer)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "reply", claude_answer[:300])

        memory.store_chat_message(project_id, role_id, chat_session_id, "final", summary)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "internal", "summary", summary[:300])

        return {
            "provider": "all",
            "openai": openai_answer,
            "claude": claude_answer,
            "summary": summary,
            "chat_session_id": chat_session_id
        }

    raise HTTPException(status_code=400, detail="Unsupported provider")
