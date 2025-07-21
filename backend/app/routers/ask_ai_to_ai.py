# app/routers/ask_ai_to_ai.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Literal
import asyncio

from app.memory.db import get_db

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager

router = APIRouter()

class AiToAiRequest(BaseModel):
    topic: str
    starter: Literal["openai", "anthropic"]
    role_id: int

async def claude_with_retry(messages: list[dict], retries: int = 2) -> str:
    for attempt in range(retries + 1):
        ans = ask_claude(messages)
        if "[Claude Error]" not in ans or "overloaded" not in ans.lower():
            return ans
        await asyncio.sleep(1.5 + attempt)
    return ans

@router.post("/ask-ai-to-ai")
async def ask_ai_to_ai_route(data: AiToAiRequest):
    db_session = next(get_db())
    memory = MemoryManager(db=db_session)

    # First response by OpenAI (or Claude)
    initial_provider = data.starter
    other_provider = "anthropic" if data.starter == "openai" else "openai"

    conversation = [{"role": "user", "content": f"Topic: {data.topic}"}]

    if initial_provider == "openai":
        first_reply = ask_openai(conversation)
    else:
        first_reply = await claude_with_retry(conversation)

    conversation.append({"role": "assistant", "content": first_reply})

    # Second provider sees the previous reply and responds
    if other_provider == "anthropic":
        final_reply = await claude_with_retry(conversation)
    else:
        final_reply = ask_openai(conversation)

    conversation.append({"role": "assistant", "content": final_reply})

    # Save to memory
    raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    memory.store_memory(
        data.role_id,
        memory.summarize_messages([raw_text]),
        raw_text,
    )

    return {
        "starter": data.starter,
        "conversation": conversation,
        "final_summary": final_reply
    }
