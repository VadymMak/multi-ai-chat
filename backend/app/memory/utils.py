# File: app/memory/utils.py
from __future__ import annotations

from typing import Iterable, List
import unicodedata

from sqlalchemy.orm import Session

from app.memory.models import Project

# ---- Optional tiktoken import (safe at import time) ----
try:
    import tiktoken  # type: ignore
    try:
        _ENC = tiktoken.get_encoding("o200k_base")
    except Exception:
        try:
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC = None
except Exception:
    _ENC = None  # type: ignore

DEFAULT_MAX_MEMORY_TOKENS = 1000
_CHARS_PER_TOKEN_APPROX = 4  # fallback heuristic


def count_tokens(text: str) -> int:
    """
    Count tokens using the selected encoding. If tiktoken is unavailable or
    the encoding fails, fall back to a rough character-length heuristic.
    """
    if not isinstance(text, str):
        text = str(text or "")
    if not text:
        return 0

    if _ENC is None:
        # ~4 chars per token rough heuristic
        tokens = max(1, len(text) // _CHARS_PER_TOKEN_APPROX)
        return tokens

    try:
        return len(_ENC.encode(text))
    except Exception:
        # Defensive fallback; do not break the request pipeline.
        return max(1, len(text) // _CHARS_PER_TOKEN_APPROX)


def trim_memory(texts: Iterable[str], max_tokens: int = DEFAULT_MAX_MEMORY_TOKENS) -> str:
    """
    Join, tokenize, and trim memory to the last `max_tokens`.
    - Ignores None/empty pieces safely
    - Works even if tiktoken encoding is unavailable
    """
    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = DEFAULT_MAX_MEMORY_TOKENS
    max_tokens = max(1, max_tokens)

    pieces: List[str] = [str(s).strip() for s in texts if isinstance(s, str) and str(s).strip()]
    if not pieces:
        return ""

    joined = "\n\n".join(pieces)

    if _ENC is None:
        # Heuristic fallback: slice last N*4 chars
        approx_chars = max_tokens * _CHARS_PER_TOKEN_APPROX
        tail = joined[-approx_chars:]
        return tail

    try:
        toks = _ENC.encode(joined)
        if len(toks) > max_tokens:
            toks = toks[-max_tokens:]
        return _ENC.decode(toks)
    except Exception as e:
        # If anything goes wrong, do not crash—fallback to simple tail slice
        print(f"[utils.trim_memory] decode fallback due to: {e}")
        approx_chars = max_tokens * _CHARS_PER_TOKEN_APPROX
        return joined[-approx_chars:]


def get_project_structure(db: Session, project_id: int) -> str:
    """
    Retrieve the project's `project_structure` markdown text, safely.
    - Returns empty string if the project or field is missing
    - Always returns a clean, str value
    """
    try:
        pid = int(project_id)
        project = db.query(Project).filter(Project.id == pid).first()
    except Exception as e:
        # Avoid breaking prompt building due to DB or cast errors.
        print(f"⚠️ get_project_structure: failed for project_id={project_id}: {e}")
        return ""

    if not project or not project.project_structure:
        return ""

    text = str(project.project_structure or "").strip()
    return safe_text(text)


def safe_text(s: str) -> str:
    """
    Remove invalid unicode (surrogates), normalize, and ensure UTF-8 safety.
    Matches the stricter approach used elsewhere so API/JSON never breaks.
    """
    if not isinstance(s, str):
        s = str(s or "")

    try:
        # Normalize and drop surrogate characters
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Cs")
        # Ensure it's valid utf-8
        return s.encode("utf-8", "ignore").decode("utf-8")
    except Exception as e:
        print(f"[safe_text warning] {e}")
        return ""
