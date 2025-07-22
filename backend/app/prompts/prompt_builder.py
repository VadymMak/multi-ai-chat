from typing import List, Dict
from sqlalchemy.orm import Session
from app.memory.manager import MemoryManager
from app.memory.models import Role
from app.memory.manager import count_tokens

def build_full_prompt(
    system_prompt: str,
    memory_summaries: list[str],
    youtube_context: list[str],
    web_context: list[str],
    starter_reply: str,
    user_input: str,
    max_memory_tokens: int = 600
) -> str:
    def trim_memory(summaries: list[str], token_limit: int) -> list[str]:
        trimmed = []
        total = 0
        for summary in reversed(summaries):
            tokens = count_tokens(summary)
            if total + tokens > token_limit:
                break
            trimmed.append(summary)
            total += tokens
        print(f"🧠 Injected {len(trimmed)} memory summaries using {total} tokens")
        return list(reversed(trimmed))

    memory_block = "\n\n".join(trim_memory(memory_summaries, max_memory_tokens))
    youtube_block = "\n\n".join(youtube_context)
    web_block = "\n\n".join(web_context)

    prompt = f"""
{system_prompt.strip()}

### 🧠 Memory Context
{memory_block or "No prior memory."}

### 📺 YouTube Results
{youtube_block or "None."}

### 🌐 Web Search Results
{web_block or "None."}

### 💬 Previous AI Reply
{starter_reply.strip() or "No previous reply."}

### 📝 Your Question
{user_input.strip()}
    """.strip()

    print(f"📄 Final prompt token count: {count_tokens(prompt)}")
    return prompt


def generate_prompt_from_db(
    db: Session,
    project_id: str,
    role_id: int,
    system_prompt: str,
    youtube_context: List[str],
    web_context: List[str],
    starter_reply: str,
    user_input: str,
    max_memory_tokens: int = 600,
) -> str:
    memory = MemoryManager(db)
    summaries = memory.load_recent_summaries(project_id=project_id, role_id=role_id, limit=10)

    return build_full_prompt(
        system_prompt=system_prompt,
        memory_summaries=summaries,
        youtube_context=youtube_context,
        web_context=web_context,
        starter_reply=starter_reply,
        user_input=user_input,
        max_memory_tokens=max_memory_tokens
    )
