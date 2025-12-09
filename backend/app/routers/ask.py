# File: app/routers/ask.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Literal, Union, Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
import re
import asyncio

from app.providers.factory import ask_model
from app.providers.streaming import stream_openai, stream_claude
from app.memory.manager import MemoryManager
from app.memory.db import get_db
from app.memory.models import Role, Project, User
from app.prompts.prompt_builder import generate_prompt_from_db
from app.config.settings import settings
from app.config.model_registry import MODEL_REGISTRY
from app.services.vector_service import store_message_with_embedding, get_relevant_context
from sse_starlette.sse import EventSourceResponse
import json
from app.deps import get_current_active_user
from app.utils.api_key_resolver import get_openai_key, get_anthropic_key
from app.services.smart_context import build_smart_context

# ✅ Deterministic YouTube path
from app.services.youtube_service import search_videos

# Optional dynamic thresholds + token preflight
try:
    from app.config.settings import get_thresholds  # type: ignore
except Exception:  # pragma: no cover
    def get_thresholds(model: Optional[str] = None, provider: Optional[str] = None) -> Tuple[int, int]:
        soft = int(getattr(settings, "SOFT_TOKEN_BUDGET", 6000))
        hard = int(getattr(settings, "HARD_TOKEN_BUDGET", 7800))
        return soft, hard

try:
    from app.services.token_service import preflight as token_preflight  # type: ignore
except Exception:  # pragma: no cover
    token_preflight = None  # falls back to MemoryManager counting

router = APIRouter(tags=["Chat"])

HISTORY_MAX_TOKENS = getattr(settings, "HISTORY_MAX_TOKENS", 1800)
HISTORY_FETCH_LIMIT = getattr(settings, "HISTORY_FETCH_LIMIT", 200)
SUMMARIZE_TRIGGER_TOKENS = getattr(settings, "SUMMARIZE_TRIGGER_TOKENS", 2000)

ENABLE_CANON = bool(getattr(settings, "ENABLE_CANON", False))
CANON_TOPK = int(getattr(settings, "CANON_TOPK", 6))

# ---------- Output-mode helpers ----------
_LANG_HINTS = {
    "c#": "csharp",
    "csharp": "csharp",
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "php": "php",
    "ruby": "ruby",
    "rust": "rust",
    "kotlin": "kotlin",
    "swift": "swift",
    "sql": "sql",
    "bash": "bash",
    "powershell": "powershell",
    "go": "go",
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

def _detect_output_mode(
    q: str,
    override_mode: Optional[str] = None,
    override_lang: Optional[str] = None
) -> Tuple[str, Optional[str]]:
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
        key in ql
        for key in (
            " in code", " code", "snippet", "snippets", "script",
            "program", "function", "class ", "write a", "write an",
            "example in ", "show code", "give code", "source code"
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
        "csharp": "Program.cs",
        "python": "main.py",
        "javascript": "index.js",
        "typescript": "index.ts",
        "java": "Main.java",
        "go": "main.go",
        "php": "index.php",
        "ruby": "main.rb",
        "rust": "main.rs",
        "kotlin": "Main.kt",
        "swift": "main.swift",
        "sql": "query.sql",
        "bash": "script.sh",
        "powershell": "script.ps1",
        "text": "poem.txt",
    }.get(l)

# ---------- Multi-file code detection helpers ----------
def extract_code_blocks(text: str) -> List[Tuple[str, str, str]]:
    """
    Extract multiple code blocks from AI response with smart filename generation.
    Returns: List of (filename, language, code) tuples
    
    Improvements:
    - Skips empty or very short blocks (< 10 chars)
    - Generates smart filenames based on content analysis
    - Filters out command-only blocks
    """
    # Match: ```language [optional filename]
    pattern = r'```(\w+)(?:\s+([^\n]+))?\n(.*?)```'
    matches = re.finditer(pattern, text, re.DOTALL | re.MULTILINE)
    
    files = []
    language_counters = {}  # Track counts per language for smart naming
    
    for match in matches:
        language = (match.group(1) or "text").lower()
        filename = match.group(2)
        code = (match.group(3) or "").strip()
        
        # Skip empty or very short blocks
        if len(code) < 10:
            continue
            
        # Filter out command-only blocks (npm start, pip install, etc.)
        lines = [line.strip() for line in code.split('\n') if line.strip()]
        if len(lines) <= 2:
            # Check if it's just commands
            command_prefixes = ('npm', 'yarn', 'pip', 'python', 'node', 'cd', 'mkdir', 'touch', 'git', 'docker', 'curl', 'wget')
            if all(any(line.startswith(prefix) for prefix in command_prefixes) for line in lines):
                continue
        
        # Generate smart filename if not provided
        if not filename or filename.startswith('#'):
            filename = _generate_smart_filename(code, language, language_counters)
        
        files.append((filename.strip(), language.strip(), code))
    
    return files

def _generate_smart_filename(code: str, language: str, counters: Dict[str, int]) -> str:
    """
    Generate smart filename based on code content and language.
    """
    lang = language.lower()
    
    # Increment counter for this language
    counters[lang] = counters.get(lang, 0) + 1
    count = counters[lang]
    
    # Language-specific smart naming
    if lang == 'sql':
        # Check for common SQL patterns
        code_lower = code.lower()
        if 'create table' in code_lower or 'create database' in code_lower:
            return 'database.sql'
        elif 'create index' in code_lower:
            return 'indexes.sql'
        elif 'insert into' in code_lower:
            return 'seed_data.sql'
        elif 'select' in code_lower and 'from' in code_lower:
            return 'queries.sql'
        return 'schema.sql' if count == 1 else f'query{count}.sql'
    
    elif lang in ('php', 'python', 'javascript', 'typescript', 'tsx', 'jsx'):
        # Extract class/component/function names
        
        # React component pattern (function/const ComponentName)
        react_match = re.search(r'(?:function|const)\s+([A-Z][a-zA-Z0-9]+)\s*(?:\(|=)', code)
        if react_match and lang in ('tsx', 'jsx', 'typescript', 'javascript'):
            name = react_match.group(1)
            ext = 'tsx' if lang == 'tsx' else 'jsx' if lang == 'jsx' else 'ts' if lang == 'typescript' else 'js'
            return f'{name}.{ext}'
        
        # Class name pattern
        class_match = re.search(r'class\s+([A-Z][a-zA-Z0-9]+)', code)
        if class_match:
            name = class_match.group(1)
            ext_map = {'php': 'php', 'python': 'py', 'typescript': 'ts', 'javascript': 'js'}
            ext = ext_map.get(lang, 'txt')
            return f'{name}.{ext}'
        
        # PHP API patterns
        if lang == 'php':
            if 'api' in code.lower() or '$_POST' in code or '$_GET' in code:
                return 'api.php' if count == 1 else f'api{count}.php'
            elif 'database' in code.lower() or 'mysqli' in code or 'PDO' in code:
                return 'database.php'
            return 'index.php' if count == 1 else f'script{count}.php'
        
        # Python patterns
        if lang == 'python':
            if 'def main(' in code or 'if __name__' in code:
                return 'main.py'
            elif 'flask' in code.lower() or 'fastapi' in code.lower():
                return 'app.py'
            elif 'import unittest' in code or 'import pytest' in code:
                return 'test.py' if count == 1 else f'test{count}.py'
            return 'script.py' if count == 1 else f'module{count}.py'
        
        # JavaScript/TypeScript patterns
        if lang in ('javascript', 'typescript'):
            if 'express' in code.lower() or 'app.listen' in code:
                return 'server.js' if lang == 'javascript' else 'server.ts'
            elif 'export default' in code or 'module.exports' in code:
                return 'index.js' if lang == 'javascript' else 'index.ts'
            return 'app.js' if lang == 'javascript' else 'app.ts'
    
    elif lang == 'html':
        return 'index.html' if count == 1 else f'page{count}.html'
    
    elif lang == 'css':
        if 'root' in code or ':root' in code:
            return 'theme.css'
        return 'styles.css' if count == 1 else f'styles{count}.css'
    
    elif lang == 'json':
        if 'package' in code.lower() or '"name"' in code:
            return 'package.json'
        elif 'tsconfig' in code.lower():
            return 'tsconfig.json'
        return 'config.json' if count == 1 else f'data{count}.json'
    
    elif lang in ('bash', 'shell', 'sh'):
        if 'npm' in code or 'yarn' in code:
            return 'build.sh'
        return 'script.sh' if count == 1 else f'script{count}.sh'
    
    elif lang == 'dockerfile':
        return 'Dockerfile'
    
    elif lang == 'yaml' or lang == 'yml':
        if 'docker-compose' in code.lower():
            return 'docker-compose.yml'
        return 'config.yml' if count == 1 else f'config{count}.yml'
    
    elif lang in ('java', 'kotlin', 'swift'):
        # Extract class name
        class_match = re.search(r'(?:class|interface)\s+([A-Z][a-zA-Z0-9]+)', code)
        if class_match:
            name = class_match.group(1)
            ext_map = {'java': 'java', 'kotlin': 'kt', 'swift': 'swift'}
            return f'{name}.{ext_map.get(lang, "txt")}'
    
    elif lang in ('c', 'cpp', 'cc', 'cxx'):
        if 'int main(' in code or 'void main(' in code:
            return 'main.cpp' if lang in ('cpp', 'cc', 'cxx') else 'main.c'
        return 'program.cpp' if lang in ('cpp', 'cc', 'cxx') else 'program.c'
    
    elif lang == 'rust':
        if 'fn main(' in code:
            return 'main.rs'
        return 'lib.rs' if count == 1 else f'module{count}.rs'
    
    elif lang == 'go':
        if 'func main(' in code:
            return 'main.go'
        return 'app.go' if count == 1 else f'module{count}.go'
    
    # Fallback: use generic naming with proper extensions
    ext_map = {
        'python': 'py', 'javascript': 'js', 'typescript': 'ts',
        'jsx': 'jsx', 'tsx': 'tsx', 'java': 'java',
        'cpp': 'cpp', 'c': 'c', 'go': 'go', 'rust': 'rs',
        'html': 'html', 'css': 'css', 'sql': 'sql',
        'bash': 'sh', 'shell': 'sh', 'json': 'json',
        'php': 'php', 'ruby': 'rb', 'kotlin': 'kt',
        'swift': 'swift', 'xml': 'xml', 'yaml': 'yml',
        'markdown': 'md', 'text': 'txt'
    }
    ext = ext_map.get(lang, 'txt')
    return f'file{count}.{ext}'

def chunk_text(text: str, chunk_size: int = 500) -> List[str]:
    """
    Split text into chunks for smooth streaming.
    Chunk by lines to avoid breaking code mid-line.
    """
    lines = text.split('\n')
    chunks = []
    current_chunk = []
    current_size = 0
    
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        
        if current_size + line_len > chunk_size and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_size = line_len
        else:
            current_chunk.append(line)
            current_size += line_len
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks

# ---------- YouTube helpers ----------
_YT_PREFIX = re.compile(r"^\s*(?:youtube:|yt:)\s*(.+)$", re.IGNORECASE)
_YT_FIND = re.compile(r"\b(?:find on youtube|search youtube for)\b[:\s]*(.+)$", re.IGNORECASE)

def _detect_youtube_intent(q: str) -> Optional[str]:
    if not q:
        return None
    m = _YT_PREFIX.match(q)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = _YT_FIND.search(q)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None

async def _safe_youtube(topic: str) -> List[Dict[str, str]]:
    timeout = float(getattr(settings, "YT_SEARCH_TIMEOUT", 6.0))
    maxn = int(getattr(settings, "YT_SEARCH_MAX_RESULTS", 3))
    since_months = int(getattr(settings, "YT_SINCE_MONTHS", 24))
    order = getattr(settings, "YOUTUBE_ORDER", "relevance")
    region = getattr(settings, "YOUTUBE_REGION_CODE", "")

    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(
                search_videos,
                query=topic,
                max_results=maxn,
                since_months=since_months,
                channels=None,
                order=order,
                region=region,
                debug=bool(getattr(settings, "YOUTUBE_DEBUG", False)),
            ),
            timeout=timeout,
        )
    except Exception as e:
        print(f"[YouTube] fetch skipped or failed: {e}")
        return []

    out: List[Dict[str, str]] = []
    seen = set()
    for it in (items or []):
        title = str(it.get("title", "")).strip()
        url = str(it.get("url", "")).strip()
        vid = str(it.get("videoId", "")).strip()
        if not url and vid:
            url = f"https://www.youtube.com/watch?v={vid}"
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title or url, "url": url})
    return out[:maxn]

# ---------- Pydantic ----------
class AskRequest(BaseModel):
    query: str
    provider: Literal["openai", "anthropic", "all"] = "openai"
    model_key: Optional[str] = None
    role_id: int
    project_id: Union[int, str]
    chat_session_id: Optional[str] = None

    output_mode: Optional[Literal["code", "doc", "plain"]] = None
    language: Optional[str] = None
    presentation: Optional[Literal["default", "poem_plain", "poem_code"]] = "default"

    @field_validator("role_id")
    @classmethod
    def role_id_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("role_id must be a positive integer")
        return value

    @field_validator("project_id", mode="before")
    @classmethod
    def project_id_safe(cls, v):
        if v in (None, "", "default"):
            raise ValueError("project_id is required and must be a positive integer")
        s = str(v).strip()
        if not s.isdigit() or int(s) <= 0:
            raise ValueError("project_id must be a positive integer")
        return s  # MemoryManager expects string project_id

def _db_rows_to_chat_messages(rows: List[Dict[str, Any]], memory: MemoryManager) -> List[Dict[str, str]]:
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

def _clip_history_by_tokens(memory: MemoryManager, messages: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
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
    return kept

def _registry_key_for_model_name(model_name: Optional[str]) -> Optional[str]:
    if not model_name:
        return None
    for k, v in MODEL_REGISTRY.items():
        if v.get("model") == model_name:
            return k
    return None

def _default_key_for_provider(provider: str) -> str:
    p = (provider or "").lower()
    if p == "anthropic":
        anth_raw = getattr(settings, "ANTHROPIC_DEFAULT_MODEL", None)
        return _registry_key_for_model_name(anth_raw) or "claude-3-5-sonnet"
    if settings.DEFAULT_MODEL in MODEL_REGISTRY and MODEL_REGISTRY[settings.DEFAULT_MODEL]["provider"] == "openai":
        return settings.DEFAULT_MODEL
    openai_raw = getattr(settings, "OPENAI_DEFAULT_MODEL", None)
    return _registry_key_for_model_name(openai_raw) or "gpt-4o"

async def _auto_summarize_if_needed(memory: MemoryManager, role_id: int, project_id: str, chat_session_id: Optional[str]):
    try:
        messages_data = memory.retrieve_messages(role_id=role_id, project_id=project_id, chat_session_id=chat_session_id, limit=1000)
        rows = messages_data.get("messages", [])
        if not rows or len(rows) < 2:
            return
        texts = [(r.get("text") or "") for r in rows]
        texts = [t for t in texts if not t.startswith("[OpenAI Error]")]
        total_tokens = sum(memory.count_tokens(t) for t in texts)
        print(f"🔍 Token check → total={total_tokens}, threshold={SUMMARIZE_TRIGGER_TOKENS}")
        if total_tokens <= SUMMARIZE_TRIGGER_TOKENS:
            return
        combined_text = "\n".join(f"{(r.get('sender') or '')}: {(r.get('text') or '')}" for r in rows)[:4000]
        summary = memory.summarize_messages([combined_text])
        memory.store_memory(project_id, role_id, summary, combined_text, chat_session_id)
        memory.delete_chat_messages(project_id, role_id, chat_session_id)
        memory.store_chat_message(project_id, role_id, chat_session_id, "system", "📌 New Phase After Summarization")
        try:
            memory.insert_audit_log(
                project_id, role_id, chat_session_id, "internal", "autosummarize_trigger",
                f"total_tokens={total_tokens} threshold={SUMMARIZE_TRIGGER_TOKENS}"
            )
        except Exception:
            pass
        print("✅ Auto-summary stored.")
    except Exception as e:
        print(f"❌ Summarization error: {e}")

@router.post("/ask")
async def ask_route(
    data: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    debug: Optional[bool] = Query(default=False, description="Include token thresholds and preflight info"),
):
    # ---- Validate FK existence
    role_id = int(data.role_id)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role_id={role_id}. Create the role first.")

    project_id_str = str(data.project_id).strip()
    if not project_id_str.isdigit() or int(project_id_str) <= 0:
        raise HTTPException(status_code=400, detail="project_id must be a positive integer")
    project_id_int = int(project_id_str)
    project = db.get(Project, project_id_int)
    if not project:
        raise HTTPException(status_code=400, detail=f"Unknown project_id={project_id_int}. Create/link the project first.")
    project_id = project_id_str  # MemoryManager expects string

    memory = MemoryManager(db)

    # Get user API keys based on provider
    user_api_key: Optional[str] = None
    if data.provider == "openai" or data.provider == "all":
        user_api_key = get_openai_key(current_user, db, required=True)
    elif data.provider == "anthropic":
        user_api_key = get_anthropic_key(current_user, db, required=True)

    # Stable session id
    if data.chat_session_id:
        chat_session_id = data.chat_session_id.strip()
    elif hasattr(memory, "get_or_create_chat_session_id"):
        chat_session_id = memory.get_or_create_chat_session_id(role_id, project_id)  # type: ignore[attr-defined]
    else:
        chat_session_id = str(uuid4())

    print(
        f"\n📅 /ask role={role_id} project={project_id} session={chat_session_id} "
        f"provider={data.provider} model_key={data.model_key} user_id={current_user.id}"
    )
    print(f"📥 User: {data.query[:120]}")

    try:
        # 1) write user msg + audit
        user_entry = memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.query)
        memory.insert_audit_log(project_id, role_id, chat_session_id, data.provider, "ask", query=data.query)
        
        # 1a) Generate embedding for user message (async, don't block on errors)
        try:
            store_message_with_embedding(db, user_entry.id, data.query)
        except Exception as e:
            print(f"[Embedding] User message skipped: {e}")

        # 2) Build Smart Context (replaces full history loading)
        print(f"🎯 [Smart Context] Building context for query: {data.query[:50]}...")
        smart_context_text = await build_smart_context(
            project_id=project_id_int,
            role_id=role_id,
            query=data.query,
            session_id=chat_session_id,
            db=db,
            memory=memory
        )

        print(f"🔍 [DEBUG ask.py] smart_context_text length: {len(smart_context_text)} chars")
        print(f"🔍 [DEBUG ask.py] First 500 chars:\n{smart_context_text[:500]}")
        print(f"🔍 [DEBUG ask.py] Contains 'pgvector': {'pgvector' in smart_context_text}")
        print(f"🔍 [DEBUG ask.py] Contains '```': {'```' in smart_context_text}")  # Проверка есть ли код
        
        # Smart Context as system message
        hist_now = []
        print(f"✅ [Smart Context] Context ready (~4K tokens)")

        # 3) YouTube intent (force plain output when present)
        youtube_items: List[Dict[str, str]] = []
        youtube_context_blocks: List[str] = []
        yt_topic = None
        if bool(getattr(settings, "ENABLE_YT_IN_CHAT", True)):
            yt_topic = _detect_youtube_intent(data.query)
            if yt_topic:
                print(f"[YT] intent detected → topic='{yt_topic}'")
                youtube_items = await _safe_youtube(yt_topic)
                if youtube_items:
                    youtube_context_blocks = [
                        "\n".join(f"- {i+1}. {it['title']} — {it['url']}" for i, it in enumerate(youtube_items))
                    ]
                    try:
                        memory.insert_audit_log(
                            project_id, role_id, chat_session_id, "youtube", "search", yt_topic[:200]
                        )
                    except Exception:
                        pass

        # 4) Build prompt + render policy
        base_system = (
            "You are a helpful assistant. You DO have access to the chat history included below. "
            "Use it to stay consistent, reference prior messages, and avoid claiming you cannot see previous messages."
        )

        mode, lang = _detect_output_mode(data.query, data.output_mode, data.language)

        force_plain = (yt_topic is not None) or (data.presentation == "poem_plain")
        force_code = (data.presentation == "poem_code")
        if force_code:
            mode, lang = "code", "text"
        elif force_plain:
            mode, lang = "plain", None

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
                "Do NOT include URLs. If YouTube links are present in context, "
                "DO NOT re-list them; the UI will show video cards separately."
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

        full_prompt = generate_prompt_from_db(
            db=db,
            project_id=None,
            role_id=role_id,
            system_prompt=base_system + render_policy + "\n\n" + smart_context_text,
            youtube_context=youtube_context_blocks,
            web_context=[],
            starter_reply="",
            user_input=data.query,
            max_memory_tokens=0,
            canonical_context=None,
        )

        # 5) Use Smart Context + current query
        history = hist_now + [{"role": "user", "content": data.query}]

        debug_info: Optional[Dict[str, Any]] = None
        if debug:
            debug_info = {
                "smart_context": "enabled",
                "mode": mode,
                "presentation": data.presentation,
                "yt_topic": yt_topic,
            }

        def store_and_respond(sender: str, text: str, render: Optional[Dict[str, Any]] = None):
            ai_entry = memory.store_chat_message(project_id, role_id, chat_session_id, sender, text)
            memory.insert_audit_log(project_id, role_id, chat_session_id, sender, "reply", text[:300])
            
            # Generate embedding for AI response (async, don't block on errors)
            try:
                if sender in ["openai", "anthropic", "assistant", "final"]:
                    store_message_with_embedding(db, ai_entry.id, text)
            except Exception as e:
                print(f"[Embedding] AI response skipped: {e}")
            
            resp: Dict[str, Any] = {"provider": sender, "answer": text, "chat_session_id": chat_session_id}
            if render:
                resp["render"] = render
            if youtube_items:
                resp.setdefault("sources", {})["youtube"] = youtube_items
            if debug_info:
                resp["debug"] = debug_info
            return resp

        def _post_process(answer: str) -> Tuple[str, Optional[Dict[str, Any]]]:
            """
            Return (final_text, render_meta) where render_meta uses the *frontend*
            contract: render = { kind: 'code'|'markdown'|'plain', language?, filename? }.
            """
            if force_code:
                answer2 = _enforce_code_block(answer or "", "text")
                render_meta = {"kind": "code", "language": "text", "filename": _suggest_filename("text")}
                return answer2, render_meta

            if force_plain:
                if _CODE_FENCE_RE.search(answer or ""):
                    answer = _CODE_FENCE_RE.sub(lambda m: (m.group(2) or "").strip(), answer or "")
                return answer, {"kind": "plain"}

            render_meta: Optional[Dict[str, Any]] = None
            if mode == "code":
                answer2 = _enforce_code_block(answer, lang)
                render_meta = {"kind": "code", "language": (lang or "").lower() or None, "filename": _suggest_filename(lang)}
                return answer2, render_meta
            if mode == "doc":
                answer2 = _ensure_markdown(answer)
                render_meta = {"kind": "markdown"}
                return answer2, render_meta
            if _CODE_FENCE_RE.search(answer or ""):
                answer = _CODE_FENCE_RE.sub(lambda m: (m.group(2) or "").strip(), answer or "")
            if _looks_like_markdown_list(answer) or answer.lstrip().startswith("# "):
                render_meta = {"kind": "markdown"}
            else:
                render_meta = {"kind": "plain"}
            return answer, render_meta

        # 6) Provider selection
        if data.provider == "all":
            if data.model_key and MODEL_REGISTRY.get(data.model_key, {}).get("provider") == "openai":
                openai_key = data.model_key
            elif settings.DEFAULT_MODEL in MODEL_REGISTRY and MODEL_REGISTRY[settings.DEFAULT_MODEL]["provider"] == "openai":
                openai_key = settings.DEFAULT_MODEL
            else:
                openai_key = _registry_key_for_model_name(getattr(settings, "OPENAI_DEFAULT_MODEL", None)) or "gpt-4o"

            if data.model_key and MODEL_REGISTRY.get(data.model_key, {}).get("provider") == "anthropic":
                anthropic_key = data.model_key
            else:
                anthropic_key = _registry_key_for_model_name(getattr(settings, "ANTHROPIC_DEFAULT_MODEL", None)) or "claude-3-5-sonnet"

            openai_api_key = get_openai_key(current_user, db, required=True)
            anthropic_api_key = get_anthropic_key(current_user, db, required=True)
            
            openai_reply = ask_model(history, model_key=openai_key, system_prompt=full_prompt, api_key=openai_api_key)
            claude_reply = ask_model(history, model_key=anthropic_key, system_prompt=full_prompt, api_key=anthropic_api_key)

            openai_reply, openai_render = _post_process(openai_reply)
            claude_reply, claude_render = _post_process(claude_reply)

            summary_prompt = (
                "Summarize both AI responses in a fair, concise, plain-text way. "
                "Avoid any fenced code unless explicitly asked for code.\n\n"
                f"OpenAI:\n{openai_reply}\n\nClaude:\n{claude_reply}\n"
            )
            final_summary = ask_model([{"role": "user", "content": summary_prompt}], model_key=openai_key, system_prompt=full_prompt, api_key=openai_api_key)

            openai_entry = memory.store_chat_message(project_id, role_id, chat_session_id, "openai", openai_reply)
            claude_entry = memory.store_chat_message(project_id, role_id, chat_session_id, "anthropic", claude_reply)
            final_entry = memory.store_chat_message(project_id, role_id, chat_session_id, "final", final_summary)
            
            # Generate embeddings for all responses (async, don't block on errors)
            try:
                store_message_with_embedding(db, openai_entry.id, openai_reply)
                store_message_with_embedding(db, claude_entry.id, claude_reply)
                store_message_with_embedding(db, final_entry.id, final_summary)
            except Exception as e:
                print(f"[Embedding] Response embeddings skipped: {e}")

            resp: Dict[str, Any] = {
                "provider": "all",
                "openai": openai_reply,
                "openai_render": openai_render,
                "claude": claude_reply,
                "anthropic_render": claude_render,
                "summary": final_summary,
                "chat_session_id": chat_session_id,
            }
            if youtube_items:
                resp["sources"] = {"youtube": youtube_items}
            if debug_info:
                resp["debug"] = debug_info
            return resp

        chosen_key = data.model_key or _default_key_for_provider(data.provider)
        reg = MODEL_REGISTRY.get(chosen_key)
        if reg and data.provider in {"openai", "anthropic"} and reg["provider"] != data.provider:
            chosen_key = _default_key_for_provider(data.provider)

        answer_raw = ask_model(history, model_key=chosen_key, system_prompt=full_prompt, api_key=user_api_key)
        answer, render_meta = _post_process(answer_raw)

        info = MODEL_REGISTRY.get(chosen_key)
        sender = info["provider"] if info else ("openai" if chosen_key.startswith("gpt-") else "anthropic")
        return store_and_respond(sender, answer, render=render_meta)

    except IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Database integrity error: {getattr(e, 'orig', e)}")
    except Exception as e:
        print(f"❌ Error in /ask: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask-stream")
async def ask_stream_route(
    data: AskRequest,
    db: Session = Depends(get_db),
):
    """
    Streaming version of /ask endpoint using Server-Sent Events.
    Streams responses token-by-token as they arrive from the AI provider.
    """
    # ---- Validate FK existence (same as /ask)
    role_id = int(data.role_id)
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role_id={role_id}. Create the role first.")

    project_id_str = str(data.project_id).strip()
    if not project_id_str.isdigit() or int(project_id_str) <= 0:
        raise HTTPException(status_code=400, detail="project_id must be a positive integer")
    project_id_int = int(project_id_str)
    project = db.get(Project, project_id_int)
    if not project:
        raise HTTPException(status_code=400, detail=f"Unknown project_id={project_id_int}. Create/link the project first.")
    project_id = project_id_str

    memory = MemoryManager(db)

    # Stable session id
    if data.chat_session_id:
        chat_session_id = data.chat_session_id.strip()
    elif hasattr(memory, "get_or_create_chat_session_id"):
        chat_session_id = memory.get_or_create_chat_session_id(role_id, project_id)  # type: ignore[attr-defined]
    else:
        chat_session_id = str(uuid4())

    print(
        f"\n🌊 /ask-stream role={role_id} project={project_id} session={chat_session_id} "
        f"provider={data.provider} model_key={data.model_key}"
    )
    print(f"📥 User: {data.query[:120]}")

    async def event_generator():
        try:
            # 1) Store user message
            memory.store_chat_message(project_id, role_id, chat_session_id, "user", data.query)
            memory.insert_audit_log(project_id, role_id, chat_session_id, data.provider, "ask_stream", query=data.query)

            # Send initial status
            yield f"{json.dumps({'event': 'status', 'data': {'status': 'processing'}})}\n\n"

            # 2) Build Smart Context (replaces full history loading)
            print(f"🎯 [Smart Context] Building context for streaming query: {data.query[:50]}...")
            smart_context_text =await build_smart_context(
                project_id=project_id_int,
                role_id=role_id,
                query=data.query,
                session_id=chat_session_id,
                db=db,
                memory=memory
            )
            
            # Smart Context as system message
            hist_now = []
            print(f"✅ [Smart Context] Context ready for streaming (~4K tokens)")

            # 3) Build prompt (same as /ask)
            base_system = (
                "You are a helpful assistant. You DO have access to the chat history included below. "
                "Use it to stay consistent, reference prior messages, and avoid claiming you cannot see previous messages."
            )

            mode, lang = _detect_output_mode(data.query, data.output_mode, data.language)

            force_plain = (data.presentation == "poem_plain")
            force_code = (data.presentation == "poem_code")
            if force_code:
                mode, lang = "code", "text"
            elif force_plain:
                mode, lang = "plain", None

            if force_code:
                render_policy = (
                    "\n\n[RENDER_POLICY] Output EXACTLY one fenced code block labeled `text` "
                    "containing ONLY the poem text (each verse on its own line). "
                    "No headings, no explanations before or after, no extra prose."
                )
            elif force_plain:
                render_policy = (
                    "\n\n[RENDER_POLICY] Respond in concise plain text. "
                    "Do NOT include triple backticks, fenced code blocks, or markdown lists."
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

            full_prompt = generate_prompt_from_db(
                db=db,
                project_id=None,
                role_id=role_id,
                system_prompt=base_system + render_policy + "\n\n" + smart_context_text,
                youtube_context=[],
                web_context=[],
                starter_reply="",
                user_input=data.query,
                max_memory_tokens=0,
                canonical_context=None,
            )

            # 4) Use Smart Context + current query
            history = hist_now + [{"role": "user", "content": data.query}]

            # 5) Determine model and parameters
            chosen_key = data.model_key or _default_key_for_provider(data.provider)
            reg = MODEL_REGISTRY.get(chosen_key)
            if reg and data.provider in {"openai", "anthropic"} and reg["provider"] != data.provider:
                chosen_key = _default_key_for_provider(data.provider)

            model_info = MODEL_REGISTRY.get(chosen_key, {})
            chosen_model = model_info.get("model", "gpt-4o-mini")
            actual_provider = model_info.get("provider", data.provider)
            max_tokens = model_info.get("max_tokens", 4096)
            temperature = model_info.get("temperature", 0.7)

            # 6) Stream based on provider
            full_response = ""

            if actual_provider == "openai":
                async for chunk in stream_openai(
                    messages=history,
                    model=chosen_model,
                    system_prompt=full_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature
                ):
                    full_response += chunk
                    yield f"{json.dumps({'event': 'chunk', 'data': {'content': chunk, 'accumulated': full_response}})}\n\n"

            elif actual_provider == "anthropic":
                async for chunk in stream_claude(
                    messages=history,
                    model=chosen_model,
                    system=full_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature
                ):
                    full_response += chunk
                    yield f"{json.dumps({'event': 'chunk', 'data': {'content': chunk, 'accumulated': full_response}})}\n\n"
            else:
                error_msg = f"Unsupported provider for streaming: {actual_provider}"
                print(f"❌ {error_msg}")
                yield f"{json.dumps({'event': 'error', 'data': {'error': error_msg}})}\n\n"
                return

            # 6a) Detect and stream multiple files separately
            code_blocks = extract_code_blocks(full_response)
            
            if len(code_blocks) > 1:
                # Multiple files detected - stream each separately
                print(f"📁 [Multi-File Detection] Found {len(code_blocks)} code files")
                
                yield f"{json.dumps({'event': 'files_detected', 'data': {'total_files': len(code_blocks), 'files': [{'filename': f[0], 'language': f[1], 'size': len(f[2])} for f in code_blocks]}})}\n\n"
                
                for idx, (filename, language, code) in enumerate(code_blocks, 1):
                    # File start event
                    yield f"{json.dumps({'event': 'file_start', 'data': {'filename': filename, 'language': language, 'index': idx, 'total': len(code_blocks)}})}\n\n"
                    
                    # Stream file content in chunks
                    chunks = chunk_text(code, chunk_size=500)
                    for chunk in chunks:
                        yield f"{json.dumps({'event': 'file_chunk', 'data': {'filename': filename, 'content': chunk}})}\n\n"
                        # Small delay to prevent overwhelming frontend
                        await asyncio.sleep(0.01)
                    
                    # File end event
                    yield f"{json.dumps({'event': 'file_end', 'data': {'filename': filename, 'size': len(code)}})}\n\n"
                    
                    print(f"  ✅ File {idx}/{len(code_blocks)}: {filename} ({len(code)} chars)")

            # 7) Store complete message in database
            ai_entry = memory.store_chat_message(
                project_id, role_id, chat_session_id,
                actual_provider, full_response
            )
            memory.insert_audit_log(
                project_id, role_id, chat_session_id,
                actual_provider, "stream_complete", full_response[:300]
            )
            
            # 7a) Generate embedding for AI response (async, don't block on errors)
            try:
                store_message_with_embedding(db, ai_entry.id, full_response)
            except Exception as e:
                print(f"[Embedding] Stream response skipped: {e}")

            # 8) Send completion event
            token_count = memory.count_tokens(full_response)
            yield f"{json.dumps({'event': 'done', 'data': {'status': 'completed', 'full_response': full_response, 'tokens': token_count, 'model': chosen_model, 'provider': actual_provider, 'chat_session_id': chat_session_id}})}\n\n"

            print(f"✅ [Stream Complete] provider={actual_provider} model={chosen_model} tokens={token_count}")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ [Stream Error] {error_msg}")
            yield f"{json.dumps({'event': 'error', 'data': {'error': error_msg}})}\n\n"

    return EventSourceResponse(event_generator())
