# app/prompts/prompt_builder.py
from __future__ import annotations

from typing import List, Optional, Union, Dict
from sqlalchemy.orm import Session

from app.memory.manager import MemoryManager
from app.memory.utils import get_project_structure

# Try to pull default memory budget from settings; fall back to 600
try:
    from app.config.settings import settings
    _DEFAULT_MEMORY_BUDGET = int(getattr(settings, "MEMORY_SUMMARY_BUDGET_TOKENS", 600))
except Exception:
    _DEFAULT_MEMORY_BUDGET = 600


def _count_tokens(text: str) -> int:
    """
    Lightweight token counter:
    - Uses tiktoken (o200k_base) when available
    - Falls back to a rough heuristic if not
    """
    try:
        import tiktoken  # local import to avoid global hard dependency
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text or ""))
    except Exception:
        s = text or ""
        return max(1, len(s) // 4)  # ~4 chars ≈ 1 token


def _trim_memory(summaries: List[str], token_limit: int) -> List[str]:
    """Keep newest summaries within token budget (assumes input is chronological)."""
    trimmed: List[str] = []
    total = 0
    # newest last: add from the end, then reverse back to chronological
    for summary in reversed(summaries or []):
        tokens = _count_tokens(summary)
        if total + tokens > token_limit:
            break
        trimmed.append(summary)
        total += tokens
    trimmed = list(reversed(trimmed))
    print(f"🧠 Injected {len(trimmed)} memory summaries using {total} tokens")
    return trimmed


def _format_youtube_block(youtube_context: Optional[Union[List[str], List[Dict[str, str]]]]) -> str:
    """
    Accepts either a list of preformatted strings, or a list of dicts:
      { "title": str, "url": str }
    Returns a plain text block (without the section header).
    """
    if not youtube_context:
        return "None."

    # Case 1: already strings → join them
    if youtube_context and isinstance(youtube_context[0], str):
        block = "\n\n".join([s.strip() for s in youtube_context if str(s).strip()])
        return block or "None."

    # Case 2: dicts → render a numbered list "N. <title> — <url>"
    lines: List[str] = []
    for i, item in enumerate(youtube_context, start=1):  # type: ignore[arg-type]
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "Untitled").strip()
        url = (item.get("url") or "").strip()
        if url:
            lines.append(f"{i}. {title} — {url}")
        else:
            lines.append(f"{i}. {title}")
    return "\n".join(lines) if lines else "None."


def _format_web_block(web_context: Optional[Union[List[str], List[Dict[str, str]]]]) -> str:
    """
    Lightweight formatter for web context. Today we expect strings,
    but allow dicts with {title?, url?, snippet?} gracefully.
    """
    if not web_context:
        return "None."

    if web_context and isinstance(web_context[0], str):
        block = "\n\n".join([s.strip() for s in web_context if str(s).strip()])
        return block or "None."

    # Dicts → "• <title or url>\n  <snippet>"
    lines: List[str] = []
    for item in web_context:  # type: ignore[assignment]
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        head = title or url
        if not head and snippet:
            head = snippet.split("\n", 1)[0][:120]
        if head:
            lines.append(f"• {head}")
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines) if lines else "None."


def build_full_prompt(
    system_prompt: str,
    project_structure: str,
    memory_summaries: List[str],
    youtube_context: Union[List[str], List[Dict[str, str]], None],
    web_context: Union[List[str], List[Dict[str, str]], None],
    starter_reply: str,
    user_input: str,
    max_memory_tokens: int = _DEFAULT_MEMORY_BUDGET,
    db: Optional[Session] = None,
    *,
    canonical_context: Optional[str] = None,
) -> str:
    """
    Assemble the final system prompt. Uses a local token counter to trim memory
    so we avoid creating a MemoryManager with db=None just to count tokens.
    """

    # Trim blocks
    memory_block = "\n\n".join(_trim_memory(memory_summaries, max_memory_tokens))
    youtube_block = _format_youtube_block(youtube_context)
    web_block = _format_web_block(web_context)

    # Normalize inputs
    system_prompt = (system_prompt or "").strip() or "You are a helpful assistant."
    project_structure = (project_structure or "").strip() or "No project structure provided."
    memory_block = (memory_block or "No prior memory.").strip()
    youtube_block = (youtube_block or "None.").strip()
    web_block = (web_block or "None.").strip()
    starter_reply = (starter_reply or "No previous reply.").strip()
    user_input = (user_input or "[No question provided]").strip()
    canonical_context = (canonical_context or "").strip()

    # Canon handling
    canon_rule = (
        "Canonical rule: If anything in chat history, web results, YouTube results, or your assumptions "
        "conflicts with the Canonical Context, treat the Canonical Context as source of truth. Prefer canon over speculation."
    ) if canonical_context else ""
    canon_rule_line = f"\n{canon_rule}" if canon_rule else ""
    if canonical_context:
        if canonical_context.lstrip().startswith("#"):
            canon_section = f"\n\n{canonical_context}"
        else:
            canon_section = f"\n\n### 📚 Canonical Context\n{canonical_context}"
    else:
        canon_section = ""

    # Debug logs
    print("📌 SYSTEM PROMPT:", system_prompt[:200])
    print("📌 PROJECT STRUCTURE:", project_structure[:200])
    if canonical_context:
        print("📌 CANONICAL CONTEXT:", canonical_context[:200])
    print("📌 MEMORY:", memory_block[:200])
    print("📌 YOUTUBE:", youtube_block[:200])
    print("📌 WEB:", web_block[:200])
    print("📌 STARTER:", starter_reply[:200])
    print("📌 INPUT:", user_input[:200])

    # Assemble final prompt
    prompt = f"""
{system_prompt}{canon_rule_line}

### 🗂️ Project Structure
{project_structure}{canon_section}

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

    print(f"📄 Final prompt token count: {_count_tokens(prompt)}")
    return prompt


def generate_prompt_from_db(
    db: Session,
    project_id: Optional[Union[int, str]],
    role_id: int,
    system_prompt: str,
    youtube_context: Union[List[str], List[Dict[str, str]], None],
    web_context: Union[List[str], List[Dict[str, str]], None],
    starter_reply: str,
    user_input: str,
    max_memory_tokens: int = _DEFAULT_MEMORY_BUDGET,
    *,
    canonical_context: Optional[str] = None,
) -> str:
    """
    Pull summaries + project structure, then delegate to build_full_prompt.
    Ensures string project_id for MemoryManager, int conversion for structure.
    """
    memory = MemoryManager(db)

    # Always pass project_id as string to MemoryManager
    project_id_str = "0" if project_id in (None, "", "default") else str(project_id)

    summaries = memory.load_recent_summaries(
        project_id=project_id_str,
        role_id=role_id,
        limit=10,
    )

    # Gracefully fetch project structure (expects an int id)
    if project_id in (None, "", "default"):
        project_structure = ""
    else:
        try:
            project_structure = get_project_structure(db, int(project_id))  # may raise ValueError/TypeError
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
        max_memory_tokens=max_memory_tokens,
        db=db,
        canonical_context=canonical_context,  # no-op if None
    )
