# File: app/routers/ask_ai_to_ai.py

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
    role: str  # ✅ changed from role_id (to align with frontend)

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

    conversation = [{"role": "user", "content": f"Topic: {data.topic}"}]

    # First provider replies
    if data.starter == "openai":
        first_reply = ask_openai(conversation)
        other_provider = "anthropic"
    else:
        first_reply = await claude_with_retry(conversation)
        other_provider = "openai"

    conversation.append({"role": "assistant", "content": first_reply})

    # Second provider replies after seeing the first
    if other_provider == "anthropic":
        final_reply = await claude_with_retry(conversation)
    else:
        final_reply = ask_openai(conversation)

    conversation.append({"role": "assistant", "content": final_reply})

    # Save to memory with role
    raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    summary = memory.summarize_messages([raw_text])
    memory.store_memory(data.role, summary, raw_text)

    # 🧠 Split AI messages and final summary as expected by frontend
    return {
        "messages": [
            {"sender": data.starter, "answer": first_reply},
            {"sender": other_provider, "answer": final_reply}
        ],
        "summary": final_reply
    }

