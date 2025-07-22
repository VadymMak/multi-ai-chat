from typing import List, Optional, Union
from sqlalchemy.orm import Session

from app.memory.manager import MemoryManager
from app.memory.utils import get_project_structure


def build_full_prompt(
    system_prompt: str,
    project_structure: str,
    memory_summaries: list[str],
    youtube_context: list[str],
    web_context: list[str],
    starter_reply: str,
    user_input: str,
    max_memory_tokens: int = 600
) -> str:
    memory = MemoryManager(db=None)  # Only used for token counting

    def trim_memory(summaries: list[str], token_limit: int) -> list[str]:
        trimmed = []
        total = 0
        for summary in reversed(summaries):
            tokens = memory.count_tokens(summary)
            if total + tokens > token_limit:
                break
            trimmed.append(summary)
            total += tokens
        print(f"🧠 Injected {len(trimmed)} memory summaries using {total} tokens")
        return list(reversed(trimmed))

    # Trim memory summaries
    memory_block = "\n\n".join(trim_memory(memory_summaries, max_memory_tokens))
    youtube_block = "\n\n".join(youtube_context)
    web_block = "\n\n".join(web_context)

    # Normalize inputs
    system_prompt = system_prompt.strip() or "You are a helpful assistant."
    project_structure = project_structure.strip() or "No project structure provided."
    memory_block = memory_block or "No prior memory."
    youtube_block = youtube_block or "None."
    web_block = web_block or "None."
    starter_reply = starter_reply.strip() or "No previous reply."
    user_input = user_input.strip() or "[No question provided]"

    # Debug logging
    print("📌 SYSTEM PROMPT:", system_prompt[:200])
    print("📌 PROJECT STRUCTURE:", project_structure[:200])
    print("📌 MEMORY:", memory_block[:200])
    print("📌 YOUTUBE:", youtube_block[:200])
    print("📌 WEB:", web_block[:200])
    print("📌 STARTER:", starter_reply[:200])
    print("📌 INPUT:", user_input[:200])

    # Assemble final prompt
    prompt = f"""
{system_prompt}

### 🗂️ Project Structure
{project_structure}

### 🧠 Memory Context
{memory_block}

### 📺 YouTube Results
{youtube_block}

### 🌐 Web Search Results
{web_block}

### 💬 Previous AI Reply
{starter_reply}

### 📝 Your Question
{user_input}
    """.strip()

    print(f"📄 Final prompt token count: {memory.count_tokens(prompt)}")
    return prompt


def generate_prompt_from_db(
    db: Session,
    project_id: Optional[Union[int, str]],
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

    # Gracefully fetch project structure
    if not project_id or project_id == "default":
        project_structure = ""
    else:
        try:
            project_structure = get_project_structure(db, int(project_id))
        except (ValueError, TypeError):
            print("⚠️ Invalid project_id passed to get_project_structure:", project_id)
            project_structure = ""

    return build_full_prompt(
        system_prompt=system_prompt,
        project_structure=project_structure,
        memory_summaries=summaries,
        youtube_context=youtube_context,
        web_context=web_context,
        starter_reply=starter_reply,
        user_input=user_input,
        max_memory_tokens=max_memory_tokens
    )
