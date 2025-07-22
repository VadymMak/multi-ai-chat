# app/routers/ask_ai_to_ai_turn.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import List, Optional, Union, Literal, Dict, Any
from sqlalchemy.orm import Session
from uuid import uuid4
import asyncio

from starlette.concurrency import run_in_threadpool

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.config.settings import settings
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude

router = APIRouter(tags=["Chat"])

HISTORY_MAX_TOKENS = getattr(settings, "HISTORY_MAX_TOKENS", 1800)
HISTORY_FETCH_LIMIT = getattr(settings, "HISTORY_FETCH_LIMIT", 200)


class AiToAiTurnRequest(BaseModel):
    topic: str
    role_id: int
    project_id: Union[int, str]
    chat_session_id: Optional[str] = None
    starter: Literal["openai", "anthropic"] = "openai"

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v):
        return "0" if v in (None, "", "default") else str(v).strip()


async def _ask_openai_async(messages: List[Dict[str, str]]) -> str:
    return await run_in_threadpool(ask_openai, messages)


async def _ask_claude_with_retry(messages: List[Dict[str, str]], retries: int = 2) -> str:
    last = ""
    for attempt in range(retries + 1):
        try:
            ans = await run_in_threadpool(ask_claude, messages)
            last = ans or ""
            if ans and "[Claude Error]" not in ans and "overloaded" not in ans.lower():
                return ans
        except Exception as e:
            last = f"[Claude Exception] {e}"
        await asyncio.sleep(1.5 + attempt)
    return last or "[Claude Retry Failed]"


def _rows_to_messages(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Map DB rows → OpenAI/Claude message format, keeping only user/assistant."""
    out: List[Dict[str, str]] = []
    for r in rows:
        sender = (r.get("sender") or "").strip().lower()
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if sender == "user":
            out.append({"role": "user", "content": text})
        elif sender in {"openai", "anthropic", "assistant", "final"}:
            out.append({"role": "assistant", "content": text})
    return out


def _clip_by_tokens(mm: MemoryManager, msgs: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    """Keep newest turns within token budget by dropping from the front."""
    if not msgs:
        return msgs
    total = 0
    kept_rev: List[Dict[str, str]] = []
    for m in reversed(msgs):
        total += mm.count_tokens(m.get("content") or "")
        if total > max_tokens:
            break
        kept_rev.append(m)
    return list(reversed(kept_rev))


@router.post("/ask-ai-to-ai-turn")
async def ask_ai_to_ai_turn_route(data: AiToAiTurnRequest, db: Session = Depends(get_db)):
    """
    Lightweight 'turn' flow:
      1) Starter model answers the topic (with trimmed history as context).
      2) Claude answers the same topic (second opinion).
      3) Claude merges both into a refined general response.
      4) Everything is persisted + a long-term summary is saved.
    """
    try:
        memory = MemoryManager(db)
        role_id = int(data.role_id)
        project_id = str(data.project_id)

        # Stable session reuse (or mint)
        chat_session_id = data.chat_session_id or memory.get_or_create_chat_session_id(role_id, project_id)

        # Fetch & trim history
        rows = memory.retrieve_messages(
            project_id=project_id,
            role_id=role_id,
            chat_session_id=chat_session_id,
            limit=HISTORY_FETCH_LIMIT,
        )
        hist = _rows_to_messages(rows)
        hist = _clip_by_tokens(memory, hist, HISTORY_MAX_TOKENS)

        # Compose and store the user turn
        user_turn = {"role": "user", "content": data.topic}
        memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.topic, is_ai_to_ai=True)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "internal", "ai2ai_turn_start", data.topic[:300])

        # 1) Starter reply
        starter_messages = hist + [user_turn]
        if data.starter == "openai":
            starter_reply = await _ask_openai_async(starter_messages)
            starter_sender = "openai"
        else:
            starter_reply = await _ask_claude_with_retry(starter_messages)
            starter_sender = "anthropic"

        memory.store_chat_message(project_id, role_id, chat_session_id, starter_sender, starter_reply, is_ai_to_ai=True)
        memory.insert_audit_log(project_id, role_id, chat_session_id, starter_sender, "ai2ai_turn_reply", starter_reply[:300])

        # 2) Claude second opinion
        claude_reply = await _ask_claude_with_retry(starter_messages)
        memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_reply, is_ai_to_ai=True)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "ai2ai_turn_second", claude_reply[:300])

        # 3) Merged/general reply (robust if starter failed)
        starter_ok = bool(starter_reply and not starter_reply.startswith("[OpenAI Error]") and "overloaded" not in starter_reply.lower())
        if starter_ok:
            merged_prompt_text = (
                f"OpenAI/Starter replied:\n\n{starter_reply}\n\n"
                f"Claude replied:\n\n{claude_reply}\n\n"
                "Provide a refined, general response that combines the best parts of both answers. "
                "Be concise and actionable."
            )
        else:
            merged_prompt_text = (
                "The starter model returned an error or empty output.\n"
                f"Claude's standalone answer:\n\n{claude_reply}\n\n"
                "Provide a concise, actionable final answer to the user's topic using the best of the above."
            )

        merged = await _ask_claude_with_retry(
            hist
            + [user_turn, {"role": "assistant", "content": starter_reply}, {"role": "assistant", "content": claude_reply}]
            + [{"role": "user", "content": merged_prompt_text}]
        )
        memory.store_chat_message(project_id, role_id, chat_session_id, "final", merged, is_ai_to_ai=True)
        memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "ai2ai_turn_merged", merged[:300])

        # 4) Persist long-term summary
        try:
            transcript = (
                hist
                + [user_turn, {"role": "assistant", "content": starter_reply}]
                + [{"role": "assistant", "content": claude_reply}]
                + [{"role": "assistant", "content": merged}]
            )
            raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in transcript])
            summary = memory.summarize_messages([raw_text])
            memory.store_memory(project_id, role_id, summary, raw_text, chat_session_id, is_ai_to_ai=True)
        except Exception as e:
            print(f"[AI-to-AI turn: summary error] {e}")

        return {
            "chat_session_id": chat_session_id,
            "starter": starter_sender,
            "starter_reply": starter_reply,
            "claude_reply": claude_reply,
            "merged": merged,
        }

    except Exception as e:
        print(f"❌ Error in /ask-ai-to-ai-turn: {e}")
        raise HTTPException(status_code=500, detail="AI-to-AI turn failed")
