from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
import asyncio

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager
from app.memory.db import get_db
from sqlalchemy.orm import Session

router = APIRouter()

class AiToAiRequest(BaseModel):
    topic: str
    role_id: str

async def claude_with_retry(messages: List[dict], retries: int = 2) -> str:
    for attempt in range(retries + 1):
        answer = ask_claude(messages)
        if "[Claude Error]" not in answer and "overloaded" not in answer.lower():
            return answer
        await asyncio.sleep(1.5 + attempt)
    return answer

@router.post("/ask-ai-to-ai-turn")
async def ask_ai_to_ai_turn_route(data: AiToAiRequest, db: Session = Depends(get_db)):
    memory = MemoryManager(db)
    history = memory.retrieve_messages(data.role_id)
    first_query = [{"role": "user", "content": data.topic}]
    conversation = history + first_query

    # Step 1: OpenAI reply
    openai_answer = ask_openai(conversation)
    conversation.append({"role": "assistant", "content": openai_answer})

    # Step 2: Claude reply
    claude_answer = await claude_with_retry(history + first_query)
    conversation.append({"role": "assistant", "content": claude_answer})

    # Step 3: Claude general reply
    general_prompt = {
        "role": "user",
        "content": (
            f"OpenAI replied:\n\n{openai_answer}\n\n"
            f"Claude replied:\n\n{claude_answer}\n\n"
            "Please provide a refined, general response combining insights from both."
        )
    }
    conversation.append(general_prompt)
    general_answer = await claude_with_retry(conversation)

    # Store conversation
    raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    summary = memory.summarize_messages([raw_text])
    memory.store_memory(data.role_id, summary, raw_text)

    return {
        "openai_answer": openai_answer,
        "claude_answer": claude_answer,
        "general_answer": general_answer,
        "summary": summary
    }