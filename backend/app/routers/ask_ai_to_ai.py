from fastapi import APIRouter
from pydantic import BaseModel, validator
from typing import Literal, Optional, Union
import asyncio
from uuid import uuid4

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
    def convert_role(cls, v):
        try:
            return int(v)
        except Exception:
            raise ValueError("role must be an integer")


async def claude_with_retry(messages: list[dict], retries: int = 2) -> str:
    for attempt in range(retries + 1):
        ans = ask_claude(messages)
        if ans and "[Claude Error]" not in ans and "overloaded" not in ans.lower():
            return ans
        await asyncio.sleep(1.5 + attempt)
    return ans or "[Claude Retry Failed]"


@router.post("/ask-ai-to-ai")
async def ask_ai_to_ai_route(data: AiToAiRequest):
    db = next(get_db())
    memory = MemoryManager(db)
    role_id = data.role
    project_id = data.project_id
    chat_session_id = data.chat_session_id or memory.get_or_create_chat_session_id(role_id, project_id)

    print(f"⚙️ Boost Mode: topic='{data.topic}' | starter={data.starter} | role={role_id} | project_id={project_id} | session={chat_session_id}")

    # 🔍 Context Gathering
    try:
        yt_block, yt_hits = perform_youtube_search(data.topic, memory, role_id, project_id)
    except Exception as e:
        yt_block, yt_hits = "[YouTube context unavailable]", []
        print(f"[YouTube Error] {e}")

    try:
        web_hits = perform_web_search(data.topic)
    except Exception as e:
        web_hits = []
        print(f"[Web Search Error] {e}")

    # 🧠 Store initial user message
    user_message = f"{data.topic}\n\n{yt_block}"
    memory.store_chat_message(project_id, role_id, chat_session_id, "user", user_message, is_ai_to_ai=True)

    # 🔁 Initial Assistant Reply
    conversation = [{"role": "user", "content": user_message}]
    if data.starter == "openai":
        first_reply = ask_openai(conversation)
    else:
        first_reply = await claude_with_retry(conversation)

    conversation.append({"role": "assistant", "content": first_reply})
    memory.store_chat_message(project_id, role_id, chat_session_id, data.starter, first_reply, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, data.starter, "boost_reply", first_reply[:300])

    # 🤖 Claude Review
    review_prompt = f"""Here is the assistant's reply to the topic "{data.topic}":

{first_reply}

Please review and reflect on this reply. Highlight what’s good, what could be improved, and what additional context might help the user. Be objective and constructive."""
    claude_review = await claude_with_retry([{"role": "user", "content": review_prompt}])
    conversation.append({"role": "assistant", "content": claude_review})
    memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_review, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "boost_review", claude_review[:300])

    # 🧠 Build Final Prompt
    memory_summaries = memory.load_recent_summaries(role_id=role_id, project_id=project_id, limit=5)
    youtube_context = [f"{v['title']} - {v['url']}" for v in yt_hits]
    web_context = [f"{v['title']} - {v['snippet']}" for v in web_hits]
    project = db.query(Project).filter_by(id=project_id).first()
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

    # 🧠 Final Claude Summary
    final_reply = await claude_with_retry([{"role": "user", "content": full_prompt}])
    conversation.append({"role": "assistant", "content": final_reply})
    memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_reply, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "boost_summary", final_reply[:300])

    # 💾 Summarize and Store Final Memory
    raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in conversation])
    summary = memory.summarize_messages([raw_text])
    memory.store_memory(project_id, role_id, summary, raw_text, chat_session_id, is_ai_to_ai=True)

    print("✅ Boost Mode completed.")

    return {
        "messages": [
            {"sender": data.starter, "answer": first_reply},
            {"sender": "anthropic", "answer": claude_review}
        ],
        "summary": final_reply,
        "youtube": yt_hits,
        "web": web_hits,
        "chat_session_id": chat_session_id
    }
