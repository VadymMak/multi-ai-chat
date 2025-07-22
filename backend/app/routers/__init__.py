# File: app/routers/__init__.py

# Re-export router modules so callers can do:
#   from app.routers import ask, chat, ...
# Keep this list in sync with main.py.

from . import (
    ask,
    ask_ai_to_ai,
    ask_ai_to_ai_turn,
    youtube,
    chat,
    projects,
    audit,
    roles,
)

# Optional routers (imported directly in main.py, but exposed here if present)
try:
    from . import upload_file  # noqa: F401
except Exception:
    upload_file = None  # type: ignore

try:
    from . import prompt_template  # noqa: F401
except Exception:
    prompt_template = None  # type: ignore

__all__ = [
    "ask",
    "ask_ai_to_ai",
    "ask_ai_to_ai_turn",
    "youtube",
    "chat",
    "projects",
    "audit",
    "roles",
    # Optional
    "upload_file",
    "prompt_template",
]
