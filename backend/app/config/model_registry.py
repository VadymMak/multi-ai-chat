# app/config/model_registry.py
from __future__ import annotations

from typing import Dict, Literal, TypedDict

# Try modern Required/NotRequired; gracefully degrade if unavailable
_HAS_REQ_NOTREQ = True
try:
    from typing import Required, NotRequired  # Python 3.11+
except Exception:  # pragma: no cover
    try:
        from typing_extensions import Required, NotRequired  # type: ignore
    except Exception:  # pragma: no cover
        _HAS_REQ_NOTREQ = False

Provider = Literal["openai", "anthropic"]

if _HAS_REQ_NOTREQ:
    class ModelInfo(TypedDict):
        provider: Required[Provider]
        model: Required[str]
        # Optional per-model overrides used by factory.ask_model(...)
        temperature: NotRequired[float]
        max_tokens: NotRequired[int]
else:
    # Fallback: permissive TypedDict (runtime data still includes provider/model).
    class ModelInfo(TypedDict, total=False):  # type: ignore[misc]
        provider: Provider
        model: str
        temperature: float
        max_tokens: int

# Registry keys (left side) are what your API accepts as model_key.
# "provider" and "model" are used by the provider wrappers.
MODEL_REGISTRY: Dict[str, ModelInfo] = {
    # -----------------------
    # OpenAI (defaults)
    # -----------------------
    "gpt-4o": {
        "provider": "openai",
        "model": "gpt-4o",
    },
    "gpt-4o-mini": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-4o-mini",
        "max_tokens": 1024,
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "max_tokens": 1024,
    },
    "gpt-3.5-turbo": {
        "provider": "openai",
        "model": "gpt-3.5-turbo",
        "max_tokens": 1024,
    },

    # Optional GPT-5 keys (use only if your account/gateway supports them)
    "gpt-5": {
        "provider": "openai",
        "model": "gpt-5",
    },
    "gpt-5-mini": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-5-mini",
    },
    "gpt-5-nano": {  # factory fallback candidate
        "provider": "openai",
        "model": "gpt-5-nano",
    },
    "gpt-5-chat": {
        "provider": "openai",
        "model": "gpt-5-chat-latest",
    },
    "gpt-5-chat-latest": {
        "provider": "openai",
        "model": "gpt-5-chat-latest",
    },

    # -----------------------
    # Anthropic (Claude)
    # -----------------------
    "claude-3-5-sonnet": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
    },
    # Fallback minis your factory looks for
    "claude-3-5-haiku-20241022": {
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
    },
    "claude-3-5-haiku-latest": {  # ← new alias used by factory fallback
        "provider": "anthropic",
        "model": "claude-3-5-haiku-20241022",
    },
    "claude-3-haiku-20240307": {
        "provider": "anthropic",
        "model": "claude-3-haiku-20240307",
    },
    "claude-3-haiku": {  # ← new alias used by factory fallback
        "provider": "anthropic",
        "model": "claude-3-haiku-20240307",
    },
    # Aliases (full ids)
    "claude-3-5-sonnet-20241022": {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
    },
}
