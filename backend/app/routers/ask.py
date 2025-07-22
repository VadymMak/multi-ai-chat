from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Literal, Union
from sqlalchemy.orm import Session

from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager
from app.memory.db import get_db

router = APIRouter()

class AskRequest(BaseModel):
    query: str
    provider: Literal["openai", "anthropic", "all"]
    role_id: int
    project_id: Union[int, str]

@router.post("/ask")
async def ask_route(data: AskRequest, db: Session = Depends(get_db)):
    memory = MemoryManager(db)
    role_id = data.role_id
    project_id = str(data.project_id)

    history = memory.retrieve_messages(project_id=project_id, role_id=role_id, limit=6)
    user_input = {"role": "user", "content": data.query}

    summaries = memory.load_recent_summaries(project_id=project_id, role_id=role_id, limit=5)
    system_prompt = (
        "You are an assistant helping with project memory.\n\n"
        "Here are recent memory summaries to inform your response:\n"
        + "\n".join(f"- {s}" for s in summaries)
    )

    if data.provider == "openai":
        answer = ask_openai(
            messages=history + [user_input],
            system_prompt=system_prompt,
        ) or "[OpenAI Error] Empty response"

        raw_text = f"User: {data.query}\nOpenAI: {answer}"
        summary = memory.summarize_messages([raw_text]) or raw_text[:400]
        memory.store_memory(project_id=project_id, role_id=role_id, summary=summary, raw_text=raw_text)

        return {"provider": "openai", "answer": answer}

    elif data.provider == "anthropic":
        answer = ask_claude(
            messages=history + [user_input],
            system=system_prompt,  # ✅ Corrected here
        ) or "[Claude Error] Empty response"

        raw_text = f"User: {data.query}\nAnthropic: {answer}"
        summary = memory.summarize_messages([raw_text]) or raw_text[:400]
        memory.store_memory(project_id=project_id, role_id=role_id, summary=summary, raw_text=raw_text)

        return {"provider": "anthropic", "answer": answer}

    elif data.provider == "all":
        openai_answer = ask_openai(
            messages=history + [user_input],
            system_prompt=system_prompt,
        ) or "[OpenAI Error] Empty response"

        claude_answer = ask_claude(
            messages=history + [user_input],
            system=system_prompt,  # ✅ Corrected here
        ) or "[Claude Error] Empty response"

        summary_prompt = f"""Please summarize both AI responses in a fair and neutral way.

OpenAI said:
{openai_answer}

Claude said:
{claude_answer}
"""

        summary = ask_openai(
            messages=[{"role": "user", "content": summary_prompt}],
            system_prompt=system_prompt,
        ) or "[Summary Error]"

        raw_text = (
            f"User: {data.query}\n"
            f"OpenAI: {openai_answer}\n"
            f"Anthropic: {claude_answer}\n"
            f"Final: {summary}"
        )
        mem_summary = memory.summarize_messages([raw_text]) or raw_text[:500]
        memory.store_memory(project_id=project_id, role_id=role_id, summary=mem_summary, raw_text=raw_text)

        return {
            "provider": "all",
            "openai": openai_answer,
            "claude": claude_answer,
            "summary": summary,
        }

    raise HTTPException(status_code=400, detail="Unsupported provider")
