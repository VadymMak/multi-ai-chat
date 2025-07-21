# backend/app/routers/ask.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager
from app.memory.db import get_db

router = APIRouter()

class AskRequest(BaseModel):
    query: str
    provider: Literal["openai", "anthropic", "all"]
    role_id: str

@router.post("/ask")
async def ask_route(data: AskRequest, db: Session = Depends(get_db)):
    memory = MemoryManager(db)
    history = memory.retrieve_messages(data.role_id, limit=6)
    user_input = {"role": "user", "content": data.query}

    if data.provider == "openai":
        answer = ask_openai(history + [user_input])
        raw_text = f"User: {data.query}\nOpenAI: {answer}"
        summary = memory.summarize_messages([raw_text])
        memory.store_memory(data.role_id, summary, raw_text)
        return {"provider": "openai", "answer": answer}

    elif data.provider == "anthropic":
        answer = ask_claude(history + [user_input])
        raw_text = f"User: {data.query}\nAnthropic: {answer}"
        summary = memory.summarize_messages([raw_text])
        memory.store_memory(data.role_id, summary, raw_text)
        return {"provider": "anthropic", "answer": answer}

    elif data.provider == "all":
        openai_answer = ask_openai(history + [user_input])
        claude_answer = ask_claude(history + [user_input])

        summary_prompt = f"""Please summarize both AI responses in a fair and neutral way.

OpenAI said:
{openai_answer}

Claude said:
{claude_answer}
"""
        summary = ask_openai([{"role": "user", "content": summary_prompt}])
        raw_text = (
            f"User: {data.query}\n"
            f"OpenAI: {openai_answer}\n"
            f"Anthropic: {claude_answer}\n"
            f"Final: {summary}"
        )
        mem_summary = memory.summarize_messages([raw_text])
        memory.store_memory(data.role_id, mem_summary, raw_text)

        return {
            "provider": "all",
            "openai": openai_answer,
            "claude": claude_answer,
            "summary": summary
        }

    raise HTTPException(status_code=400, detail="Unsupported provider")
