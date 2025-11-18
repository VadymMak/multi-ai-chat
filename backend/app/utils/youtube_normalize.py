# app/routers/ask_ai_to_ai.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Literal, Optional, Union, List, Dict, Any, Tuple, Iterable
from uuid import uuid4
import asyncio
import re

from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.memory.db import get_db
from app.memory.manager import MemoryManager
from app.memory.models import Project
from app.providers.openai_provider import ask_openai
from app.providers.claude_provider import ask_claude
from app.services.youtube_http import perform_youtube_search  # unchanged import
from app.services.web_search_service import perform_web_search
from app.prompts.prompt_builder import build_full_prompt
from app.config.settings import settings

router = APIRouter(tags=["Chat"])

# ---- Tunables (overridable via settings) ----
HISTORY_MAX_TOKENS = getattr(settings, "HISTORY_MAX_TOKENS", 1800)
HISTORY_FETCH_LIMIT = getattr(settings, "HISTORY_FETCH_LIMIT", 200)
CANON_TOPK = int(getattr(settings, "CANON_TOPK", 6))
ENABLE_CANON = bool(getattr(settings, "ENABLE_CANON", False))

# -------------------- Output/presentation helpers --------------------
_LANG_HINTS = {
    "c#": "csharp", "csharp": "csharp", "python": "python", "javascript": "javascript",
    "typescript": "typescript", "java": "java", "php": "php", "ruby": "ruby",
    "rust": "rust", "kotlin": "kotlin", "swift": "swift", "sql": "sql",
    "bash": "bash", "powershell": "powershell", "go": "go",
}
_RISKY_SHORT_ALIASES = {"go", "js", "ts", "rb", "rs", "cs", "kt", "sh"}
_LANG_WORD_RE = re.compile(r"\b([A-Za-z#+]+)\b", re.IGNORECASE)
_DOC_HINTS = (
    "markdown", "readme", "doc", "document", "adr", "proposal", "spec",
    "rfc", "notes", "design doc", "bullets", "bullet points", "bullet-point",
    "outline", "list", "checklist", "pros and cons", "pros & cons",
    "advantages", "disadvantages", "compare", "vs "
)
_CODE_FENCE_RE = re.compile(r"```([a-zA-Z0-9#.+-]*)\n([\s\S]*?)```", re.MULTILINE)
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*•·]|(?:\d+)[.)])\s+\S+", re.MULTILINE)

# -------------------- Normalizers (YouTube & Web) --------------------
_YT_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

def _extract_video_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    if "watch?v=" in url:
        return url.split("watch?v=", 1)[1][:11]
    if "youtu.be/" in url:
        return url.split("youtu.be/", 1)[1][:11]
    if "/shorts/" in url:
        return url.split("/shorts/", 1)[1][:11]
    m = _YT_ID_RE.search(url)
    return m.group(0) if m else None

def normalize_youtube_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    Accept dicts or tuples/lists of:
      (title, url[, videoId][, description])  OR  (title, url[, description])
    Returns stable dicts: { title, url, videoId?, description? }.
    """
    out: List[Dict[str, Any]] = []
    for it in items or []:
        title = url = description = None
        video_id = None

        if isinstance(it, dict):
            title = str(it.get("title", "")).strip() or "YouTube"
            url = str(it.get("url") or "").strip()
            video_id = (it.get("videoId") or it.get("id") or None)
            description = it.get("description")
        elif isinstance(it, (list, tuple)):
            if len(it) >= 1:
                title = str(it[0]).strip() or "YouTube"
            if len(it) >= 2:
                url = str(it[1]).strip()
            if len(it) >= 3:
                third = str(it[2]).strip()
                video_id = third if _YT_ID_RE.fullmatch(third) else None
                if not video_id:
                    description = third
            if len(it) >= 4 and description is None:
                description = str(it[3])
        else:
            continue

        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"

        if url:
            if not video_id:
                video_id = _extract_video_id_from_url(url)
            out.append({
                "title": title or "YouTube",
                "url": url,
                "videoId": video_id,
                "description": description,
            })
    return out

def build_youtube_block(items: List[Dict[str, Any]], max_lines: int = 5) -> str:
    lines: List[str] = []
    for v in items[:max_lines]:
        t = (v.get("title") or "YouTube").strip()
        u = (v.get("url") or "").strip()
        if u:
            lines.append(f"{t} - {u}")
    return "📋 YOUTUBE:\n" + ("\n".join(lines) if lines else "None.")

def normalize_web_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    Make sure each item has at least {title, url, snippet?}.
    Tolerates tuples or dicts.
    """
    out: List[Dict[str, Any]] = []
    for it in items or []:
        title = url = snippet = None
        if isinstance(it, dict):
            title = str(it.get("title", "")).strip()
            url = str(it.get("url", "")).strip()
            snippet = it.get("snippet")
        elif isinstance(it, (list, tuple)):
            if len(it) >= 1:
                title = str(it[0]).strip()
            if len(it) >= 2:
                url = str(it[1]).strip()
            if len(it) >= 3:
                snippet = it[2]
        if url:
            out.append({
                "title": title or "",
                "url": url,
                "snippet": snippet if isinstance(snippet, str) else None,
            })
    return out

# --- Fallback link extraction (from text) -----------------------------------
_YT_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_YT_URL_RE = re.compile(r"https?://[^\s)]+")
def _is_youtube(url: str) -> bool:
    u = url.lower()
    return "youtube.com" in u or "youtu.be" in u

def _extract_youtube_from_text(text: str, max_items: int = 6) -> List[Dict[str, Any]]:
    """Find YouTube links in markdown or bare URLs; return [{title,url,videoId?}]."""
    if not text:
        return []
    found: List[Dict[str, Any]] = []
    seen = set()

    # Markdown links first
    for m in _YT_MD_LINK_RE.finditer(text):
        title, url = (m.group(1) or "").strip(), (m.group(2) or "").strip()
        if not _is_youtube(url):
            continue
        key = (title.lower(), url.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append({"title": title or url, "url": url})
        if len(found) >= max_items:
            return normalize_youtube_items(found)

    # Bare URLs
    if len(found) < max_items:
        for m in _YT_URL_RE.finditer(text):
            url = (m.group(0) or "").strip()
            if not _is_youtube(url):
                continue
            key = ("", url.lower())
            if key in seen:
                continue
            seen.add(key)
            found.append({"title": url, "url": url})
            if len(found) >= max_items:
                break

    return normalize_youtube_items(found)

# -------------------- Rendering helpers --------------------
def _detect_output_mode(
    q: str,
    override_mode: Optional[str] = None,
    override_lang: Optional[str] = None
) -> Tuple[str, Optional[str]]:  # returns ("code"|"doc"|"plain", lang|None)
    if override_mode in {"code", "doc", "plain"}:
        lang = None
        if override_mode == "code" and override_lang:
            k = override_lang.strip().lower()
            lang = _LANG_HINTS.get(k, k)
        return override_mode, lang

    q = q or ""
    ql = q.lower()
    if "```" in q:
        m = re.search(r"```([A-Za-z0-9#+.-]*)", q)
        label = (m.group(1) or "").lower() if m else ""
        lang = _LANG_HINTS.get(label, label) if label else None
        return "code", (lang or None)

    explicit_code_intent = any(
        key in ql for key in (
            " in code", " code", "snippet", "snippets", "script", "program", "function",
            "class ", "write a", "write an", "example in ", "show code", "give code", "source code"
        )
    )
    words = set(w.lower() for w in _LANG_WORD_RE.findall(ql))
    lang: Optional[str] = None
    for alias, norm in _LANG_HINTS.items():
        al = alias.lower()
        if al in _RISKY_SHORT_ALIASES and not explicit_code_intent:
            continue
        if al in words:
            lang = norm
            break

    if explicit_code_intent and (lang or "```" in q):
        return "code", lang
    if any(k in ql for k in _DOC_HINTS):
        return "doc", None
    return "plain", None

def _enforce_code_block(text: str, lang: Optional[str]) -> str:
    text = text or ""
    m = _CODE_FENCE_RE.search(text)
    label = (lang or (m.group(1) if m else "") or "").strip()
    label_map = {"c#": "csharp", "cs": "csharp", "js": "javascript"}
    label = label_map.get(label.lower(), label)
    body = (m.group(2) if m else text).strip()
    return f"```{label}\n{body}\n```"

def _ensure_markdown(text: str) -> str:
    t = (text or "").strip()
    if not t.startswith("# "):
        t = "# Document\n\n" + t
    return t

def _looks_like_markdown_list(text: str) -> bool:
    if not text:
        return False
    matches = _LIST_LINE_RE.findall(text)
    return len(matches) >= 2

def _suggest_filename(lang: Optional[str]) -> Optional[str]:
    l = (lang or "").lower()
    return {
        "csharp": "Program.cs", "python": "main.py", "javascript": "index.js", "typescript": "index.ts",
        "java": "Main.java", "go": "main.go", "php": "index.php", "ruby": "main.rb", "rust": "main.rs",
        "kotlin": "Main.kt", "swift": "main.swift", "sql": "query.sql", "bash": "script.sh",
        "powershell": "script.ps1", "text": "poem.txt",
    }.get(l)

# -------------------- Pydantic model --------------------
class AiToAiRequest(BaseModel):
    topic: str
    starter: Literal["openai", "anthropic"]
    role: Union[int, str]
    project_id: Union[int, str]
    chat_session_id: Optional[str] = None

    # Optional explicit rendering overrides
    output_mode: Optional[Literal["code", "doc", "plain"]] = None
    language: Optional[str] = None

    # Presentation switch for poems / printing workflows
    presentation: Optional[Literal["default", "poem_plain", "poem_code"]] = "default"

    @field_validator("role", mode="before")
    @classmethod
    def convert_role(cls, v):
        try:
            v2 = int(v)
            if v2 <= 0:
                raise ValueError
            return v2
        except Exception:
            raise ValueError("role must be a positive integer")

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v):
        s = "0" if v in (None, "", "default") else str(v).strip()
        if not s.isdigit() or int(s) <= 0:
            raise ValueError("project_id must be a positive integer")
        return s

# -------------------- Provider wrappers & utils --------------------
async def claude_with_retry(messages: List[Dict[str, str]], retries: int = 2) -> str:
    """Claude wrapper with simple retries/backoff (runs provider in a thread)."""
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
    """Map DB rows → provider messages; keep only user/assistant turns."""
    out: List[Dict[str, str]] = []
    for r in rows:
        sender = (r.get("sender") or "").strip().lower()
        text = (r.get("text") or "").strip()
        if not text:
            continue
        if sender in {"openai", "anthropic", "assistant", "final"}:
            out.append({"role": "assistant", "content": text})
        elif sender == "user":
            out.append({"role": "user", "content": text})
    return out

def _clip_by_tokens(memory: MemoryManager, messages: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    """Keep newest turns within token budget by dropping from the front."""
    if not messages:
        return messages
    total = 0
    kept_rev: List[Dict[str, str]] = []
    for m in reversed(messages):
        total += memory.count_tokens(m["content"])
        if total > max_tokens:
            break
        kept_rev.append(m)
    kept = list(reversed(kept_rev))
    dropped = len(messages) - len(kept)
    if dropped > 0:
        print(f"✂️ Trimmed {dropped} old turns to fit token budget ({max_tokens}).")
    try:
        memory.insert_audit_log("?", -1, None, "internal", "token_budget_history", f"kept={len(kept)}, dropped={dropped}")
    except Exception:
        pass
    return kept

def _get_or_create_session_id(memory: MemoryManager, role_id: int, project_id: str, provided: Optional[str]) -> str:
    """Use provided id; else reuse last or mint a new uuid4."""
    if provided and provided.strip():
        return provided.strip()
    try:
        if hasattr(memory, "get_or_create_chat_session_id"):
            return memory.get_or_create_chat_session_id(role_id, project_id)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"[get_or_create_chat_session_id error] {e}")
    last = memory.get_last_session(role_id=role_id, project_id=project_id)
    if last and (last.get("chat_session_id") or "").strip():
        return str(last["chat_session_id"]).strip()
    return str(uuid4())

def _extract_terms_from_topic(topic: str) -> List[str]:
    """Tiny term extractor for Canon search: alnum tokens length ≥ 3."""
    toks = re.findall(r"[A-Za-z0-9_]+", topic or "")
    return [t for t in toks if len(t) >= 3][:8]

# -------------------- Main route --------------------
@router.post("/ask-ai-to-ai")
async def ask_ai_to_ai_route(data: AiToAiRequest, db: Session = Depends(get_db)):
    """
    Boost mode: one model answers, Claude reviews, then a final summary is produced.
    Returns:
    {
      "messages": [
        {"sender": "<starter>", "answer": "..."},
        {"sender": "anthropic", "answer": "<review>"}
      ],
      "summary": "<final_reply>",
      "youtube": [...],
      "web": [...],
      "chat_session_id": "<id>",
      "canon"?: { "hits": int, "items": [...] }   # optional
    }
    """
    memory = MemoryManager(db)
    role_id = data.role
    project_id = data.project_id
    chat_session_id = _get_or_create_session_id(memory, role_id, project_id, data.chat_session_id)

    print(
        f"⚙️ Boost Mode: topic='{data.topic}' | starter={data.starter} | "
        f"role={role_id} | project_id={project_id} | session={chat_session_id}"
    )

    # ---- History for context (trim) ----
    messages_data = memory.retrieve_messages(
        role_id=role_id,
        project_id=project_id,
        chat_session_id=chat_session_id,
        limit=HISTORY_FETCH_LIMIT,
    )
    rows = messages_data.get("messages", [])
    history = _rows_to_messages(rows)
    history = _clip_by_tokens(memory, history, HISTORY_MAX_TOKENS)
    if history:
        print(f"🧩 Context included → {len(history)} turns")
    else:
        print("🧩 No prior turns available for boost session.")

    # ---- Canonical Context (optional) ----
    canon_digest = ""
    canon_items_struct: List[Dict[str, Any]] = []
    if ENABLE_CANON and hasattr(memory, "retrieve_context_digest"):
        try:
            query_terms = _extract_terms_from_topic(data.topic)
            canon_digest, canon_items_struct = memory.retrieve_context_digest(
                project_id=project_id,
                role_id=role_id,
                query_terms=query_terms,
                top_k=CANON_TOPK,
            )
            try:
                memory.insert_audit_log(
                    project_id, role_id, chat_session_id, "internal", "canon_fetch",
                    f"hits={len(canon_items_struct)} terms={','.join(query_terms)[:120]}"
                )
            except Exception:
                pass
        except Exception as e:
            print(f"[Canon digest error] {e}")

    # ---- Context gathering (safe, shape-agnostic) ----
    yt_block: str = "📋 YOUTUBE: None."
    yt_hits: List[Dict[str, Any]] = []
    try:
        # Some implementations return (block, hits); others return just hits; some return dicts
        raw_yt = await run_in_threadpool(perform_youtube_search, data.topic, memory, role_id, project_id)
        if isinstance(raw_yt, tuple) and len(raw_yt) == 2:
            raw_block, raw_items = raw_yt
            yt_hits = normalize_youtube_items(raw_items)
            yt_block = str(raw_block or "").strip() or build_youtube_block(yt_hits)
        elif isinstance(raw_yt, list):
            yt_hits = normalize_youtube_items(raw_yt)
            yt_block = build_youtube_block(yt_hits)
        elif isinstance(raw_yt, dict):
            items = raw_yt.get("items") or raw_yt.get("results") or []
            yt_hits = normalize_youtube_items(items)
            yt_block = str(raw_yt.get("block") or "").strip() or build_youtube_block(yt_hits)
        elif isinstance(raw_yt, str):
            yt_block = raw_yt
        else:
            yt_block = "📋 YOUTUBE: None."
    except Exception as e:
        yt_block, yt_hits = "📋 YOUTUBE: None.", []
        print(f"[YouTube Error] {e}")

    try:
        raw_web = await run_in_threadpool(perform_web_search, data.topic)
        web_hits = normalize_web_items(raw_web if isinstance(raw_web, (list, tuple)) else raw_web or [])
    except Exception as e:
        web_hits = []
        print(f"[Web Search Error] {e}")

    # ---- Write the synthetic "user" message that seeds the debate ----
    user_message = f"{data.topic}\n\n{yt_block}"
    memory.store_chat_message(project_id, role_id, chat_session_id, "user", user_message, is_ai_to_ai=True)

    # -------------------- Render policy --------------------
    base_system = (
        "You are a thoughtful assistant collaborating with another model. "
        "You DO have access to the trimmed chat history provided; use it to stay consistent."
    )

    mode, lang = _detect_output_mode(data.topic, data.output_mode, data.language)

    force_code = (data.presentation == "poem_code")
    force_plain = (data.presentation == "poem_plain")

    if force_code:
        render_policy = (
            "\n\n[RENDER_POLICY] Output EXACTLY one fenced code block labeled `text` "
            "containing ONLY the poem text (each verse on its own line). "
            "No headings, no explanations before or after, no extra prose."
        )
    elif force_plain:
        render_policy = (
            "\n\n[RENDER_POLICY] Respond in concise plain text. "
            "Do NOT include triple backticks, fenced code blocks, or markdown lists. "
            "If you output a poem, write it as normal lines/paragraphs, not as bullets."
        )
    elif mode == "code":
        render_policy = f"\n\n[RENDER_POLICY] Return a single fenced code block labeled `{lang or ''}`. No commentary."
    elif mode == "doc":
        render_policy = "\n\n[RENDER_POLICY] Return valid GitHub-flavored Markdown only. Start with an `#` title. No pre/post text."
    else:
        render_policy = (
            "\n\n[RENDER_POLICY] Respond in concise plain text. "
            "Do NOT include triple backticks or fenced code blocks under any circumstances."
        )

    policy_system_msg = {"role": "system", "content": base_system + render_policy}

    # -------------------- Starter model reply --------------------
    starter_messages: List[Dict[str, str]] = history + [policy_system_msg, {"role": "user", "content": user_message}]
    try:
        if data.starter == "openai":
            first_reply_raw: str = await run_in_threadpool(ask_openai, starter_messages)
            starter_sender = "openai"
        else:
            first_reply_raw = await claude_with_retry(starter_messages)
            starter_sender = "anthropic"
    except Exception as e:
        print(f"❌ Starter model error: {e}")
        raise HTTPException(status_code=502, detail="Starter model failed")

    def _post_process(answer: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        # Enforce presentation overrides
        if force_code:
            answer2 = _enforce_code_block(answer or "", "text")
            render_meta = {"type": "code", "language": "text", "filename": _suggest_filename("text")}
            return answer2, render_meta
        if force_plain:
            if _CODE_FENCE_RE.search(answer or ""):
                answer = _CODE_FENCE_RE.sub(lambda m: (m.group(2) or "").strip(), answer or "")
            return answer, None

        # Normal post-process
        render_meta: Optional[Dict[str, Any]] = None
        if mode == "code":
            answer2 = _enforce_code_block(answer, lang)
            render_meta = {"type": "code", "language": (lang or "").lower() or None, "filename": _suggest_filename(lang)}
            return answer2, render_meta
        if mode == "doc":
            answer2 = _ensure_markdown(answer)
            render_meta = {"type": "markdown"}
            return answer2, render_meta
        # plain
        if _CODE_FENCE_RE.search(answer or ""):
            answer = _CODE_FENCE_RE.sub(lambda m: (m.group(2) or "").strip(), answer or "")
        if _looks_like_markdown_list(answer) or answer.lstrip().startswith("# "):
            render_meta = {"type": "markdown"}
        return answer, render_meta

    first_reply, _first_render = _post_process(first_reply_raw)

    # --- Fallback: extract YouTube links from the starter reply (or topic) ---
    if not yt_hits:
        try:
            fallback_yt = _extract_youtube_from_text(first_reply)
            if not fallback_yt:
                fallback_yt = _extract_youtube_from_text(data.topic)
            if fallback_yt:
                yt_hits = fallback_yt
                yt_block = build_youtube_block(yt_hits)
                print(f"[YouTube Fallback] extracted {len(fallback_yt)} link(s) from text.")
        except Exception as e:
            print(f"[YouTube Fallback Error] {e}")

    memory.store_chat_message(project_id, role_id, chat_session_id, starter_sender, first_reply, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, starter_sender, "boost_reply", first_reply[:300])

    # -------------------- Claude review --------------------
    review_messages = [
        policy_system_msg,
        {
            "role": "user",
            "content": (
                f'Here is the assistant\'s reply to the topic "{data.topic}":\n\n'
                f"{first_reply}\n\n"
                "Please review and reflect on this reply. Highlight what’s good, what could be improved, "
                "and what additional context might help the user. Be objective and constructive."
            ),
        },
    ]
    claude_review_raw = await claude_with_retry(review_messages)
    claude_review, _review_render = _post_process(claude_review_raw)

    memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_review, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "boost_review", claude_review[:300])

    # -------------------- Final summary (Claude) --------------------
    try:
        memory_summaries = memory.load_recent_summaries(role_id=role_id, project_id=project_id, limit=5)
    except Exception as e:
        print(f"[Memory summaries error] {e}")
        memory_summaries = []

    try:
        proj_id_int = int(project_id) if str(project_id).isdigit() else None
        project: Optional[Project] = db.query(Project).filter_by(id=proj_id_int).first() if proj_id_int else None
        project_structure = project.project_structure if project else ""
    except Exception as e:
        print(f"[Project lookup error] {e}")
        project_structure = ""

    youtube_context: List[str] = []
    for v in yt_hits:
        t = (v.get("title") or "YouTube").strip()
        u = (v.get("url") or "").strip()
        if u:
            youtube_context.append(f"{t} - {u}")

    web_context: List[str] = []
    for v in web_hits:
        t = (v.get("title") or "").strip()
        s = (v.get("snippet") or "").strip()
        if t or s:
            web_context.append(f"{t} - {s}".strip(" -"))

    system_prompt = (
        "You are a thoughtful assistant summarizing and enhancing user research. "
        "You DO have access to the trimmed chat history provided; use it to stay consistent."
        + render_policy
    )

    full_prompt = build_full_prompt(
        system_prompt=system_prompt,
        project_structure=project_structure,
        memory_summaries=memory_summaries,
        youtube_context=youtube_context,
        web_context=web_context,
        starter_reply=first_reply,
        user_input=data.topic,
        max_memory_tokens=600,
        canonical_context=(canon_digest or None),
    )

    try:
        final_reply_raw = await claude_with_retry([{"role": "user", "content": full_prompt}])
    except Exception as e:
        print(f"❌ Final summary error: {e}")
        raise HTTPException(status_code=502, detail="Final summary model failed")

    final_reply, _final_render = _post_process(final_reply_raw)

    memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_reply, is_ai_to_ai=True)
    memory.insert_audit_log(project_id, role_id, chat_session_id, "anthropic", "boost_summary", final_reply[:300])

    # ---- Persist Boost Memory ----
    try:
        transcript = (
            history
            + [{"role": "assistant", "content": first_reply}]
            + [{"role": "assistant", "content": claude_review}]
            + [{"role": "assistant", "content": final_reply}]
        )
        raw_text = "\n".join([f"{m['role']}: {m['content']}" for m in transcript])
        summary = memory.summarize_messages([raw_text])
        memory.store_memory(project_id, role_id, summary, raw_text, chat_session_id, is_ai_to_ai=True)
    except Exception as e:
        print(f"[Boost memory summary error] {e}")

    print("✅ Boost Mode completed.")

    resp: Dict[str, Any] = {
        "messages": [
            {"sender": starter_sender, "answer": first_reply},
            {"sender": "anthropic", "answer": claude_review},
        ],
        "summary": final_reply,
        "youtube": yt_hits,   # normalized dicts
        "web": web_hits,      # normalized dicts
        "chat_session_id": chat_session_id,
    }
    if canon_items_struct:
        resp["canon"] = {"hits": len(canon_items_struct), "items": canon_items_struct}

    return JSONResponse(content=resp)
