from fastapi import APIRouter
from pydantic import BaseModel, validator
from typing import Literal, Optional, List, Union
import asyncio

from app.memory.db import get_db
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.memory.manager import MemoryManager
from app.memory.models import Project
from app.services.youtube_sevice import perform_youtube_search
from app.services.web_search_service import perform_web_search
from app.prompts.prompt_builder import build_full_prompt

router = APIRouter()


class AiToAiRequest(BaseModel):
    topic: str
    starter: Literal["openai", "anthropic"]
    role: Union[int, str]
    project_id: str
    chat_session_id: Optional[str] = None

    @validator("role", pre=True)
    def convert_role_to_int(cls, v):
        try:
            return int(v)
        except Exception:
            raise ValueError("role must be an integer")


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

    print(f"⚙️ Boost Mode: topic='{data.topic}' | starter={data.starter} | role_id={data.role} | project_id={data.project_id}")

    # 🔍 YouTube & Web Context
    try:
        yt_block, yt_hits = perform_youtube_search(
            data.topic,
            memory,
            data.role,
            data.project_id
        )
    except Exception as e:
        yt_block = "[YouTube search unavailable]"
        yt_hits = []
        print(f"[YouTube Error] {e}")

    try:
        web_hits = perform_web_search(data.topic)
    except Exception as e:
        web_hits = []
        print(f"[Web Search Error] {e}")

    # 🔁 Initial assistant reply
    conversation = [{"role": "user", "content": f"Topic: {data.topic}\n\n{yt_block}"}]

    if data.starter == "openai":
        first_reply = ask_openai(conversation)
    else:
        first_reply = await claude_with_retry(conversation)

    conversation.append({"role": "assistant", "content": first_reply})

    memory.insert_audit_log(
        project_id=data.project_id,
        role_id=data.role,
        chat_session_id=data.chat_session_id,
        provider=data.starter,
        action="boost_reply",
        query=first_reply[:300]
    )

    # 🤖 Claude review of the initial reply
    review_prompt = f"""Here is the assistant's reply to the topic "{data.topic}":

{first_reply}

Please review and reflect on this reply. Highlight what’s good, what could be improved, and what additional context might help the user. Be objective and constructive."""
    claude_review = await claude_with_retry([{"role": "user", "content": review_prompt}])
    conversation.append({"role": "assistant", "content": claude_review})

    memory.insert_audit_log(
        project_id=data.project_id,
        role_id=data.role,
        chat_session_id=data.chat_session_id,
        provider="anthropic",
        action="boost_review",
        query=claude_review[:300]
    )

    # 🧠 Memory summaries and project structure
    memory_summaries = memory.load_recent_summaries(
        role_id=data.role,
        project_id=data.project_id,
        limit=5
    )

    youtube_context = [f"{v['title']} - {v['url']}" for v in yt_hits]
    web_context = [f"{v['title']} - {v['snippet']}" for v in web_hits]

    project = db_session.query(Project).filter_by(id=data.project_id).first()
    project_structure = project.project_structure if project else ""

    full_prompt = build_full_prompt(
        system_prompt="You are a thoughtful assistant summarizing and enhancing user research.",
        memory_summaries=memory_summaries,
        youtube_context=youtube_context,
        web_context=web_context,
        starter_reply=first_reply,
        user_input=data.topic,
        project_structure=project_structure
    )

    final_reply = await claude_with_retry([{"role": "user", "content": full_prompt}])
    conversation.append({"role": "assistant", "content": final_reply})

    memory.insert_audit_log(
        project_id=data.project_id,
        role_id=data.role,
        chat_session_id=data.chat_session_id,
        provider="anthropic",
        action="boost_summary",
        query=final_reply[:300]
    )

    # 💾 Store final memory with summary
    raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    summary = memory.summarize_messages([raw_text])

    memory.store_memory(
        project_id=data.project_id,
        role_id=data.role,
        chat_session_id=data.chat_session_id,
        summary=summary,
        raw_text=raw_text
    )

    print("✅ Boost Mode completed and audit logged.")

    return {
        "messages": [
            {"sender": data.starter, "answer": first_reply},
            {"sender": "anthropic", "answer": claude_review}
        ],
        "summary": final_reply,
        "youtube": yt_hits,
        "web": web_hits
    }
