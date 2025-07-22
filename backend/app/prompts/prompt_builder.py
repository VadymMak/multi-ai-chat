# app/prompts/prompt_builder.py
from __future__ import annotations

from typing import List, Optional, Union, Dict, Tuple, Any
from sqlalchemy.orm import Session

from app.memory.manager import MemoryManager
from app.memory.utils import get_project_structure

# Settings (with safe fallbacks)
try:
    from app.config.settings import settings
    _DEFAULT_MEMORY_BUDGET = int(getattr(settings, "MEMORY_SUMMARY_BUDGET_TOKENS", 600))
    _CANON_ENABLED = bool(getattr(settings, "ENABLE_CANON", False))
    _CANON_TOPK = int(getattr(settings, "CANON_TOPK", 6))
except Exception:
    _DEFAULT_MEMORY_BUDGET = 600
    _CANON_ENABLED = False
    _CANON_TOPK = 6


def _count_tokens(text: str) -> int:
    """
    Lightweight token counter:
    - Uses tiktoken (o200k_base, then cl100k_base) when available
    - Falls back to a rough heuristic if not
    """
    try:
        import tiktoken  # local import to avoid hard dep at import-time
        try:
            enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or ""))
    except Exception:
        s = text or ""
        return max(1, len(s) // 4)  # ~4 chars ≈ 1 token


def _trim_memory(summaries: List[str], token_limit: int) -> List[str]:
    """
    Keep newest summaries within the token budget.
    Assumes input is newest-first (matches load_recent_summaries DESC).
    """
    kept: List[str] = []
    total = 0
    for s in summaries or []:
        t = _count_tokens(s)
        if total + t > token_limit:
            break
        kept.append(s)
        total += t
    print(f"🧠 Injected {len(kept)} memory summaries using {total} tokens (budget={token_limit})")
    return kept


def _format_youtube_block(youtube_context: Optional[Union[List[str], List[Dict[str, str]]]]) -> str:
    """
    Accepts either a list of preformatted strings, or a list of dicts:
      { "title": str, "url": str }
    Returns a plain text block (without the section header).
    """
    if not youtube_context:
        return "None."

    # already formatted strings
    if isinstance(youtube_context[0], str):  # type: ignore[index]
        block = "\n\n".join([str(s).strip() for s in youtube_context if str(s).strip()])
        return block or "None."

    # dicts → numbered lines "N. <title> — <url>"
    lines: List[str] = []
    for i, item in enumerate(youtube_context, start=1):  # type: ignore[arg-type]
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "Untitled").strip()
        url = (item.get("url") or "").strip()
        lines.append(f"{i}. {title}" + (f" — {url}" if url else ""))
    return "\n".join(lines) if lines else "None."


def _format_web_block(web_context: Optional[Union[List[str], List[Dict[str, str]]]]) -> str:
    """
    Lightweight formatter for web context. Accepts:
    - list[str]
    - list[dict{title?, url?, snippet?}]
    """
    if not web_context:
        return "None."

    if isinstance(web_context[0], str):  # type: ignore[index]
        block = "\n\n".join([str(s).strip() for s in web_context if str(s).strip()])
        return block or "None."

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


def _maybe_fetch_canon_digest(
    memory: MemoryManager,
    *,
    project_id: str,
    role_id: int,
    user_input: str,
    top_k: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Best-effort Canon digest retrieval. If disabled or unsupported, returns ("", []).
    """
    if not _CANON_ENABLED:
        return "", []
    if not hasattr(memory, "retrieve_context_digest"):
        return "", []
    try:
        # Simple term extraction: keep unique words ≥4 chars
        words: List[str] = []
        for w in (user_input or "").split():
            w = "".join(ch for ch in w if ch.isalnum() or ch in "-_")
            if len(w) >= 4:
                words.append(w.lower())
        terms = sorted(set(words))[:8] or None
        digest, items = memory.retrieve_context_digest(
            project_id=project_id,
            role_id=role_id,
            query_terms=terms,
            top_k=top_k,
        )
        return (digest or "").strip(), (items or [])
    except Exception as e:
        print(f"[Canon digest error] {e}")
        return "", []


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
    so we avoid creating a MemoryManager just to count tokens.
    """
    # Trim/inflate blocks
    trimmed_mem = _trim_memory(memory_summaries or [], max_memory_tokens)
    memory_block = "\n\n".join(trimmed_mem) if trimmed_mem else "No prior memory."
    youtube_block = _format_youtube_block(youtube_context)
    web_block = _format_web_block(web_context)

    # Normalize inputs
    system_prompt = (system_prompt or "").strip() or "You are a helpful assistant."
    project_structure = (project_structure or "").strip() or "No project structure provided."
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
        canon_section = f"\n\n{canonical_context}" if canonical_context.lstrip().startswith("#") \
            else f"\n\n### 📚 Canonical Context\n{canonical_context}"
    else:
        canon_section = ""

    # Debug (trimmed)
    print("📌 SYSTEM PROMPT:", system_prompt[:200])
    print("📌 PROJECT STRUCTURE:", project_structure[:200])
    if canonical_context:
        print("📌 CANONICAL CONTEXT:", canonical_context[:200])
    print("📌 MEMORY:", memory_block[:200])
    print("📌 YOUTUBE:", youtube_block[:200])
    print("📌 WEB:", web_block[:200])
    print("📌 STARTER:", starter_reply[:200])
    print("📌 INPUT:", user_input[:200])

    # Final assembly
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
    Pull summaries + project structure (and optionally Canon), then delegate to build_full_prompt.
    Ensures string project_id for MemoryManager, int conversion for structure.
    """
    memory = MemoryManager(db)

    # MemoryManager expects project_id as string
    project_id_str = "0" if project_id in (None, "", "default") else str(project_id)

    summaries = memory.load_recent_summaries(
        project_id=project_id_str,
        role_id=role_id,
        limit=10,
    )

    # Auto-include Canon if enabled and not explicitly provided
    if not canonical_context and _CANON_ENABLED:
        canon_digest, _canon_items = _maybe_fetch_canon_digest(
            memory,
            project_id=project_id_str,
            role_id=role_id,
            user_input=user_input,
            top_k=_CANON_TOPK,
        )
        canonical_context = canon_digest or None

    # Project structure requires int id; be lenient
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
        canonical_context=canonical_context,
    )


__all__ = ["build_full_prompt", "generate_prompt_from_db"]
