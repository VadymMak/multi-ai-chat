"""
Re-export router modules so callers can do:
    from app.routers import ask, chat, ...
Keep this list in sync with main.py.
"""

from __future__ import annotations

import os
from types import ModuleType
from typing import Optional

# Enable extra logging with ROUTERS_DEBUG=1|true|yes|on
_DEBUG = (os.getenv("ROUTERS_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}


def _log(msg: str) -> None:
    if _DEBUG:
        print(f"[routers.__init__] {msg}")


# ---- Required routers (import must succeed; fail fast if missing) ----
try:
    from . import ask
    _log("Loaded: ask")
    from . import ask_ai_to_ai
    _log("Loaded: ask_ai_to_ai")
    from . import ask_ai_to_ai_turn
    _log("Loaded: ask_ai_to_ai_turn")
    from . import youtube
    _log("Loaded: youtube")
    from . import chat
    _log("Loaded: chat")
    from . import projects
    _log("Loaded: projects")
    from . import audit
    _log("Loaded: audit")
    from . import roles
    _log("Loaded: roles")
    from . import balance
    _log("Loaded: balance")
    from . import debate
    _log("Loaded: debate")
except Exception as e:
    # Fail fast with a clear message about which router chain caused the error
    raise ImportError(f"[routers.__init__] Failed importing required routers: {e}") from e


# ---- Optional routers (ok if missing) ----
def _try_import_optional(name: str) -> Optional[ModuleType]:
    try:
        mod = __import__(f"{__name__}.{name}", fromlist=[name])
        _log(f"Loaded (optional): {name}")
        return getattr(mod, name) if hasattr(mod, name) else mod  # export module or 'router' module
    except Exception as exc:
        _log(f"Optional router '{name}' not available: {exc}")
        return None


_upload_file_mod = _try_import_optional("upload_file")
_prompt_template_mod = _try_import_optional("prompt_template")

# Public exports
__all__ = [
    # required
    "ask",
    "ask_ai_to_ai",
    "ask_ai_to_ai_turn",
    "youtube",
    "chat",
    "projects",
    "audit",
    "roles",
    "balance",
    "debate",
]

# add optionals only if present
if _upload_file_mod is not None:
    __all__.append("upload_file")
    upload_file = _upload_file_mod  # type: ignore[assignment]
if _prompt_template_mod is not None:
    __all__.append("prompt_template")
    prompt_template = _prompt_template_mod  # type: ignore[assignment]
